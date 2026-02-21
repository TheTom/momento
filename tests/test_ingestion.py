"""Ingestion tests — T10.1 and T10.2.

Tests for partial failure resilience and summary output during JSONL ingestion.
Creates temporary JSONL files in tmp_path to test the ingestion pipeline.
"""

import json
import os

import pytest

from momento.db import ensure_db
from tests.mock_data import MOCK_PROJECT_ID, MOCK_PROJECT_NAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_jsonl_line(content, entry_type="session_state", tags=None):
    """Create a valid JSONL line for ingestion."""
    return json.dumps({
        "content": content,
        "type": entry_type,
        "tags": tags or ["server"],
        "project_id": MOCK_PROJECT_ID,
        "project_name": MOCK_PROJECT_NAME,
        "branch": "main",
        "source_type": "compaction",
        "confidence": 0.8,
    })


def _make_valid_jsonl_file(tmp_path, filename, num_valid=10, num_malformed=0):
    """Create a JSONL file with valid and optionally malformed lines.

    Returns the file path.
    """
    filepath = tmp_path / filename
    lines = []

    # Valid entries
    for i in range(num_valid):
        lines.append(_make_valid_jsonl_line(
            content=f"Valid entry {i+1}: checkpoint for migration step {i+1}.",
            entry_type="session_state",
            tags=["server", f"step-{i+1}"],
        ))

    # Malformed entries interspersed
    malformed_positions = []
    for i in range(num_malformed):
        pos = (i + 1) * (num_valid // (num_malformed + 1))
        malformed_positions.append(pos)

    # Insert malformed lines at calculated positions
    for i, pos in enumerate(sorted(malformed_positions, reverse=True)):
        if i % 2 == 0:
            # Completely invalid JSON
            lines.insert(pos, "{this is not valid json at all!!!")
        else:
            # Valid JSON but missing required fields
            lines.insert(pos, json.dumps({"incomplete": True}))

    filepath.write_text("\n".join(lines) + "\n")
    return str(filepath)


# ===========================================================================
# T10.1 — Partial failure resilience
# ===========================================================================

@pytest.mark.nice_to_have
class TestPartialFailureResilience:
    """T10.1 — JSONL with 10 valid + 2 malformed lines, 10 stored."""

    def test_valid_entries_stored_despite_malformed_lines(self, tmp_path):
        """T10.1: 10 valid entries stored, 2 malformed lines skipped."""
        # TODO: Import ingest module once it exists
        # from momento.ingest import ingest_file
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        jsonl_path = _make_valid_jsonl_file(
            tmp_path, "mixed.jsonl", num_valid=10, num_malformed=2
        )

        result = ingest_file(conn, jsonl_path)

        # Verify 10 entries stored
        cursor = conn.execute("SELECT COUNT(*) FROM knowledge")
        count = cursor.fetchone()[0]
        assert count == 10, (
            f"Expected 10 entries stored (2 malformed skipped), got {count}"
        )

        conn.close()

    def test_process_does_not_crash_on_malformed(self, tmp_path):
        """T10.1: ingestion completes successfully even with malformed lines."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        jsonl_path = _make_valid_jsonl_file(
            tmp_path, "all_bad.jsonl", num_valid=3, num_malformed=2
        )

        # Should NOT raise any exception
        result = ingest_file(conn, jsonl_path)

        # Should have returned a result (not crashed)
        assert result is not None, "ingest_file should return a result dict"
        conn.close()

    def test_completely_malformed_file_handled(self, tmp_path):
        """T10.1: file with all malformed lines produces 0 entries, no crash."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        # Create file with only malformed lines
        bad_file = tmp_path / "all_malformed.jsonl"
        bad_file.write_text(
            "{bad json line 1\n"
            "not even close to json\n"
            "{\"incomplete\": true}\n"
        )

        result = ingest_file(conn, str(bad_file))

        cursor = conn.execute("SELECT COUNT(*) FROM knowledge")
        count = cursor.fetchone()[0]
        assert count == 0, "All-malformed file should produce 0 entries"
        conn.close()


# ===========================================================================
# T10.2 — Summary output
# ===========================================================================

class TestSummaryOutput:
    """T10.2 — ingestion prints files/lines/entries/skipped/dupes counts."""

    def test_summary_includes_all_counts(self, tmp_path):
        """T10.2: summary includes files, lines, entries stored, skipped, dupes."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        jsonl_path = _make_valid_jsonl_file(
            tmp_path, "summary_test.jsonl", num_valid=10, num_malformed=2
        )

        result = ingest_file(conn, jsonl_path)

        # Result should include summary counts
        assert "entries_stored" in result, "Summary should include entries_stored"
        assert "lines_skipped" in result, "Summary should include lines_skipped"
        assert "lines_processed" in result, "Summary should include lines_processed"

        assert result["entries_stored"] == 10, (
            f"Expected 10 entries stored, got {result['entries_stored']}"
        )
        assert result["lines_skipped"] == 2, (
            f"Expected 2 lines skipped, got {result['lines_skipped']}"
        )

        conn.close()

    def test_summary_includes_dupe_count(self, tmp_path):
        """T10.2: summary tracks duplicate entries skipped."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        # Create file with some duplicates
        filepath = tmp_path / "dupes.jsonl"
        content = "Duplicate entry: same content repeated."
        line = _make_valid_jsonl_line(content)

        # 5 identical lines + 3 unique
        lines = [line] * 5
        for i in range(3):
            lines.append(_make_valid_jsonl_line(f"Unique entry {i+1}."))

        filepath.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(filepath))

        # Should store 4 unique entries (1 from the 5 dupes + 3 unique)
        assert result.get("entries_stored", 0) == 4, (
            f"Expected 4 entries stored, got {result.get('entries_stored')}"
        )
        assert result.get("dupes_skipped", 0) == 4, (
            f"Expected 4 dupes skipped, got {result.get('dupes_skipped')}"
        )

        conn.close()

    def test_summary_for_multiple_files(self, tmp_path):
        """T10.2: summary accumulates across multiple files."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_files

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        file1 = _make_valid_jsonl_file(tmp_path, "file1.jsonl", num_valid=5, num_malformed=1)
        file2 = _make_valid_jsonl_file(tmp_path, "file2.jsonl", num_valid=3, num_malformed=0)

        result = ingest_files(conn, [file1, file2])

        assert "files_processed" in result, "Summary should include files_processed"
        assert result["files_processed"] == 2
        assert result.get("entries_stored", 0) == 8  # 5 + 3
        assert result.get("lines_skipped", 0) == 1  # 1 malformed in file1

        conn.close()

    def test_summary_skips_unreadable_file_and_continues(self, tmp_path):
        """Ingestion should skip unreadable files and continue processing others."""
        pytest.importorskip("momento.ingest", reason="ingest module not yet implemented")
        from momento.ingest import ingest_files

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        good_file = _make_valid_jsonl_file(tmp_path, "good.jsonl", num_valid=3, num_malformed=0)
        missing_file = str(tmp_path / "missing.jsonl")

        result = ingest_files(conn, [good_file, missing_file])

        assert result.get("files_processed", 0) == 1
        assert result.get("files_skipped", 0) == 1
        assert result.get("entries_stored", 0) == 3

        count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 3, "Good file entries should still be ingested"

        conn.close()

"""Ingestion tests — T10.1, T10.2, and project/all ingestion.

Tests for partial failure resilience, summary output, compaction extraction,
error+resolution pairs, keyword filtering, and CLI integration.
"""

import json
import os

import pytest

from momento.db import ensure_db
from momento.ingest import ingest_project, ingest_all
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
            content=f"Valid entry {i+1} from {filename}: checkpoint for migration step {i+1}.",
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

    def test_cross_file_db_level_dedup(self, tmp_path):
        """Duplicate content across files is caught by DB unique constraint."""
        from momento.ingest import ingest_files

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        # Same content in both files → second file's entry is a DB-level dupe
        shared = _make_valid_jsonl_line(content="Identical entry across files.")
        file1 = tmp_path / "f1.jsonl"
        file2 = tmp_path / "f2.jsonl"
        file1.write_text(shared + "\n")
        file2.write_text(shared + "\n")

        result = ingest_files(conn, [str(file1), str(file2)])

        assert result["entries_stored"] == 1
        assert result["dupes_skipped"] == 1  # DB-level dupe (line 105)
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


# ===========================================================================
# Coverage gap tests — ingest.py edge-case branches
# ===========================================================================


class TestIngestCoverageGaps:
    """Tests targeting specific uncovered lines in ingest.py."""

    def test_blank_lines_skipped_in_jsonl(self, tmp_path):
        """ingest.py line 38: blank/whitespace-only lines are skipped.

        JSONL files may contain blank lines between entries. These should
        be silently skipped without incrementing lines_processed.
        """
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        filepath = tmp_path / "blanks.jsonl"
        lines = [
            "",                                           # blank
            _make_valid_jsonl_line("Entry one"),          # valid
            "   ",                                        # whitespace-only
            "",                                           # blank
            _make_valid_jsonl_line("Entry two"),          # valid
            "\t",                                         # tab-only
        ]
        filepath.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(filepath))

        assert result["lines_processed"] == 2, (
            f"Only non-blank lines should count. Got {result['lines_processed']}"
        )
        assert result["entries_stored"] == 2
        assert result["lines_skipped"] == 0

        conn.close()

    def test_sqlite_error_during_insert_rolls_back(self, tmp_path):
        """ingest.py lines 93-95: sqlite3.Error during insert triggers rollback.

        Drops knowledge_stats table so the INSERT INTO knowledge_stats
        raises OperationalError, triggering the except sqlite3.Error path.
        """
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        # Remove knowledge_stats so the stats INSERT fails
        conn.execute("DROP TABLE knowledge_stats")
        conn.commit()

        filepath = tmp_path / "error.jsonl"
        filepath.write_text(
            _make_valid_jsonl_line("Entry that will fail on stats insert.") + "\n"
        )

        result = ingest_file(conn, str(filepath))

        # The entry should be skipped (rolled back) due to sqlite3.Error
        assert result["lines_skipped"] == 1, (
            f"sqlite3.Error should cause line to be skipped. Got {result['lines_skipped']}"
        )

        # No rows should persist (rollback undoes the knowledge INSERT)
        count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 0, "Rollback should prevent partial inserts"

        conn.close()

    def test_invalid_field_types_are_skipped_not_crashed(self, tmp_path):
        """Malformed JSON object fields should be skipped safely."""
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        bad_file = tmp_path / "bad_types.jsonl"
        lines = [
            json.dumps({
                "content": 123,
                "type": "decision",
                "tags": ["server"],
                "project_id": MOCK_PROJECT_ID,
                "project_name": MOCK_PROJECT_NAME,
            }),
            json.dumps({
                "content": "valid text but invalid tags type",
                "type": "decision",
                "tags": 123,
                "project_id": MOCK_PROJECT_ID,
                "project_name": MOCK_PROJECT_NAME,
            }),
        ]
        bad_file.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(bad_file))
        assert result["entries_stored"] == 0
        assert result["lines_skipped"] == 2
        assert conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0] == 0
        conn.close()

    def test_null_project_fields_are_allowed(self, tmp_path):
        """Global/cross-project JSONL entries with null project fields should ingest."""
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        filepath = tmp_path / "global.jsonl"
        filepath.write_text(
            json.dumps({
                "content": "Global knowledge entry.",
                "type": "decision",
                "tags": ["global"],
                "project_id": None,
                "project_name": None,
            }) + "\n"
        )

        result = ingest_file(conn, str(filepath))
        assert result["entries_stored"] == 1
        row = conn.execute(
            "SELECT project_id, project_name FROM knowledge LIMIT 1"
        ).fetchone()
        assert row == (None, None)
        conn.close()

    def test_ingest_project_returns_empty_for_nonexistent_dir(self, tmp_path):
        """ingest_project returns zero-count summary for non-existent project dir."""
        from momento.ingest import ingest_project

        conn = ensure_db(str(tmp_path / "test.db"))
        result = ingest_project(conn, "/nonexistent/project/dir")
        assert result["files_processed"] == 0
        assert result["entries_stored"] == 0
        conn.close()

    def test_ingest_all_returns_empty_when_no_projects(self, tmp_path, monkeypatch):
        """ingest_all returns zero-count summary when no Claude Code projects exist."""
        from momento.ingest import ingest_all
        import momento.ingest as ingest_mod

        # Point to an empty temp dir instead of real ~/.claude/projects
        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", tmp_path / "empty")
        conn = ensure_db(str(tmp_path / "test.db"))
        result = ingest_all(conn)
        assert result["projects_scanned"] == 0
        assert result["entries_stored"] == 0
        conn.close()

    def test_invalid_type_field_skipped(self, tmp_path):
        """Entries with invalid type values are skipped (covers ingest.py:134)."""
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        bad_file = tmp_path / "bad_type.jsonl"
        lines = [
            json.dumps({
                "content": "Valid content",
                "type": "invalid_type",  # not in allowed set
                "tags": ["server"],
                "project_id": MOCK_PROJECT_ID,
                "project_name": MOCK_PROJECT_NAME,
            }),
        ]
        bad_file.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(bad_file))
        assert result["entries_stored"] == 0
        assert result["lines_skipped"] == 1
        conn.close()

    def test_invalid_project_id_field_skipped(self, tmp_path):
        """Entries with non-string project_id are skipped (covers ingest.py:142)."""
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        bad_file = tmp_path / "bad_pid.jsonl"
        lines = [
            json.dumps({
                "content": "Valid content",
                "type": "decision",
                "tags": ["server"],
                "project_id": 12345,  # not a string
                "project_name": MOCK_PROJECT_NAME,
            }),
        ]
        bad_file.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(bad_file))
        assert result["entries_stored"] == 0
        assert result["lines_skipped"] == 1
        conn.close()

    def test_invalid_project_name_field_skipped(self, tmp_path):
        """Entries with non-string project_name are skipped (covers ingest.py:144)."""
        from momento.ingest import ingest_file

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        bad_file = tmp_path / "bad_pname.jsonl"
        lines = [
            json.dumps({
                "content": "Valid content",
                "type": "decision",
                "tags": ["server"],
                "project_id": MOCK_PROJECT_ID,
                "project_name": 999,  # invalid type (None is now allowed for global entries)
            }),
        ]
        bad_file.write_text("\n".join(lines) + "\n")

        result = ingest_file(conn, str(bad_file))
        assert result["entries_stored"] == 0
        assert result["lines_skipped"] == 1
        conn.close()


# ===========================================================================
# New ingestion feature tests — ingest_project, ingest_all, extraction
# ===========================================================================


def _make_compaction_summary_entry(content, git_branch="main", session_id="abc123"):
    """Create a raw Claude Code JSONL entry that is a compaction summary."""
    return json.dumps({
        "parentUuid": "parent-uuid",
        "isSidechain": False,
        "type": "user",
        "isCompactSummary": True,
        "sessionId": session_id,
        "gitBranch": git_branch,
        "message": {
            "role": "user",
            "content": content,
        },
        "uuid": f"uuid-{hash(content) % 100000}",
        "timestamp": "2026-02-21T10:00:00.000Z",
    })


def _make_error_tool_result_entry(error_content, git_branch="main"):
    """Create a raw Claude Code JSONL user entry with an is_error tool_result."""
    return json.dumps({
        "parentUuid": "parent-uuid",
        "type": "user",
        "sessionId": "sess-123",
        "gitBranch": git_branch,
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": error_content,
                    "is_error": True,
                    "tool_use_id": "tool-use-123",
                },
            ],
        },
        "uuid": "uuid-error",
        "timestamp": "2026-02-21T10:00:00.000Z",
    })


def _make_assistant_response_entry(text_content, git_branch="main"):
    """Create a raw Claude Code JSONL assistant entry with a text response."""
    return json.dumps({
        "parentUuid": "uuid-error",
        "type": "assistant",
        "sessionId": "sess-123",
        "gitBranch": git_branch,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "text",
                    "text": text_content,
                },
            ],
        },
        "uuid": "uuid-resolution",
        "timestamp": "2026-02-21T10:01:00.000Z",
    })


def _make_plain_user_entry(content, git_branch="main"):
    """Create a plain user message (not compaction, not error)."""
    return json.dumps({
        "parentUuid": "parent-uuid",
        "type": "user",
        "sessionId": "sess-123",
        "gitBranch": git_branch,
        "message": {
            "role": "user",
            "content": content,
        },
        "uuid": "uuid-plain",
        "timestamp": "2026-02-21T10:00:00.000Z",
    })


def _setup_claude_project_dir(tmp_path, project_path, jsonl_files):
    """Set up a fake ~/.claude/projects/{encoded} directory with JSONL files.

    Args:
        tmp_path: pytest tmp_path fixture
        project_path: e.g. "/Users/tom/myproject" — will be encoded
        jsonl_files: dict of {filename: list_of_jsonl_lines}

    Returns:
        The fake projects root dir (to monkeypatch _CLAUDE_PROJECTS_DIR).
    """
    from momento.ingest import _encode_project_path

    projects_root = tmp_path / "claude_projects"
    encoded = _encode_project_path(project_path)
    project_dir = projects_root / encoded
    project_dir.mkdir(parents=True)

    for filename, lines in jsonl_files.items():
        filepath = project_dir / filename
        filepath.write_text("\n".join(lines) + "\n")

    return projects_root


class TestEncodeProjectPath:
    """Test the path encoding used to map project dirs to Claude Code dirs."""

    def test_encode_simple_path(self):
        from momento.ingest import _encode_project_path
        result = _encode_project_path("/Users/tom/myproject")
        assert result == "-Users-tom-myproject"

    def test_encode_nested_path(self):
        from momento.ingest import _encode_project_path
        result = _encode_project_path("/Users/tom/dev/momento")
        assert result == "-Users-tom-dev-momento"

    def test_encode_trailing_slash(self):
        from momento.ingest import _encode_project_path
        result = _encode_project_path("/Users/tom/myproject/")
        assert result == "-Users-tom-myproject"


class TestDecodeProjectPath:
    """Test the path decoding used to reverse Claude Code encoded dirs."""

    def test_decode_simple_path(self):
        from momento.ingest import _decode_project_path
        result = _decode_project_path("-Users-tom-myproject")
        assert result == "/Users/tom/myproject"

    def test_decode_nested_path(self):
        from momento.ingest import _decode_project_path
        result = _decode_project_path("-Users-tom-dev-momento")
        assert result == "/Users/tom/dev/momento"


class TestKeywordHeuristicFilter:
    """Test the keyword filter that decides if a compaction summary is worth keeping."""

    def test_passes_with_keyword(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("We decided to use PostgreSQL because it supports ACID")

    def test_passes_with_error_keyword(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("Found a race condition in the webhook handler")

    def test_passes_with_security_keyword(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("Important security concern: tokens must be rotated")

    def test_fails_without_keywords(self):
        from momento.ingest import _passes_keyword_filter
        assert not _passes_keyword_filter("The user said hello and I responded with a greeting")

    def test_fails_on_empty_string(self):
        from momento.ingest import _passes_keyword_filter
        assert not _passes_keyword_filter("")

    def test_case_insensitive(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("NEVER use raw SQL without parameterized queries")

    def test_passes_with_gotcha(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("This is a gotcha worth remembering")

    def test_passes_with_tradeoff(self):
        from momento.ingest import _passes_keyword_filter
        assert _passes_keyword_filter("There is a tradeoff between speed and safety")


class TestClassifyCompactionType:
    """Test the type classifier for compaction summaries."""

    def test_classifies_gotcha(self):
        from momento.ingest import _classify_compaction_type
        assert _classify_compaction_type("Found a race condition in the handler") == "gotcha"

    def test_classifies_decision(self):
        from momento.ingest import _classify_compaction_type
        assert _classify_compaction_type("We chose PostgreSQL instead of MongoDB") == "decision"

    def test_classifies_pattern(self):
        from momento.ingest import _classify_compaction_type
        assert _classify_compaction_type("The pattern we always follow for API routes") == "pattern"

    def test_classifies_session_state_fallback(self):
        from momento.ingest import _classify_compaction_type
        assert _classify_compaction_type("Completed the migration and moved on") == "session_state"

    def test_gotcha_takes_priority_over_decision(self):
        """Gotcha signals should take priority over decision signals."""
        from momento.ingest import _classify_compaction_type
        # Contains both "chose" (decision) and "bug" (gotcha)
        assert _classify_compaction_type("We chose this approach because of a bug") == "gotcha"


class TestExtractEntriesFromSession:
    """Test extraction of entries from raw Claude Code session JSONL files."""

    def test_extracts_compaction_summary(self, tmp_path):
        """Compaction summaries with insight keywords are extracted."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        filepath.write_text(
            _make_compaction_summary_entry(
                "We decided to use server-side sessions because JWTs can't be revoked."
            ) + "\n"
        )

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        assert len(entries) == 1
        assert entries[0]["type"] == "decision"
        assert entries[0]["source_type"] == "compaction"
        assert entries[0]["confidence"] == 0.8
        assert entries[0]["project_id"] == MOCK_PROJECT_ID
        assert "compaction" in entries[0]["tags"]

    def test_filters_out_fluff_compaction(self, tmp_path):
        """Compaction summaries without insight keywords are skipped."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        filepath.write_text(
            _make_compaction_summary_entry(
                "The user asked me to format the code and I did so."
            ) + "\n"
        )

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        assert len(entries) == 0

    def test_extracts_error_resolution_pair(self, tmp_path):
        """Error+resolution pairs are extracted as gotcha entries."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        lines = [
            _make_error_tool_result_entry(
                "Exit code 1\nConnection refused: MongoDB is not running"
            ),
            _make_assistant_response_entry(
                "The MongoDB container needs to be started. Run docker-compose up -d mongodb."
            ),
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        assert len(entries) == 1
        assert entries[0]["type"] == "gotcha"
        assert entries[0]["source_type"] == "error_pair"
        assert entries[0]["confidence"] == 0.7
        assert "Error:" in entries[0]["content"]
        assert "Resolution:" in entries[0]["content"]

    def test_error_without_resolution_is_skipped(self, tmp_path):
        """Error tool results without a following resolution are not extracted."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        # Only an error, no subsequent assistant message
        filepath.write_text(
            _make_error_tool_result_entry("Some error occurred") + "\n"
        )

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        assert len(entries) == 0

    def test_handles_unreadable_file(self, tmp_path):
        """Unreadable file returns empty list, no crash."""
        from momento.ingest import _extract_entries_from_session

        entries = _extract_entries_from_session(
            str(tmp_path / "nonexistent.jsonl"), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert entries == []

    def test_handles_empty_file(self, tmp_path):
        """Empty file returns empty list."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "empty.jsonl"
        filepath.write_text("")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert entries == []

    def test_deduplicates_within_session(self, tmp_path):
        """Duplicate compaction summaries within a session are deduplicated."""
        from momento.ingest import _extract_entries_from_session

        content = "We decided to always validate input because of security concerns."
        filepath = tmp_path / "session.jsonl"
        lines = [
            _make_compaction_summary_entry(content),
            _make_compaction_summary_entry(content),  # duplicate
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        assert len(entries) == 1

    def test_mixed_entries_extraction(self, tmp_path):
        """Session with compaction + errors + plain messages extracts correctly."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        lines = [
            _make_plain_user_entry("just a normal message"),
            _make_compaction_summary_entry(
                "We decided to use Redis because it has built-in TTL support."
            ),
            _make_error_tool_result_entry("Exit code 1\nPermission denied"),
            _make_assistant_response_entry("You need to run with sudo or fix file permissions."),
            _make_plain_user_entry("thanks"),
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )

        # 1 compaction summary + 1 error-resolution pair
        assert len(entries) == 2
        types = {e["type"] for e in entries}
        source_types = {e["source_type"] for e in entries}
        assert "decision" in types
        assert "gotcha" in types
        assert "compaction" in source_types
        assert "error_pair" in source_types


class TestIngestProject:
    """Test ingest_project() with mock Claude Code session directories."""

    def test_ingest_project_with_compaction_summaries(self, tmp_path, monkeypatch):
        """ingest_project extracts compaction summaries and stores them."""
        import momento.ingest as ingest_mod

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [
                _make_compaction_summary_entry(
                    "We chose PostgreSQL because ACID transactions are important for billing."
                ),
                _make_compaction_summary_entry(
                    "Found a bug in the webhook handler — race condition on concurrent requests."
                ),
            ],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, project_path)

        assert result["files_processed"] == 1
        assert result["entries_stored"] == 2

        # Verify entries are in DB
        count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 2

        conn.close()

    def test_ingest_project_with_error_pairs(self, tmp_path, monkeypatch):
        """ingest_project extracts error+resolution pairs."""
        import momento.ingest as ingest_mod

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [
                _make_error_tool_result_entry("Exit code 1\nDocker daemon not running"),
                _make_assistant_response_entry("Start Docker Desktop or run systemctl start docker."),
            ],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, project_path)

        assert result["files_processed"] == 1
        assert result["entries_stored"] == 1

        # Verify it's a gotcha entry
        row = conn.execute("SELECT type, source_type FROM knowledge").fetchone()
        assert row[0] == "gotcha"
        assert row[1] == "error_pair"

        conn.close()

    def test_ingest_project_no_session_dir(self, tmp_path, monkeypatch):
        """ingest_project returns zeros when no Claude Code session dir exists."""
        import momento.ingest as ingest_mod

        empty_root = tmp_path / "empty_claude"
        empty_root.mkdir()
        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", empty_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, str(tmp_path / "some_project"))

        assert result["files_processed"] == 0
        assert result["entries_stored"] == 0

        conn.close()

    def test_ingest_project_empty_session_dir(self, tmp_path, monkeypatch):
        """ingest_project returns zeros when session dir exists but has no .jsonl files."""
        import momento.ingest as ingest_mod
        from momento.ingest import _encode_project_path

        project_path = str(tmp_path / "empty_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = tmp_path / "claude_projects"
        encoded = _encode_project_path(project_path)
        session_dir = projects_root / encoded
        session_dir.mkdir(parents=True)
        # No .jsonl files, just an empty directory

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, project_path)

        assert result["files_processed"] == 0
        assert result["entries_stored"] == 0

        conn.close()

    def test_ingest_project_filters_fluff_summaries(self, tmp_path, monkeypatch):
        """Compaction summaries without insight keywords are not stored."""
        import momento.ingest as ingest_mod

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [
                # This one has keywords — should be stored
                _make_compaction_summary_entry(
                    "We decided to use TypeScript for the frontend."
                ),
                # This one is fluff — should be filtered out
                _make_compaction_summary_entry(
                    "I formatted the code and ran the linter."
                ),
            ],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, project_path)

        assert result["entries_stored"] == 1
        conn.close()

    def test_ingest_project_multiple_session_files(self, tmp_path, monkeypatch):
        """ingest_project processes all .jsonl files in the session dir."""
        import momento.ingest as ingest_mod

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [
                _make_compaction_summary_entry(
                    "Decided to use Redis because of its TTL support."
                ),
            ],
            "session2.jsonl": [
                _make_compaction_summary_entry(
                    "Found a security bug in the auth handler."
                ),
            ],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_project(conn, project_path)

        assert result["files_processed"] == 2
        assert result["entries_stored"] == 2

        conn.close()


class TestIngestAll:
    """Test ingest_all() scanning multiple project directories."""

    def test_ingest_all_multiple_projects(self, tmp_path, monkeypatch):
        """ingest_all scans all subdirectories with .jsonl files."""
        import momento.ingest as ingest_mod

        projects_root = tmp_path / "claude_projects"

        # Project 1: has sessions
        proj1_path = str(tmp_path / "project_alpha")
        os.makedirs(proj1_path, exist_ok=True)
        encoded1 = ingest_mod._encode_project_path(proj1_path)
        proj1_dir = projects_root / encoded1
        proj1_dir.mkdir(parents=True)
        (proj1_dir / "sess1.jsonl").write_text(
            _make_compaction_summary_entry(
                "Chose microservices because of scaling constraints."
            ) + "\n"
        )

        # Project 2: has sessions
        proj2_path = str(tmp_path / "project_beta")
        os.makedirs(proj2_path, exist_ok=True)
        encoded2 = ingest_mod._encode_project_path(proj2_path)
        proj2_dir = projects_root / encoded2
        proj2_dir.mkdir(parents=True)
        (proj2_dir / "sess1.jsonl").write_text(
            _make_compaction_summary_entry(
                "Found a bug in the payment processing pipeline."
            ) + "\n"
        )

        # Project 3: empty dir (no .jsonl files) — should be skipped
        proj3_dir = projects_root / "-empty-project"
        proj3_dir.mkdir(parents=True)

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_all(conn)

        assert result["projects_scanned"] == 2  # only 2 with .jsonl files
        assert result["entries_stored"] == 2  # 1 from each project

        conn.close()

    def test_ingest_all_empty_projects_dir(self, tmp_path, monkeypatch):
        """ingest_all returns zeros when projects dir is empty."""
        import momento.ingest as ingest_mod

        empty_root = tmp_path / "empty_claude"
        empty_root.mkdir()
        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", empty_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_all(conn)

        assert result["projects_scanned"] == 0
        assert result["entries_stored"] == 0

        conn.close()

    def test_ingest_all_nonexistent_projects_dir(self, tmp_path, monkeypatch):
        """ingest_all returns zeros when ~/.claude/projects doesn't exist."""
        import momento.ingest as ingest_mod

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR",
                            tmp_path / "does_not_exist")

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_all(conn)

        assert result["projects_scanned"] == 0
        conn.close()

    def test_ingest_all_accumulates_totals(self, tmp_path, monkeypatch):
        """ingest_all accumulates file/entry counts across all projects."""
        import momento.ingest as ingest_mod

        projects_root = tmp_path / "claude_projects"

        # Project with 2 session files, each with 1 entry
        proj_path = str(tmp_path / "multifile_project")
        os.makedirs(proj_path, exist_ok=True)
        encoded = ingest_mod._encode_project_path(proj_path)
        proj_dir = projects_root / encoded
        proj_dir.mkdir(parents=True)

        (proj_dir / "sess1.jsonl").write_text(
            _make_compaction_summary_entry(
                "Important constraint: always validate user input."
            ) + "\n"
        )
        (proj_dir / "sess2.jsonl").write_text(
            _make_compaction_summary_entry(
                "Decided to use connection pooling because of performance."
            ) + "\n"
        )

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        result = ingest_all(conn)

        assert result["projects_scanned"] == 1
        assert result["files_processed"] == 2
        assert result["entries_stored"] == 2

        conn.close()


class TestCLIIngestIntegration:
    """Test CLI integration for ingest command with new modes."""

    def test_cli_ingest_no_args_calls_ingest_project(self, db, capsys, tmp_path):
        """momento ingest (no args) calls ingest_project for current dir."""
        from types import SimpleNamespace
        from momento.cli import cmd_ingest

        args = SimpleNamespace(files=[], ingest_all=False, dir=str(tmp_path))
        cmd_ingest(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        out = capsys.readouterr().out
        assert "Files:" in out
        assert "Stored:" in out

    def test_cli_ingest_all_flag(self, tmp_path, capsys, monkeypatch):
        """momento ingest --all calls ingest_all."""
        from types import SimpleNamespace
        from momento.cli import cmd_ingest
        import momento.ingest as ingest_mod

        # Empty projects dir so it doesn't scan real files
        empty_root = tmp_path / "empty_claude"
        empty_root.mkdir()
        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", empty_root)

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        args = SimpleNamespace(files=[], ingest_all=True, dir=".")
        cmd_ingest(args, conn, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        out = capsys.readouterr().out
        assert "Projects:" in out  # --all mode shows project count
        assert "Files:" in out

        conn.close()

    def test_cli_ingest_with_files_still_works(self, db, capsys, tmp_path):
        """momento ingest file.jsonl still works with explicit file paths."""
        from types import SimpleNamespace
        from momento.cli import cmd_ingest

        jsonl = tmp_path / "test.jsonl"
        line = json.dumps({
            "content": "Explicit file ingest test.",
            "type": "decision",
            "tags": ["server"],
            "project_id": MOCK_PROJECT_ID,
            "project_name": MOCK_PROJECT_NAME,
            "branch": "main",
        })
        jsonl.write_text(line + "\n")

        args = SimpleNamespace(files=[str(jsonl)], ingest_all=False, dir=".")
        cmd_ingest(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        out = capsys.readouterr().out
        assert "Stored:" in out

    def test_cli_main_ingest_all(self, tmp_path, monkeypatch, capsys):
        """Integration: main() with 'ingest --all' dispatches correctly."""
        from unittest.mock import patch
        from momento.cli import main as cli_main
        import momento.ingest as ingest_mod

        db_path = str(tmp_path / "test.db")
        empty_root = tmp_path / "empty_claude"
        empty_root.mkdir()
        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", empty_root)

        monkeypatch.setattr("sys.argv", ["momento", "--db", db_path, "ingest", "--all"])
        with patch("momento.cli.resolve_project_id",
                   return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME)):
            with patch("momento.cli.resolve_branch", return_value="main"):
                cli_main()

        out = capsys.readouterr().out
        assert "Projects:" in out


# ===========================================================================
# Coverage gap tests — _extract_entries_from_session edge cases
# ===========================================================================


class TestExtractEntriesEdgeCases:
    """Cover uncovered branches in _extract_entries_from_session."""

    def test_malformed_json_in_session_file(self, tmp_path):
        """Malformed JSON lines in session file are silently skipped."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        lines = [
            "{not valid json at all!!!",
            _make_compaction_summary_entry(
                "We decided to use PostgreSQL because ACID matters."
            ),
            "another broken line {{{",
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert len(entries) == 1

    def test_blank_lines_in_session_file(self, tmp_path):
        """Blank lines are skipped in both passes."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        lines = [
            "",
            "   ",
            _make_compaction_summary_entry(
                "We chose Redis because of TTL support."
            ),
            "",
            _make_error_tool_result_entry("Exit code 1\nPermission denied"),
            "  ",
            _make_assistant_response_entry("Fix: run with sudo."),
            "",
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        # 1 compaction + 1 error pair
        assert len(entries) == 2

    def test_error_pair_with_string_assistant_content(self, tmp_path):
        """Assistant response with string content (not list) is extracted."""
        from momento.ingest import _extract_entries_from_session

        # Create assistant entry with string content instead of list
        error_entry = _make_error_tool_result_entry("ModuleNotFoundError: No module named 'foo'")
        assistant_entry = json.dumps({
            "parentUuid": "uuid-error",
            "type": "assistant",
            "sessionId": "sess-123",
            "gitBranch": "main",
            "message": {
                "role": "assistant",
                "content": "Install the missing module with pip install foo.",
            },
            "uuid": "uuid-resolution-str",
            "timestamp": "2026-02-21T10:01:00.000Z",
        })

        filepath = tmp_path / "session.jsonl"
        filepath.write_text(error_entry + "\n" + assistant_entry + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert len(entries) == 1
        assert "Resolution:" in entries[0]["content"]

    def test_forward_scan_skips_malformed_and_blanks(self, tmp_path):
        """Forward scan for resolution skips blank/malformed lines and non-assistant types."""
        from momento.ingest import _extract_entries_from_session

        filepath = tmp_path / "session.jsonl"
        lines = [
            _make_error_tool_result_entry("Exit code 1\nConnection refused"),
            "",                                    # blank line
            "{broken json in forward scan",        # malformed
            _make_plain_user_entry("not assistant"),  # non-assistant type
            _make_assistant_response_entry("Start the database service first."),
        ]
        filepath.write_text("\n".join(lines) + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert len(entries) == 1
        assert "Resolution:" in entries[0]["content"]


    def test_user_message_with_list_content_but_no_error(self, tmp_path):
        """User message with list content but no is_error blocks is skipped (line 298)."""
        from momento.ingest import _extract_entries_from_session

        # User message with tool_result that is NOT an error
        non_error_user = json.dumps({
            "parentUuid": "parent-uuid",
            "type": "user",
            "sessionId": "sess-123",
            "gitBranch": "main",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": "Success: file written",
                        "is_error": False,
                        "tool_use_id": "tool-123",
                    },
                ],
            },
            "uuid": "uuid-non-error",
            "timestamp": "2026-02-21T10:00:00.000Z",
        })

        filepath = tmp_path / "session.jsonl"
        filepath.write_text(non_error_user + "\n")

        entries = _extract_entries_from_session(
            str(filepath), MOCK_PROJECT_ID, MOCK_PROJECT_NAME
        )
        assert len(entries) == 0


class TestInsertExtractedEntryEdgeCases:
    """Cover _insert_extracted_entry sqlite error path."""

    def test_insert_extracted_entry_sqlite_error(self, tmp_path):
        """sqlite3.Error during insert returns False."""
        from momento.ingest import _insert_extracted_entry

        db_path = str(tmp_path / "test.db")
        conn = ensure_db(db_path)

        # Drop knowledge_stats table to trigger sqlite3.Error
        conn.execute("DROP TABLE knowledge_stats")
        conn.commit()

        entry = {
            "content": "Test entry that will fail on stats insert.",
            "type": "decision",
            "tags": ["server"],
            "project_id": MOCK_PROJECT_ID,
            "project_name": MOCK_PROJECT_NAME,
            "branch": "main",
            "source_type": "compaction",
            "confidence": 0.8,
        }

        result = _insert_extracted_entry(conn, entry)
        assert result is False

        conn.close()


class TestDecodeProjectPathEdgeCases:
    """Cover _decode_project_path without leading dash."""

    def test_decode_without_leading_dash(self):
        from momento.ingest import _decode_project_path
        result = _decode_project_path("no-leading-dash")
        assert result == "no/leading/dash"


class TestIngestProjectDupesCounting:
    """Cover dupes_skipped path in ingest_project (line 470)."""

    def test_ingest_project_counts_dupes_across_sessions(self, tmp_path, monkeypatch):
        """Same compaction content in two session files → second is a dupe."""
        import momento.ingest as ingest_mod

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        # Same content in both session files
        same_content = "We decided to use PostgreSQL because ACID transactions matter."
        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [_make_compaction_summary_entry(same_content)],
            "session2.jsonl": [_make_compaction_summary_entry(same_content)],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)
        conn = ensure_db(str(tmp_path / "test.db"))

        result = ingest_mod.ingest_project(conn, project_path)

        assert result["files_processed"] == 2
        assert result["entries_stored"] == 1
        assert result["dupes_skipped"] == 1

        conn.close()


class TestIngestProjectEdgeCases:
    """Cover exception paths in ingest_project."""

    def test_ingest_project_resolve_id_fails(self, tmp_path):
        """ingest_project returns zeros when resolve_project_id raises."""
        import momento.ingest as ingest_mod
        from unittest.mock import patch

        conn = ensure_db(str(tmp_path / "test.db"))

        with patch("momento.identity.resolve_project_id", side_effect=RuntimeError("boom")):
            result = ingest_mod.ingest_project(conn, "/some/bad/path")

        assert result["files_processed"] == 0
        assert result["entries_stored"] == 0
        conn.close()

    def test_ingest_project_file_processing_exception(self, tmp_path, monkeypatch):
        """ingest_project catches per-file exceptions."""
        import momento.ingest as ingest_mod
        from unittest.mock import patch

        project_path = str(tmp_path / "fake_project")
        os.makedirs(project_path, exist_ok=True)

        projects_root = _setup_claude_project_dir(tmp_path, project_path, {
            "session1.jsonl": [
                _make_compaction_summary_entry(
                    "We decided to use TypeScript for type safety."
                ),
            ],
        })

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)
        conn = ensure_db(str(tmp_path / "test.db"))

        with patch("momento.ingest._extract_entries_from_session",
                    side_effect=RuntimeError("extraction blew up")):
            result = ingest_mod.ingest_project(conn, project_path)

        assert result["files_skipped"] == 1
        assert result["entries_stored"] == 0
        conn.close()


class TestIngestAllEdgeCases:
    """Cover edge cases in ingest_all."""

    def test_ingest_all_skips_non_directory_items(self, tmp_path, monkeypatch):
        """ingest_all skips regular files in projects dir."""
        import momento.ingest as ingest_mod

        projects_root = tmp_path / "claude_projects"
        projects_root.mkdir()

        # Create a regular file (not a directory)
        (projects_root / "not-a-directory.txt").write_text("I'm a file")

        # Create a valid project dir with jsonl
        proj_path = str(tmp_path / "project_alpha")
        os.makedirs(proj_path, exist_ok=True)
        encoded = ingest_mod._encode_project_path(proj_path)
        proj_dir = projects_root / encoded
        proj_dir.mkdir(parents=True)
        (proj_dir / "sess.jsonl").write_text(
            _make_compaction_summary_entry(
                "Chose microservices because of scaling needs."
            ) + "\n"
        )

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)
        conn = ensure_db(str(tmp_path / "test.db"))

        result = ingest_mod.ingest_all(conn)

        # Should only count the actual project dir, not the file
        assert result["projects_scanned"] == 1
        conn.close()

    def test_ingest_all_catches_project_exception(self, tmp_path, monkeypatch):
        """ingest_all catches per-project exceptions."""
        import momento.ingest as ingest_mod
        from unittest.mock import patch

        projects_root = tmp_path / "claude_projects"
        proj_dir = projects_root / "-tmp-fake-project"
        proj_dir.mkdir(parents=True)
        (proj_dir / "sess.jsonl").write_text(
            _make_compaction_summary_entry(
                "Something that triggers an exception."
            ) + "\n"
        )

        monkeypatch.setattr(ingest_mod, "_CLAUDE_PROJECTS_DIR", projects_root)
        conn = ensure_db(str(tmp_path / "test.db"))

        with patch("momento.ingest.ingest_project",
                    side_effect=RuntimeError("project ingestion failed")):
            result = ingest_mod.ingest_all(conn)

        assert result["projects_scanned"] == 1
        assert result["files_skipped"] == 1
        conn.close()

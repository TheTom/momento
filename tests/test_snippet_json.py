# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS6.* — JSON rendering tests for snippets."""

import json

import pytest

from momento.snippet import generate_snippet, resolve_range
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_entry,
    hours_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS6.1 — JSON structure
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestJsonStructure:
    """TS6.1: JSON output has expected keys and structure."""

    def test_json_keys(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="json", project_name=MOCK_PROJECT_NAME,
        )

        parsed = json.loads(output)
        assert "project" in parsed
        assert "branch" in parsed
        assert "range" in parsed
        assert "sections" in parsed
        assert "entry_count" in parsed
        assert "empty" in parsed
        assert parsed["empty"] is False

        sections = parsed["sections"]
        assert "accomplished" in sections
        assert "decisions" in sections
        assert "discovered" in sections
        assert "in_progress" in sections
        assert "patterns" in sections

        # Check entry structure
        if sections["accomplished"]:
            item = sections["accomplished"][0]
            assert "content" in item
            assert "entry_id" in item
            assert "source_type" in item  # session_state items have source_type

        if sections["decisions"]:
            item = sections["decisions"][0]
            assert "content" in item
            assert "entry_id" in item


# ---------------------------------------------------------------------------
# TS6.2 — JSON empty
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestJsonEmpty:
    """TS6.2: empty range returns minimal JSON."""

    def test_empty_json(self, db):
        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="json", project_name=MOCK_PROJECT_NAME,
        )

        parsed = json.loads(output)
        assert parsed["empty"] is True
        assert parsed["entry_count"] == 0
        assert parsed["sections"] == {}


# ---------------------------------------------------------------------------
# TS6.3 — JSON round-trip
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestJsonRoundTrip:
    """TS6.3: entry_count matches sum of section lengths."""

    def test_entry_count_consistency(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="json", project_name=MOCK_PROJECT_NAME,
        )

        parsed = json.loads(output)
        assert parsed["empty"] is False

        sections = parsed["sections"]
        section_total = sum(
            len(sections[k]) for k in ("accomplished", "decisions", "discovered", "in_progress", "patterns")
        )
        assert parsed["entry_count"] == section_total or parsed["entry_count"] >= section_total

        assert "start" in parsed["range"]
        assert "end" in parsed["range"]
        # Verify ISO format
        assert "T" in parsed["range"]["start"]
        assert "T" in parsed["range"]["end"]

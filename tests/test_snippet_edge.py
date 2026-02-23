# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS9.* — Edge case tests for snippets."""

import json

import pytest

from momento.snippet import (
    generate_snippet,
    resolve_range,
    group_entries,
    split_session_states,
    extract_surface,
    _dedup_entries,
)
from momento.models import Entry
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_snippet_durable_only,
    make_entry,
    hours_ago,
    minutes_ago,
)
from tests.conftest import insert_entries


def _entry_to_model(d: dict) -> Entry:
    return Entry(
        id=d["id"], content=d["content"], content_hash=d["content_hash"],
        type=d["type"], tags=d["tags"], project_id=d["project_id"],
        project_name=d["project_name"], branch=d["branch"],
        source_type=d["source_type"], confidence=d["confidence"],
        created_at=d["created_at"], updated_at=d["updated_at"],
    )


# ---------------------------------------------------------------------------
# TS9.1 — Only session states
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestOnlySessionStates:
    """TS9.1: only session_state entries render Accomplished + Still In Progress."""

    def test_session_states_only(self, db):
        entries = [
            make_entry(content="Older checkpoint.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=hours_ago(5)),
            make_entry(content="Middle checkpoint.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=hours_ago(3)),
            make_entry(content="Latest checkpoint.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=hours_ago(1)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Accomplished" in output or "### Still In Progress" in output
        assert "### Decisions Made" not in output
        assert "### Discovered" not in output
        assert "### Conventions Established" not in output


# ---------------------------------------------------------------------------
# TS9.2 — Only durable entries
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestOnlyDurableEntries:
    """TS9.2: only durable types render their sections, no Accomplished/In Progress."""

    def test_durable_only(self, db):
        entries = make_snippet_durable_only()
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Decisions Made" in output
        assert "### Discovered" in output
        assert "### Conventions Established" in output
        assert "### Accomplished" not in output
        assert "### Still In Progress" not in output


# ---------------------------------------------------------------------------
# TS9.3 — Single entry
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestSingleEntry:
    """TS9.3: single entry produces one section only."""

    def test_single_decision(self, db):
        entries = [
            make_entry(content="Only decision in range.", type="decision",
                       tags=["server"], branch="main", created_at=hours_ago(1)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "### Decisions Made" in output
        assert "Only decision in range." in output
        assert "### Accomplished" not in output
        assert "### Still In Progress" not in output


# ---------------------------------------------------------------------------
# TS9.4 — Determinism across formats
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestDeterminismAcrossFormats:
    """TS9.4: all formats produce identical output on repeat."""

    def test_all_formats_deterministic(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        for fmt in ("markdown", "standup", "slack", "json"):
            out1 = generate_snippet(
                db, MOCK_PROJECT_ID, start, end,
                format=fmt, project_name=MOCK_PROJECT_NAME,
            )
            out2 = generate_snippet(
                db, MOCK_PROJECT_ID, start, end,
                format=fmt, project_name=MOCK_PROJECT_NAME,
            )
            assert out1 == out2, f"{fmt} format is not deterministic"


# ---------------------------------------------------------------------------
# TS9.5 — Entries at range boundaries
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestRangeBoundaries:
    """TS9.5: range_start is inclusive (>=), range_end is exclusive (<)."""

    def test_boundary_inclusion(self, db):
        entries = [
            make_entry(content="At range start", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-18T00:00:00Z"),
            make_entry(content="At range end", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-20T00:00:00Z"),
            make_entry(content="Inside range", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-19T12:00:00Z"),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(range_start="2026-02-18", range_end="2026-02-20")
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "At range start" in output  # >= start
        assert "At range end" not in output  # < end (exclusive)
        assert "Inside range" in output


# ---------------------------------------------------------------------------
# TS9.6 — Surface extraction from tags
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestSurfaceExtraction:
    """TS9.6: surface is extracted from tags for split key."""

    def test_surface_from_tags(self):
        assert extract_surface(["auth", "server", "billing"]) == "server"
        assert extract_surface(["ios", "keychain"]) == "ios"
        assert extract_surface(["web", "react"]) == "web"
        assert extract_surface(["android", "compose"]) == "android"
        assert extract_surface(["backend", "api"]) == "server"  # mapped
        assert extract_surface(["frontend", "react"]) == "web"  # mapped

    def test_surface_split_uses_tags(self):
        entries = [
            _entry_to_model(make_entry(
                content="Server work old.", type="session_state",
                tags=["server", "billing"], branch="main", surface="server",
                created_at=hours_ago(5),
            )),
            _entry_to_model(make_entry(
                content="Server work new.", type="session_state",
                tags=["server", "billing"], branch="main", surface="server",
                created_at=hours_ago(1),
            )),
        ]

        accomplished, in_progress = split_session_states(entries)
        assert len(in_progress) == 1
        assert in_progress[0].content == "Server work new."


# ---------------------------------------------------------------------------
# TS9.7 — No surface in tags
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestNoSurfaceInTags:
    """TS9.7: entries without surface keywords still split correctly."""

    def test_no_surface_split(self):
        entries = [
            _entry_to_model(make_entry(
                content="Old entry no surface.", type="session_state",
                tags=["auth", "billing"], branch="main",
                created_at=hours_ago(5),
            )),
            _entry_to_model(make_entry(
                content="New entry no surface.", type="session_state",
                tags=["auth", "billing"], branch="main",
                created_at=hours_ago(1),
            )),
        ]

        accomplished, in_progress = split_session_states(entries)
        assert len(accomplished) == 1
        assert len(in_progress) == 1
        assert in_progress[0].content == "New entry no surface."

    def test_surface_is_none(self):
        assert extract_surface(["auth", "billing"]) is None


# ---------------------------------------------------------------------------
# TS9.8 — Staleness warning
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestStalenessWarning:
    """TS9.8: staleness warning prepended when last checkpoint is old."""

    def test_fresh_checkpoint_no_warning(self, db):
        """Checkpoint <10 min old produces no staleness warning."""
        entries = [
            make_entry(
                content="Recent checkpoint.", type="session_state",
                tags=["server"], branch="main", surface="server",
                created_at=minutes_ago(5),
            ),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "Note: Last checkpoint was" not in output

    def test_stale_checkpoint_shows_warning(self, db):
        """Checkpoint >=10 min old prepends staleness note."""
        entries = [
            make_entry(
                content="Old checkpoint.", type="session_state",
                tags=["server"], branch="main", surface="server",
                created_at=minutes_ago(15),
            ),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert output.startswith("Note: Last checkpoint was")
        assert "15m ago" in output
        assert "momento save" in output

    def test_no_session_states_no_warning(self, db):
        """No session_state entries at all -> no staleness warning."""
        entries = [
            make_entry(
                content="A decision.", type="decision",
                tags=["server"], branch="main",
                created_at=hours_ago(1),
            ),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "Note: Last checkpoint was" not in output

    def test_stale_warning_on_empty_snippet(self, db):
        """Staleness warning appears even when snippet has no entries in range."""
        # Session state from 20 min ago (stale), but outside today's range
        entries = [
            make_entry(
                content="Stale checkpoint from yesterday.", type="session_state",
                tags=["server"], branch="main", surface="server",
                created_at=minutes_ago(20),
            ),
        ]
        insert_entries(db, entries)

        # Query a range that excludes the entry
        output = generate_snippet(
            db, MOCK_PROJECT_ID,
            "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z",
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "Note: Last checkpoint was" in output
        assert "No entries found" in output

    def test_stale_warning_json_structured(self, db):
        """JSON format includes staleness as a structured field, not text prefix."""
        entries = [
            make_entry(
                content="Old checkpoint.", type="session_state",
                tags=["server"], branch="main", surface="server",
                created_at=minutes_ago(15),
            ),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="json", project_name=MOCK_PROJECT_NAME,
        )

        parsed = json.loads(output)
        assert "staleness_warning" in parsed
        assert "15m ago" in parsed["staleness_warning"]


# ---------------------------------------------------------------------------
# TS9.9 — Gotcha deduplication
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestGotchaDedup:
    """TS9.9: duplicate gotchas are collapsed with a count."""

    def test_dedup_collapses_identical_first_line(self):
        """Entries with same first line are collapsed regardless of full content."""
        entries = [
            _entry_to_model(make_entry(
                content=f"Error: Exit code 1\nTrace {i}", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(i),
            ))
            for i in range(5)
        ]
        result = _dedup_entries(entries)
        assert len(result) == 1
        assert "Exit code 1" in result[0][0].content
        assert result[0][1] == 5

    def test_dedup_preserves_unique(self):
        """Different first lines stay separate with count=1."""
        entries = [
            _entry_to_model(make_entry(
                content=f"Unique error {i}", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(i),
            ))
            for i in range(3)
        ]
        result = _dedup_entries(entries)
        assert len(result) == 3
        assert all(count == 1 for _, count in result)

    def test_dedup_mixed(self):
        """Mix of duplicates and unique entries."""
        entries = [
            _entry_to_model(make_entry(
                content="Error: Exit code 1\nTrace A", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(5),
            )),
            _entry_to_model(make_entry(
                content="Error: Exit code 1\nTrace B", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(4),
            )),
            _entry_to_model(make_entry(
                content="File not found", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(3),
            )),
            _entry_to_model(make_entry(
                content="Error: Exit code 1\nTrace C", type="gotcha",
                tags=["server"], branch="main", created_at=hours_ago(2),
            )),
        ]
        result = _dedup_entries(entries)
        assert len(result) == 2
        assert "Exit code 1" in result[0][0].content
        assert result[0][1] == 3
        assert result[1][0].content == "File not found"
        assert result[1][1] == 1

    def test_dedup_renders_count_in_slack(self, db):
        """Slack format shows ×N for duplicated gotchas."""
        entries = [
            make_entry(content=f"Error: Exit code 1\nContext {i}", type="gotcha",
                       tags=["server"], branch="main", created_at=hours_ago(i))
            for i in range(1, 4)
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="slack", project_name=MOCK_PROJECT_NAME,
        )

        assert "×3" in output
        assert output.count("Exit code 1") == 1  # only once, not 3 times

    def test_dedup_renders_count_in_markdown(self, db):
        """Markdown format shows ×N for duplicated gotchas."""
        entries = [
            make_entry(content=f"Error: Exit code 1\nContext {i}", type="gotcha",
                       tags=["server"], branch="main", created_at=hours_ago(i))
            for i in range(1, 4)
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="markdown", project_name=MOCK_PROJECT_NAME,
        )

        assert "×3" in output
        assert output.count("Exit code 1") == 1

    def test_dedup_json_has_count_field(self, db):
        """JSON format includes count field for duplicated gotchas."""
        entries = [
            make_entry(content=f"Error: Exit code 1\nContext {i}", type="gotcha",
                       tags=["server"], branch="main", created_at=hours_ago(i))
            for i in range(1, 4)
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="json", project_name=MOCK_PROJECT_NAME,
        )

        parsed = json.loads(output)
        discovered = parsed["sections"]["discovered"]
        assert len(discovered) == 1
        assert discovered[0]["count"] == 3

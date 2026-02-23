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
)
from momento.models import Entry
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_snippet_durable_only,
    make_entry,
    hours_ago,
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

# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS4.* — Standup rendering tests for snippets."""

import pytest

from momento.snippet import generate_snippet, resolve_range, SnippetMeta, SnippetSections, render_standup
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_snippet_durable_only,
    make_entry,
    hours_ago,
    days_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS4.1 — Basic standup
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestBasicStandup:
    """TS4.1: standup has Yesterday/Today/Blockers structure."""

    def test_standup_structure(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*Yesterday:*" in output
        assert "*Today:*" in output
        assert "*Blockers:*" in output


# ---------------------------------------------------------------------------
# TS4.2 — Blockers from gotchas
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestBlockersFromGotchas:
    """TS4.2: gotchas appear in blockers section."""

    def test_gotchas_as_blockers(self, db):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*Blockers:*" in output
        assert "None detected" not in output


# ---------------------------------------------------------------------------
# TS4.3 — No blockers
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestNoBlockers:
    """TS4.3: no gotchas means 'None detected'."""

    def test_no_blockers(self, db):
        # Only session_state entries, no gotchas
        entries = [
            make_entry(content="Working on auth.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=hours_ago(2)),
            make_entry(content="Finished billing.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=hours_ago(5)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*Blockers:* None detected." in output


# ---------------------------------------------------------------------------
# TS4.4 — Empty standup
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptyStandup:
    """TS4.4: empty range produces standard empty standup."""

    def test_empty_standup(self, db):
        start, end, _ = resolve_range(today=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*Yesterday:* No entries recorded." in output
        assert "*Today:* \u2014" in output
        assert "*Blockers:* \u2014" in output


# ---------------------------------------------------------------------------
# TS4.5 — Weekly standup uses "This week" / "Next week"
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestWeeklyStandupLabels:
    """TS4.5: weekly standup uses 'This week' / 'Next week'."""

    def test_weekly_labels(self, db):
        entries = [
            make_entry(content="Week work item 1.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=days_ago(1)),
            make_entry(content="Week work item 2.", type="session_state",
                       tags=["server"], branch="main", surface="server",
                       created_at=days_ago(3)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(week=True)
        output = generate_snippet(
            db, MOCK_PROJECT_ID, start, end,
            format="standup", project_name=MOCK_PROJECT_NAME,
        )

        assert "*This week:*" in output
        assert "*Next week:*" in output
        assert "*Yesterday:*" not in output
        assert "*Today:*" not in output

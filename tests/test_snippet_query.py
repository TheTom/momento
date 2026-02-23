# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS1.* — Time range + SQL query tests for snippets."""

import pytest

from momento.snippet import query_entries, resolve_range, generate_snippet
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    SECOND_PROJECT_ID,
    make_entry,
    hours_ago,
    days_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS1.1 — Today range resolution
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestTodayRange:
    """TS1.1: today range returns only today's entries."""

    def test_today_excludes_yesterday(self, db):
        entries = [
            make_entry(content="2h ago entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(2)),
            make_entry(content="5h ago entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(5)),
            make_entry(content="25h ago entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(25)),
        ]
        insert_entries(db, entries)

        start, end, label = resolve_range(today=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        assert len(results) == 2, f"Expected 2 today entries, got {len(results)}"
        contents = [r.content for r in results]
        assert "25h ago entry" not in contents


# ---------------------------------------------------------------------------
# TS1.2 — Yesterday range resolution
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestYesterdayRange:
    """TS1.2: yesterday range returns only yesterday's entries."""

    def test_yesterday_excludes_today_and_older(self, db):
        entries = [
            make_entry(content="2h ago today", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(2)),
            make_entry(content="25h ago yesterday", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(25)),
            make_entry(content="50h ago two days", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(50)),
        ]
        insert_entries(db, entries)

        start, end, label = resolve_range(yesterday=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        assert len(results) == 1, f"Expected 1 yesterday entry, got {len(results)}"
        assert results[0].content == "25h ago yesterday"


# ---------------------------------------------------------------------------
# TS1.3 — Week range resolution
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestWeekRange:
    """TS1.3: week range returns entries within 7 days."""

    def test_week_excludes_old_entries(self, db):
        entries = [
            make_entry(content="1d ago", type="decision", tags=["server"],
                       branch="main", created_at=days_ago(1)),
            make_entry(content="3d ago", type="decision", tags=["server"],
                       branch="main", created_at=days_ago(3)),
            make_entry(content="6d ago", type="decision", tags=["server"],
                       branch="main", created_at=days_ago(6)),
            make_entry(content="10d ago", type="decision", tags=["server"],
                       branch="main", created_at=days_ago(10)),
        ]
        insert_entries(db, entries)

        start, end, label = resolve_range(week=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        assert len(results) == 3, f"Expected 3 week entries, got {len(results)}"
        contents = [r.content for r in results]
        assert "10d ago" not in contents


# ---------------------------------------------------------------------------
# TS1.4 — Custom range
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestCustomRange:
    """TS1.4: custom range with exclusive end date."""

    def test_custom_range_exclusive_end(self, db):
        entries = [
            make_entry(content="Feb 18 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-18T10:00:00Z"),
            make_entry(content="Feb 19 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-19T14:00:00Z"),
            make_entry(content="Feb 20 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-20T08:00:00Z"),
            make_entry(content="Feb 22 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-22T12:00:00Z"),
        ]
        insert_entries(db, entries)

        start, end, label = resolve_range(range_start="2026-02-18", range_end="2026-02-20")
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        assert len(results) == 2, f"Expected 2 entries, got {len(results)}"
        contents = [r.content for r in results]
        assert "Feb 18 entry" in contents
        assert "Feb 19 entry" in contents
        assert "Feb 20 entry" not in contents


# ---------------------------------------------------------------------------
# TS1.5 — Branch filter
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestBranchFilter:
    """TS1.5: branch filter returns only matching branch entries."""

    def test_branch_filter(self, db):
        entries = [
            make_entry(content="billing entry 1", type="decision", tags=["billing"],
                       branch="feature/billing", created_at=hours_ago(1)),
            make_entry(content="billing entry 2", type="decision", tags=["billing"],
                       branch="feature/billing", created_at=hours_ago(2)),
            make_entry(content="billing entry 3", type="gotcha", tags=["billing"],
                       branch="feature/billing", created_at=hours_ago(3)),
            make_entry(content="main entry 1", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="main entry 2", type="gotcha", tags=["server"],
                       branch="main", created_at=hours_ago(2)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end, branch="feature/billing")
        assert len(results) == 3


# ---------------------------------------------------------------------------
# TS1.6 — Cross-project mode
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestCrossProject:
    """TS1.6: cross-project mode returns entries from all projects."""

    def test_all_projects(self, db):
        entries = [
            make_entry(content="project A entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="project B entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(2),
                       project_id=SECOND_PROJECT_ID, project_name="identity-service"),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        # project_id=None means no project filter
        results = query_entries(db, None, start, end)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# TS1.7 — Project scoping (default)
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestProjectScoping:
    """TS1.7: default scoping returns only current project entries."""

    def test_project_scoped(self, db):
        entries = [
            make_entry(content="project A entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="project B entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(2),
                       project_id=SECOND_PROJECT_ID, project_name="identity-service"),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        assert len(results) == 1
        assert results[0].content == "project A entry"


# ---------------------------------------------------------------------------
# TS1.8 — Query ordering
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestQueryOrdering:
    """TS1.8: results ordered by type ASC, created_at ASC."""

    def test_ordering(self, db):
        entries = [
            make_entry(content="gotcha late", type="gotcha", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="decision early", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(3)),
            make_entry(content="decision late", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="gotcha early", type="gotcha", tags=["server"],
                       branch="main", created_at=hours_ago(3)),
        ]
        insert_entries(db, entries)

        start, end, _ = resolve_range(today=True)
        results = query_entries(db, MOCK_PROJECT_ID, start, end)
        types = [r.type for r in results]
        # Should be sorted: decision, decision, gotcha, gotcha
        assert types == ["decision", "decision", "gotcha", "gotcha"]
        # Within same type, older first (created_at ASC)
        assert results[0].content == "decision early"
        assert results[1].content == "decision late"

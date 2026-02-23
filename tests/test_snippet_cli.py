# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS7.* — CLI command tests for snippets."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from momento.cli import cmd_snippet
from momento.snippet import resolve_range
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_entry,
    hours_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS7.1 — Default invocation
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestDefaultInvocation:
    """TS7.1: `momento snippet` with no flags prints markdown."""

    def test_default_markdown(self, db, capsys):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        args = SimpleNamespace(
            yesterday=False, week=False, date_range=None,
            fmt="markdown", branch=None, all_projects=False,
        )
        cmd_snippet(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out

        assert "snippet —" in out
        assert "### " in out  # Has section headers


# ---------------------------------------------------------------------------
# TS7.2 — Format flag
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestFormatFlag:
    """TS7.2: --format standup outputs standup format."""

    def test_standup_format(self, db, capsys):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)

        args = SimpleNamespace(
            yesterday=False, week=False, date_range=None,
            fmt="standup", branch=None, all_projects=False,
        )
        cmd_snippet(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out

        assert "*Yesterday:*" in out
        assert "*Today:*" in out
        assert "*Blockers:*" in out


# ---------------------------------------------------------------------------
# TS7.3 — No project detected
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestNoProjectDetected:
    """TS7.3: no project prints error and exits 1."""

    def test_no_project(self, db, capsys):
        args = SimpleNamespace(
            yesterday=False, week=False, date_range=None,
            fmt="markdown", branch=None, all_projects=False,
        )
        with pytest.raises(SystemExit) as exc_info:
            cmd_snippet(args, db, None, None, None)

        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "project" in err.lower() or "no project" in err.lower()


# ---------------------------------------------------------------------------
# TS7.4 — Empty range message
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestEmptyRangeMessage:
    """TS7.4: no entries for today prints empty message, exit 0."""

    def test_empty_range(self, db, capsys):
        args = SimpleNamespace(
            yesterday=False, week=False, date_range=None,
            fmt="markdown", branch=None, all_projects=False,
        )
        cmd_snippet(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out

        assert "No entries found" in out


# ---------------------------------------------------------------------------
# TS7.5 — Range flag parsing
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestRangeFlagParsing:
    """TS7.5: --range flag correctly filters entries."""

    def test_range_flag(self, db, capsys):
        entries = [
            make_entry(content="Feb 18 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-18T10:00:00Z"),
            make_entry(content="Feb 19 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-19T14:00:00Z"),
        ]
        insert_entries(db, entries)

        args = SimpleNamespace(
            yesterday=False, week=False,
            date_range=["2026-02-18", "2026-02-20"],
            fmt="markdown", branch=None, all_projects=False,
        )
        cmd_snippet(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out

        assert "Feb 18 entry" in out
        assert "Feb 19 entry" in out


# ---------------------------------------------------------------------------
# TS7.6 — Branch flag
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestBranchFlag:
    """TS7.6: --branch filters to specific branch."""

    def test_branch_flag(self, db, capsys):
        entries = [
            make_entry(content="main branch entry", type="decision", tags=["server"],
                       branch="main", created_at=hours_ago(1)),
            make_entry(content="feature branch entry", type="decision", tags=["billing"],
                       branch="feature/billing", created_at=hours_ago(2)),
        ]
        insert_entries(db, entries)

        args = SimpleNamespace(
            yesterday=False, week=False, date_range=None,
            fmt="markdown", branch="main", all_projects=False,
        )
        cmd_snippet(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out

        assert "main branch entry" in out
        assert "feature branch entry" not in out

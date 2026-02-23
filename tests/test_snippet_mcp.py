# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""TS8.* — MCP tool tests for snippets."""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from momento.mcp_server import server
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_snippet_day,
    make_entry,
    hours_ago,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# TS8.1 — generate_snippet registered
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestGenerateSnippetRegistered:
    """TS8.1: generate_snippet appears in MCP tool list."""

    def test_tool_registered(self):
        tools = server._tool_manager._tools
        assert "generate_snippet" in tools


# ---------------------------------------------------------------------------
# TS8.2 — Default call
# ---------------------------------------------------------------------------

@pytest.mark.must_pass
class TestDefaultMcpCall:
    """TS8.2: generate_snippet(range='today') returns markdown."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.surface.detect_surface", return_value="server")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME))
    @patch("os.getcwd", return_value="/fake/project")
    def test_default_returns_markdown(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_db, db
    ):
        # Insert entries into the real test DB
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)
        mock_db.return_value = db

        from momento.mcp_server import generate_snippet as mcp_generate_snippet
        result = mcp_generate_snippet(range="today")

        assert "snippet —" in result or "No entries" in result


# ---------------------------------------------------------------------------
# TS8.3 — Custom range via MCP
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestCustomRangeMcp:
    """TS8.3: custom range via MCP parameters."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME))
    @patch("os.getcwd", return_value="/fake/project")
    def test_custom_range(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_db, db
    ):
        entries = [
            make_entry(content="Feb 18 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-18T10:00:00Z"),
            make_entry(content="Feb 19 entry", type="decision", tags=["server"],
                       branch="main", created_at="2026-02-19T14:00:00Z"),
        ]
        insert_entries(db, entries)
        mock_db.return_value = db

        from momento.mcp_server import generate_snippet as mcp_generate_snippet
        result = mcp_generate_snippet(
            range="custom", start_date="2026-02-18", end_date="2026-02-20",
        )

        assert "Feb 18 entry" in result
        assert "Feb 19 entry" in result


# ---------------------------------------------------------------------------
# TS8.4 — Format parameter
# ---------------------------------------------------------------------------

@pytest.mark.should_pass
class TestFormatParameterMcp:
    """TS8.4: format parameter controls output format."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.surface.detect_surface", return_value="server")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME))
    @patch("os.getcwd", return_value="/fake/project")
    def test_standup_format(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_db, db
    ):
        entries = [e for e in make_snippet_day() if e["project_id"] == MOCK_PROJECT_ID]
        insert_entries(db, entries)
        mock_db.return_value = db

        from momento.mcp_server import generate_snippet as mcp_generate_snippet
        result = mcp_generate_snippet(range="today", format="standup")

        assert "*Yesterday:*" in result or "*This week:*" in result


# ---------------------------------------------------------------------------
# TS8.5 — Empty via MCP
# ---------------------------------------------------------------------------

@pytest.mark.nice_to_have
class TestEmptyViaMcp:
    """TS8.5: empty range returns empty message, not error."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME))
    @patch("os.getcwd", return_value="/fake/project")
    def test_empty_not_error(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_db, db
    ):
        mock_db.return_value = db  # Empty DB

        from momento.mcp_server import generate_snippet as mcp_generate_snippet
        result = mcp_generate_snippet(range="today")

        assert "No entries" in result or "no entries" in result

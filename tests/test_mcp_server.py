# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for momento.mcp_server — MCP tool registration and integration.

Covers:
- Tool registration (retrieve_context, log_knowledge)
- retrieve_context returns rendered markdown
- log_knowledge stores entries and returns id
- Size limit rejection flows through from store.py
- Duplicate detection flows through from store.py
- Auto-resolution of project/branch/surface from cwd
- Empty query treated as None (restore mode)
- DB connection opened/closed per call
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from momento.mcp_server import server, retrieve_context, log_knowledge, _resolve_env, _db_path
from momento.models import RestoreResult, SIZE_LIMITS


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    """Verify both tools are registered with correct names."""

    def test_server_name(self):
        assert server.name == "momento"

    def test_retrieve_context_registered(self):
        tools = server._tool_manager._tools
        assert "retrieve_context" in tools

    def test_log_knowledge_registered(self):
        tools = server._tool_manager._tools
        assert "log_knowledge" in tools

    def test_exactly_three_tools(self):
        tools = server._tool_manager._tools
        assert len(tools) == 3


# ---------------------------------------------------------------------------
# Auto-resolution helpers
# ---------------------------------------------------------------------------


class TestAutoResolution:
    """Test _resolve_env and _db_path helpers."""

    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-123", "my-project"))
    @patch("momento.mcp_server.identity.resolve_branch", return_value="feature/test")
    @patch("momento.mcp_server.surface.detect_surface", return_value="server")
    def test_resolve_env(self, mock_surface, mock_branch, mock_identity):
        env = _resolve_env("/some/path")
        assert env["project_id"] == "proj-123"
        assert env["project_name"] == "my-project"
        assert env["branch"] == "feature/test"
        assert env["surface"] == "server"
        mock_identity.assert_called_once_with("/some/path")
        mock_branch.assert_called_once_with("/some/path")
        mock_surface.assert_called_once_with("/some/path")

    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-456", "other"))
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    def test_resolve_env_nulls(self, mock_surface, mock_branch, mock_identity):
        env = _resolve_env("/tmp")
        assert env["branch"] is None
        assert env["surface"] is None

    def test_db_path_default(self):
        with patch.dict(os.environ, {}, clear=True):
            # Remove MOMENTO_DB if present
            os.environ.pop("MOMENTO_DB", None)
            path = _db_path()
            assert path == os.path.expanduser("~/.momento/knowledge.db")

    def test_db_path_from_env(self):
        with patch.dict(os.environ, {"MOMENTO_DB": "/custom/path/test.db"}):
            path = _db_path()
            assert path == "/custom/path/test.db"


# ---------------------------------------------------------------------------
# retrieve_context tool
# ---------------------------------------------------------------------------


class TestRetrieveContext:
    """Test the retrieve_context MCP tool."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.retrieve.retrieve_context")
    @patch("momento.mcp_server.surface.detect_surface", return_value="server")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_returns_rendered_markdown(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_retrieve, mock_db
    ):
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_retrieve.return_value = RestoreResult(
            entries=[], total_tokens=50, rendered="## Momento — Project Context\n\nSome content.\n"
        )

        result = retrieve_context()

        assert "## Momento" in result
        assert "Some content." in result
        mock_retrieve.assert_called_once_with(
            conn=mock_conn,
            project_id="proj-1",
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )
        mock_conn.close.assert_called_once()

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.retrieve.retrieve_context")
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_empty_query_treated_as_none(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_retrieve, mock_db
    ):
        """Empty string query should be passed as None (restore mode)."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_retrieve.return_value = RestoreResult(entries=[], total_tokens=0, rendered="")

        retrieve_context(query="")

        _, kwargs = mock_retrieve.call_args
        assert kwargs["query"] is None

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.retrieve.retrieve_context")
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_nonempty_query_passed_through(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_retrieve, mock_db
    ):
        """Non-empty query should be passed as-is (search mode)."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_retrieve.return_value = RestoreResult(entries=[], total_tokens=0, rendered="## Search Results\n")

        retrieve_context(query="stripe webhook")

        _, kwargs = mock_retrieve.call_args
        assert kwargs["query"] == "stripe webhook"

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.retrieve.retrieve_context")
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_include_session_state_false(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_retrieve, mock_db
    ):
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_retrieve.return_value = RestoreResult(entries=[], total_tokens=0, rendered="")

        retrieve_context(include_session_state=False)

        _, kwargs = mock_retrieve.call_args
        assert kwargs["include_session_state"] is False

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.retrieve.retrieve_context", side_effect=Exception("DB error"))
    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_db_connection_closed_on_error(
        self, mock_cwd, mock_pid, mock_branch, mock_surface, mock_retrieve, mock_db
    ):
        """DB connection must be closed even if retrieve raises."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        with pytest.raises(Exception, match="DB error"):
            retrieve_context()

        mock_conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# log_knowledge tool
# ---------------------------------------------------------------------------


class TestLogKnowledge:
    """Test the log_knowledge MCP tool."""

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_returns_terse_ack(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_store.return_value = {"id": "abc-123", "status": "created"}

        result = log_knowledge(
            content="Always check webhook signatures.",
            type="gotcha",
            tags=["stripe", "server"],
        )

        assert result == "✓ gotcha"
        mock_conn.close.assert_called_once()

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_passes_correct_args_to_store(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_store.return_value = {"id": "xyz", "status": "created"}

        log_knowledge(
            content="Some decision content.",
            type="decision",
            tags=["auth", "migration"],
        )

        mock_store.assert_called_once_with(
            conn=mock_conn,
            content="Some decision content.",
            type="decision",
            tags=["auth", "migration"],
            project_id="proj-1",
            project_name="test-proj",
            branch="main",
            source_type="manual",
            confidence=0.9,
            enforce_limits=True,
        )

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_size_limit_rejection(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        """Size limit rejection from store.py should flow through as JSON error."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_store.return_value = {
            "error": "Content too long: 600 chars exceeds 400 char limit for gotcha.",
            "hint": "One pitfall, one fix. Be specific.",
        }

        result = log_knowledge(
            content="x" * 600,
            type="gotcha",
            tags=["test"],
        )

        assert "too long" in result.lower()
        assert "Hint:" in result
        mock_conn.close.assert_called_once()

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_duplicate_detection(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        """Duplicate detection from store.py should flow through."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_store.return_value = {"id": "existing-id", "status": "duplicate_skipped"}

        result = log_knowledge(
            content="Already stored content.",
            type="decision",
            tags=["test"],
        )

        assert result == "skip (dup)"

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge", side_effect=Exception("write failed"))
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_db_connection_closed_on_error(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        """DB connection must be closed even if store raises."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn

        with pytest.raises(Exception, match="write failed"):
            log_knowledge(content="fail", type="gotcha", tags=["test"])

        mock_conn.close.assert_called_once()

    @patch("momento.mcp_server.db.ensure_db")
    @patch("momento.mcp_server.store.log_knowledge")
    @patch("momento.mcp_server.identity.resolve_branch", return_value=None)
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("proj-1", "test-proj"))
    @patch("os.getcwd", return_value="/tmp/no-git")
    def test_null_branch_passed(
        self, mock_cwd, mock_pid, mock_branch, mock_store, mock_db
    ):
        """When branch is None (not a git repo), it should still work."""
        mock_conn = MagicMock()
        mock_db.return_value = mock_conn
        mock_store.return_value = {"id": "no-branch", "status": "created"}

        result = log_knowledge(content="test", type="pattern", tags=["test"])

        _, kwargs = mock_store.call_args
        assert kwargs["branch"] is None
        assert result == "✓ pattern"


# ---------------------------------------------------------------------------
# Integration tests (use real DB, mock identity/surface)
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end tests using a real SQLite DB but mocked identity resolution."""

    @patch("momento.mcp_server.surface.detect_surface", return_value="server")
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("int-proj", "integration"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_store_then_retrieve(self, mock_cwd, mock_pid, mock_branch, mock_surface, db_path):
        """Store an entry, then retrieve it — full round trip."""
        with patch.dict(os.environ, {"MOMENTO_DB": db_path}):
            # Store
            store_result = log_knowledge(
                content="Integration: always verify webhook signatures.",
                type="gotcha",
                tags=["server", "webhook"],
            )
            assert store_result == "✓ gotcha"

            # Retrieve
            rendered = retrieve_context()
            assert "webhook" in rendered.lower()

    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("int-proj", "integration"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_store_duplicate_returns_skipped(self, mock_cwd, mock_pid, mock_branch, mock_surface, db_path):
        """Storing the same content twice should return terse skip."""
        with patch.dict(os.environ, {"MOMENTO_DB": db_path}):
            content = "Dedup test: use PKCE for all OAuth clients."

            first = log_knowledge(content=content, type="decision", tags=["auth"])
            assert first == "✓ decision"

            second = log_knowledge(content=content, type="decision", tags=["auth"])
            assert second == "skip (dup)"

    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("int-proj", "integration"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_size_limit_enforced(self, mock_cwd, mock_pid, mock_branch, mock_surface, db_path):
        """Content exceeding size limit should be rejected with error+hint."""
        with patch.dict(os.environ, {"MOMENTO_DB": db_path}):
            oversized = "x" * (SIZE_LIMITS["gotcha"] + 1)
            result = log_knowledge(content=oversized, type="gotcha", tags=["test"])
            assert "too long" in result.lower()
            assert "Hint:" in result

    @patch("momento.mcp_server.surface.detect_surface", return_value=None)
    @patch("momento.mcp_server.identity.resolve_branch", return_value="main")
    @patch("momento.mcp_server.identity.resolve_project_id", return_value=("int-proj", "integration"))
    @patch("os.getcwd", return_value="/fake/project")
    def test_empty_restore_shows_tip(self, mock_cwd, mock_pid, mock_branch, mock_surface, db_path):
        """Retrieving from empty DB should return a helpful tip."""
        with patch.dict(os.environ, {"MOMENTO_DB": db_path}):
            rendered = retrieve_context()
            assert "log_knowledge" in rendered
            assert "Tip" in rendered
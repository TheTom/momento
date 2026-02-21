# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Entry size limit tests — T9.1 through T9.3.

Tests for MCP size enforcement, CLI bypass, and rejection message quality.
"""

import pytest

from momento.store import log_knowledge
from momento.models import SIZE_LIMITS, SIZE_HINTS
from tests.mock_data import MOCK_PROJECT_ID, MOCK_PROJECT_NAME


# ===========================================================================
# T9.1 — MCP rejects oversized entry
# ===========================================================================

class TestMCPRejectsOversized:
    """T9.1 — session_state at 501 chars is rejected with error details."""

    def test_session_state_501_chars_rejected(self, db):
        """T9.1: session_state at 501 chars, error with count/limit/hint."""
        content = "x" * 501  # 1 char over the 500 limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "error" in result, "Oversized session_state should be rejected"
        error_msg = result["error"]

        # Error should include the char count
        assert "501" in error_msg, f"Error should include char count (501): {error_msg}"

        # Error should include the limit
        assert "500" in error_msg, f"Error should include limit (500): {error_msg}"

    def test_session_state_at_limit_accepted(self, db):
        """T9.1: session_state at exactly 500 chars should be accepted."""
        content = "x" * 500  # Exactly at the limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "error" not in result, f"Content at exactly the limit should be accepted: {result}"

    def test_decision_oversized_rejected(self, db):
        """T9.1: decision at 801 chars is rejected."""
        content = "d" * 801  # 1 char over the 800 limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="decision",
            tags=["architecture"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "error" in result, "Oversized decision should be rejected"
        assert "801" in result["error"], "Error should include char count"
        assert "800" in result["error"], "Error should include limit"

    def test_gotcha_oversized_rejected(self, db):
        """T9.1: gotcha at 401 chars is rejected."""
        content = "g" * 401  # 1 char over the 400 limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="gotcha",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "error" in result, "Oversized gotcha should be rejected"
        assert "401" in result["error"]
        assert "400" in result["error"]

    def test_nothing_inserted_on_rejection(self, db):
        """T9.1: rejected entries should NOT be inserted into DB."""
        content = "x" * 501

        log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        cursor = db.execute("SELECT COUNT(*) FROM knowledge")
        count = cursor.fetchone()[0]
        assert count == 0, "Rejected entry should not be inserted into DB"


# ===========================================================================
# T9.2 — CLI bypass
# ===========================================================================

@pytest.mark.nice_to_have
class TestCLIBypass:
    """T9.2 — CLI does not enforce size limits (enforce_limits=False)."""

    def test_cli_accepts_oversized_session_state(self, db):
        """T9.2: 800 char session_state accepted via CLI (no limits)."""
        content = "x" * 800  # Way over the 500 MCP limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=False,  # CLI mode — no limits
        )

        assert "error" not in result, (
            f"CLI should accept oversized entries (enforce_limits=False): {result}"
        )

        # Verify it was actually stored
        cursor = db.execute("SELECT COUNT(*) FROM knowledge")
        count = cursor.fetchone()[0]
        assert count == 1, "Oversized entry should be stored when limits not enforced"

    def test_cli_accepts_oversized_gotcha(self, db):
        """T9.2: 600 char gotcha accepted via CLI."""
        content = "g" * 600  # Way over the 400 MCP limit

        result = log_knowledge(
            conn=db,
            content=content,
            type="gotcha",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=False,
        )

        assert "error" not in result, "CLI should accept oversized gotcha entries"


# ===========================================================================
# T9.3 — Rejection message includes hint
# ===========================================================================

class TestRejectionHint:
    """T9.3 — oversized rejection includes per-type hint text."""

    def test_session_state_hint(self, db):
        """T9.3: oversized session_state gets session_state-specific hint."""
        content = "x" * 501

        result = log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "hint" in result, "Rejection should include a 'hint' field"
        expected_hint = SIZE_HINTS["session_state"]
        assert result["hint"] == expected_hint, (
            f"Expected hint '{expected_hint}', got '{result.get('hint')}'"
        )

    def test_decision_hint(self, db):
        """T9.3: oversized decision gets decision-specific hint."""
        content = "d" * 801

        result = log_knowledge(
            conn=db,
            content=content,
            type="decision",
            tags=["architecture"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "hint" in result, "Rejection should include a 'hint' field"
        expected_hint = SIZE_HINTS["decision"]
        assert result["hint"] == expected_hint, (
            f"Expected hint '{expected_hint}', got '{result.get('hint')}'"
        )

    def test_plan_hint(self, db):
        """T9.3: oversized plan gets plan-specific hint."""
        content = "p" * 801

        result = log_knowledge(
            conn=db,
            content=content,
            type="plan",
            tags=["migration"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "hint" in result
        assert result["hint"] == SIZE_HINTS["plan"]

    def test_gotcha_hint(self, db):
        """T9.3: oversized gotcha gets gotcha-specific hint."""
        content = "g" * 401

        result = log_knowledge(
            conn=db,
            content=content,
            type="gotcha",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "hint" in result
        assert result["hint"] == SIZE_HINTS["gotcha"]

    def test_pattern_hint(self, db):
        """T9.3: oversized pattern gets pattern-specific hint."""
        content = "p" * 401

        result = log_knowledge(
            conn=db,
            content=content,
            type="pattern",
            tags=["api"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            enforce_limits=True,
        )

        assert "hint" in result
        assert result["hint"] == SIZE_HINTS["pattern"]

    def test_all_types_have_hints(self):
        """T9.3: every entry type in SIZE_LIMITS has a corresponding SIZE_HINTS entry."""
        for entry_type in SIZE_LIMITS:
            assert entry_type in SIZE_HINTS, (
                f"Missing hint for type '{entry_type}' in SIZE_HINTS"
            )
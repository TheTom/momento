"""Tests for dedup edge cases (T11.1-T11.2).

Dedup is by content_hash (SHA256). Per-project, not global.
COALESCE index handles NULL project_id for cross-project entries.
These are RED tests — they will fail against stub implementations.
"""

import pytest

from momento.store import log_knowledge
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    SECOND_PROJECT_ID,
    SECOND_PROJECT_NAME,
)


# ---------------------------------------------------------------------------
# T11.1 — Cross-project dedup (NULL project_id)
# ---------------------------------------------------------------------------


def test_cross_project_null_dedup(db):
    """T11.1: two cross-project entries (project_id=NULL) with identical
    content. Second log_knowledge() is silently skipped.

    The COALESCE unique index converts NULL to '__global__' for dedup,
    so SQLite's NULL != NULL behavior doesn't bypass the check.
    """
    content = "Universal: never log PII in error messages."

    result1 = log_knowledge(
        conn=db,
        content=content,
        type="pattern",
        tags=["security", "logging"],
        project_id=None,
        project_name=None,
        branch=None,
        enforce_limits=False,
    )
    assert "error" not in result1, f"First cross-project insert should succeed: {result1}"

    result2 = log_knowledge(
        conn=db,
        content=content,
        type="pattern",
        tags=["security", "logging"],
        project_id=None,
        project_name=None,
        branch=None,
        enforce_limits=False,
    )
    # Second call must be silently skipped — no error
    assert "error" not in result2, (
        "Duplicate cross-project entry should be silently skipped, not error"
    )

    # Only one row in DB
    count = db.execute(
        "SELECT COUNT(*) FROM knowledge WHERE project_id IS NULL"
    ).fetchone()[0]
    assert count == 1, (
        f"COALESCE dedup must catch NULL project_id duplicates. Got {count} rows"
    )


# ---------------------------------------------------------------------------
# T11.2 — Same content, different projects
# ---------------------------------------------------------------------------


def test_same_content_different_projects(db):
    """T11.2: identical content logged to Project A and Project B.
    Both succeed — dedup is per-project, not global.
    """
    content = "Always verify payment_intent status server-side before updating order state."

    result_a = log_knowledge(
        conn=db,
        content=content,
        type="gotcha",
        tags=["server", "stripe"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result_a, f"Project A insert should succeed: {result_a}"
    assert "id" in result_a

    result_b = log_knowledge(
        conn=db,
        content=content,
        type="gotcha",
        tags=["server", "stripe"],
        project_id=SECOND_PROJECT_ID,
        project_name=SECOND_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result_b, f"Project B insert should succeed: {result_b}"
    assert "id" in result_b

    # Both rows must exist
    count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert count == 2, (
        f"Same content in different projects must both persist. Got {count} rows"
    )

    # Different IDs
    assert result_a["id"] != result_b["id"], (
        "Entries in different projects must have different IDs"
    )

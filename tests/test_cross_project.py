"""Tests for cross-project tag matching (T12.1-T12.2).

Cross-project entries appear in Tier 5 of restore mode only when
their tags intersect with the current project's context tags.
These are RED tests — they will fail against stub implementations.
"""

import pytest

from momento.retrieve import retrieve_context
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    SECOND_PROJECT_ID,
    SECOND_PROJECT_NAME,
    make_entry,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# T12.1 — Tag intersection surfaces cross-project entry
# ---------------------------------------------------------------------------


def test_tag_intersection_surfaces_cross_project(db):
    """T12.1: Project A entry tagged ['auth', 'server'].
    Project B entry tagged ['auth'].
    retrieve_context() in Project B -> Project A entry appears in
    Tier 5 (cross-project) because tags intersect on 'auth'.
    """
    entries = [
        # Project A entry with 'auth' tag
        make_entry(
            content="Auth: always isolate TokenManager in an actor to prevent race conditions.",
            type="gotcha",
            tags=["auth", "server"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
        ),
        # Project B entry with overlapping 'auth' tag
        make_entry(
            content="Auth session tokens use 256-bit entropy with CSPRNG.",
            type="pattern",
            tags=["auth", "security"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
        ),
    ]
    insert_entries(db, entries)

    # Retrieve context from Project B's perspective
    result = retrieve_context(
        conn=db,
        query="",
        project_id=SECOND_PROJECT_ID,
        include_session_state=True,
    )

    # Project A's entry should appear (cross-project via 'auth' tag overlap)
    all_contents = [e.content for e in result.entries]
    assert any("TokenManager" in c for c in all_contents), (
        "Project A entry with overlapping 'auth' tag must appear in "
        "Project B's restore via cross-project tier"
    )


# ---------------------------------------------------------------------------
# T12.2 — No tag match, no cross-project
# ---------------------------------------------------------------------------


def test_no_tag_match_no_cross_project(db):
    """T12.2: Project A entry tagged ['billing'].
    Project B entry tagged ['auth'].
    retrieve_context() in Project B -> Project A entry does NOT appear
    because there is no tag overlap.
    """
    entries = [
        # Project A entry with 'billing' tag — no overlap with Project B
        make_entry(
            content="Billing: Stripe Checkout session creation must happen server-side.",
            type="decision",
            tags=["billing", "stripe"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
        ),
        # Project B entry with 'auth' tag — no overlap with Project A
        make_entry(
            content="Auth: PKCE flow required for all OAuth clients.",
            type="decision",
            tags=["auth", "oauth"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
        ),
    ]
    insert_entries(db, entries)

    # Retrieve context from Project B's perspective
    result = retrieve_context(
        conn=db,
        query="",
        project_id=SECOND_PROJECT_ID,
        include_session_state=True,
    )

    # Project A's billing entry must NOT appear (no tag overlap)
    all_contents = [e.content for e in result.entries]
    assert not any("Stripe Checkout" in c for c in all_contents), (
        "Project A entry with no tag overlap must NOT appear in "
        "Project B's restore results"
    )

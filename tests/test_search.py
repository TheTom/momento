"""Tests for retrieve_context — Search Mode (T5.1-T5.5).

Search mode is FTS5 keyword search, scoped to project + cross-project.
No restore ranking, no surface preference, no branch preference.
These are RED tests — they will fail against stub implementations.
"""

import pytest

from momento.store import log_knowledge
from momento.retrieve import retrieve_context
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_entry,
)
from tests.conftest import insert_entries


# ---------------------------------------------------------------------------
# T5.1 — Basic keyword search
# ---------------------------------------------------------------------------


def test_basic_keyword_search(db):
    """T5.1: entries containing 'keychain', 'token', 'auth' are returned
    when searching for 'keychain race condition', ranked by FTS5 relevance,
    scoped to current project + cross-project.
    """
    entries = [
        make_entry(
            content="iOS Keychain race condition: concurrent access to kSecAttrAccount causes crash.",
            type="gotcha",
            tags=["ios", "keychain"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
        ),
        make_entry(
            content="Auth token refresh must use actor isolation to prevent race conditions.",
            type="gotcha",
            tags=["auth", "server"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
        ),
        make_entry(
            content="Billing webhook has retry logic with exponential backoff.",
            type="decision",
            tags=["billing", "webhook"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
        ),
    ]
    insert_entries(db, entries)

    result = retrieve_context(
        conn=db,
        query="keychain race condition",
        project_id=MOCK_PROJECT_ID,
    )

    # Must return matching entries
    assert result is not None
    assert len(result.entries) >= 1, "Should find at least the keychain entry"

    # The keychain entry should rank highest (best FTS match)
    contents = [e.content for e in result.entries]
    assert any("Keychain" in c or "keychain" in c for c in contents), (
        "Keychain entry must appear in search results"
    )

    # Billing webhook should NOT appear (no keyword overlap)
    assert not any("Billing webhook" in c for c in contents), (
        "Unrelated entries should not appear in search results"
    )


# ---------------------------------------------------------------------------
# T5.2 — FTS5 sync after insert
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_fts5_sync_after_insert(db):
    """T5.2: log_knowledge() inserts an entry with 'billing webhook',
    then retrieve_context(query='billing webhook') finds it immediately.
    FTS trigger must have fired.
    """
    log_knowledge(
        conn=db,
        content="Billing webhook handler validates Stripe signature before processing.",
        type="gotcha",
        tags=["billing", "webhook", "stripe"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )

    result = retrieve_context(
        conn=db,
        query="billing webhook",
        project_id=MOCK_PROJECT_ID,
    )

    assert len(result.entries) >= 1, (
        "Entry just inserted must be searchable via FTS immediately"
    )
    assert any("billing webhook" in e.content.lower() for e in result.entries)


# ---------------------------------------------------------------------------
# T5.3 — FTS5 sync after delete
# ---------------------------------------------------------------------------


def test_fts5_sync_after_delete(db):
    """T5.3: entry with 'billing webhook' exists, then deleted via prune.
    Subsequent search for 'billing webhook' must NOT return the deleted entry.
    FTS delete trigger must have fired.
    """
    # Insert an entry
    result = log_knowledge(
        conn=db,
        content="Billing webhook handler validates Stripe signature before processing.",
        type="gotcha",
        tags=["billing", "webhook"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    entry_id = result["id"]

    # Verify it's searchable
    search_before = retrieve_context(
        conn=db,
        query="billing webhook",
        project_id=MOCK_PROJECT_ID,
    )
    assert len(search_before.entries) >= 1, "Entry must be searchable before delete"

    # Delete the entry (simulating prune)
    db.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
    db.commit()

    # Search again — must NOT find it
    search_after = retrieve_context(
        conn=db,
        query="billing webhook",
        project_id=MOCK_PROJECT_ID,
    )
    deleted_ids = [e.id for e in search_after.entries]
    assert entry_id not in deleted_ids, (
        "Deleted entry must not appear in search results (FTS trigger must fire)"
    )


# ---------------------------------------------------------------------------
# T5.4 — Search respects token cap
# ---------------------------------------------------------------------------


def test_search_respects_token_cap(db):
    """T5.4: with many matching entries, search returns max 10 results
    under 2000 tokens.
    """
    # Insert 20 entries all containing "auth"
    entries = []
    for i in range(20):
        entries.append(make_entry(
            content=f"Auth pattern {i}: always validate tokens before processing requests. "
                    f"Unique variant {i} for search dedup avoidance.",
            type="pattern",
            tags=["auth", "server"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
        ))
    insert_entries(db, entries)

    result = retrieve_context(
        conn=db,
        query="auth",
        project_id=MOCK_PROJECT_ID,
    )

    # Max 10 results
    assert len(result.entries) <= 10, (
        f"Search must return max 10 results. Got: {len(result.entries)}"
    )

    # Under 2000 tokens (approximate: len/4)
    assert result.total_tokens <= 2000, (
        f"Search results must be under 2000 tokens. Got: {result.total_tokens}"
    )


# ---------------------------------------------------------------------------
# T5.5 — Search mode has no restore ranking
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_search_mode_no_restore_ranking(db):
    """T5.5: search results are ranked by FTS5 relevance only.
    No surface preference, no branch preference, no tier ordering.
    Search is search, not restore.
    """
    entries = [
        # This entry matches "auth" AND has surface=server
        make_entry(
            content="Auth middleware validates JWT tokens on every server request.",
            type="decision",
            tags=["auth", "server"],
            branch="main",
            surface="server",
            project_id=MOCK_PROJECT_ID,
        ),
        # This entry matches "auth" better (more keyword hits) but has surface=ios
        make_entry(
            content="Auth token refresh: auth rotation uses auth actor isolation for auth safety.",
            type="gotcha",
            tags=["auth", "ios"],
            branch="feature/x",
            surface="ios",
            project_id=MOCK_PROJECT_ID,
        ),
    ]
    insert_entries(db, entries)

    # Search from a "server" context — but search mode should NOT prefer server entries
    result = retrieve_context(
        conn=db,
        query="auth",
        project_id=MOCK_PROJECT_ID,
    )

    assert len(result.entries) >= 2, "Both auth entries should match"

    # Both entries must be present — search mode does not filter by surface
    contents = [e.content for e in result.entries]
    assert any("server request" in c for c in contents), (
        "Server auth entry must appear in search (not filtered by surface)"
    )
    assert any("actor isolation" in c for c in contents), (
        "iOS auth entry must appear in search (not filtered by surface)"
    )

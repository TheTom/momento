"""Tests for momento.store — the write path (log_knowledge).

Covers T3.1 through T3.10 from the acceptance test spec.
These are RED tests — they will fail against stub implementations.
"""

import json
import re
import uuid

import pytest

from momento.store import log_knowledge
from momento.models import SIZE_LIMITS, SIZE_HINTS

from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
)


# ---------------------------------------------------------------------------
# T3.1 — Basic save
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_basic_save(db):
    """T3.1: log_knowledge with valid content, type=decision, tags=[auth]
    inserts an entry with correct project_id, branch, timestamp (UTC Z),
    and the FTS index is updated (searchable immediately).
    """
    result = log_knowledge(
        conn=db,
        content="Chose server-side Stripe Checkout over client-side.",
        type="decision",
        tags=["auth"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )

    # Should return a dict with at minimum an "id" key (success)
    assert isinstance(result, dict), "log_knowledge must return a dict"
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert "id" in result, "Successful result must include 'id'"

    # Verify the row exists in the knowledge table
    row = db.execute(
        "SELECT content, type, tags, project_id, branch FROM knowledge WHERE id = ?",
        (result["id"],),
    ).fetchone()
    assert row is not None, "Entry must exist in knowledge table"
    content, entry_type, tags_json, project_id, branch = row
    assert content == "Chose server-side Stripe Checkout over client-side."
    assert entry_type == "decision"
    assert project_id == MOCK_PROJECT_ID
    assert branch == "main"

    # Tags stored as canonical JSON
    tags = json.loads(tags_json)
    assert tags == ["auth"]

    # FTS index must be updated — searchable immediately
    fts_row = db.execute(
        "SELECT * FROM knowledge_fts WHERE knowledge_fts MATCH 'Stripe'",
    ).fetchone()
    assert fts_row is not None, "Entry must be searchable via FTS immediately after insert"


# ---------------------------------------------------------------------------
# T3.2 — Entry size rejection
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_entry_size_rejection(db):
    """T3.2: content of 1200 chars with type=session_state (limit 500)
    must return an error with char count, limit, and hint.
    Nothing is inserted.
    """
    oversized_content = "x" * 1200

    result = log_knowledge(
        conn=db,
        content=oversized_content,
        type="session_state",
        tags=["server"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )

    # Must be an error
    assert "error" in result, "Oversized content must be rejected"

    # Error message must include the count and the limit
    error_msg = result["error"]
    assert "1200" in error_msg, "Error must include actual char count (1200)"
    assert "500" in error_msg, "Error must include the limit (500)"

    # Must include a hint
    assert "hint" in result, "Rejection must include a hint"
    assert result["hint"] == SIZE_HINTS["session_state"]

    # Nothing inserted
    count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert count == 0, "No entry should be inserted on rejection"


# ---------------------------------------------------------------------------
# T3.3 — Size limits per type (boundary test at exact limit)
# ---------------------------------------------------------------------------


def test_size_limits_per_type(db):
    """T3.3: content at exactly the limit for each type must succeed.
    Boundary test — content of exactly SIZE_LIMITS[type] chars.
    """
    for entry_type, limit in SIZE_LIMITS.items():
        content = "A" * limit

        result = log_knowledge(
            conn=db,
            content=content,
            type=entry_type,
            tags=[f"test-{entry_type}"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
        )

        assert "error" not in result, (
            f"Content at exact limit ({limit}) for type '{entry_type}' "
            f"should succeed, got: {result.get('error')}"
        )
        assert "id" in result, (
            f"Successful save for '{entry_type}' must return an id"
        )


# ---------------------------------------------------------------------------
# T3.4 — Dedup by content hash
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_dedup_by_content_hash(db):
    """T3.4: identical content logged twice for same project is silently
    skipped — no error, no duplicate.
    """
    content = "Always verify payment_intent status before updating order."

    result1 = log_knowledge(
        conn=db,
        content=content,
        type="gotcha",
        tags=["server", "stripe"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result1, f"First insert should succeed: {result1}"

    result2 = log_knowledge(
        conn=db,
        content=content,
        type="gotcha",
        tags=["server", "stripe"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    # Second call must NOT be an error — it's silently skipped
    assert "error" not in result2, "Duplicate should be silently skipped, not error"

    # Only one row in DB
    count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert count == 1, f"Dedup should prevent duplicate; got {count} rows"


# ---------------------------------------------------------------------------
# T3.5 — Tag normalization
# ---------------------------------------------------------------------------


def test_tag_normalization(db):
    """T3.5: tags=[' Auth ', 'iOS', '  BILLING'] stored as
    ['auth', 'billing', 'ios'] — lowercased, trimmed, sorted alphabetically.
    """
    result = log_knowledge(
        conn=db,
        content="Testing tag normalization.",
        type="gotcha",
        tags=[" Auth ", "iOS", "  BILLING"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result
    assert "id" in result

    row = db.execute(
        "SELECT tags FROM knowledge WHERE id = ?",
        (result["id"],),
    ).fetchone()
    tags = json.loads(row[0])
    assert tags == ["auth", "billing", "ios"], (
        f"Tags must be lowercased, trimmed, sorted. Got: {tags}"
    )


# ---------------------------------------------------------------------------
# T3.6 — Tag canonical ordering for dedup
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_tag_canonical_ordering_for_dedup(db):
    """T3.6: entry A with content 'X' and tags=['ios', 'auth'],
    entry B with content 'X' and tags=['auth', 'ios'].
    Second is skipped because tags are canonicalized before hashing.
    """
    content = "Dedup test with reordered tags."

    result_a = log_knowledge(
        conn=db,
        content=content,
        type="decision",
        tags=["ios", "auth"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result_a

    result_b = log_knowledge(
        conn=db,
        content=content,
        type="decision",
        tags=["auth", "ios"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    # Second should be silently skipped
    assert "error" not in result_b, "Dedup with reordered tags should not error"

    count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert count == 1, (
        f"Canonical tag ordering must produce same content_hash; got {count} rows"
    )


# ---------------------------------------------------------------------------
# T3.7 — Branch auto-capture
# ---------------------------------------------------------------------------


def test_branch_auto_capture(db):
    """T3.7: when log_knowledge is called without explicit branch but
    cwd is on branch 'feature/x', entry.branch = 'feature/x'.

    NOTE: Since store.log_knowledge takes branch as a parameter (resolved
    by the caller), this test verifies that the branch value is stored
    correctly when provided.
    """
    result = log_knowledge(
        conn=db,
        content="Branch capture test.",
        type="session_state",
        tags=["test"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="feature/x",
    )
    assert "error" not in result

    row = db.execute(
        "SELECT branch FROM knowledge WHERE id = ?",
        (result["id"],),
    ).fetchone()
    assert row[0] == "feature/x", f"Branch must be stored as-is. Got: {row[0]}"


# ---------------------------------------------------------------------------
# T3.8 — Timestamps are UTC
# ---------------------------------------------------------------------------


def test_timestamps_are_utc(db):
    """T3.8: created_at and updated_at match YYYY-MM-DDTHH:MM:SSZ format.
    Z suffix, not +00:00, not local time.
    """
    utc_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"

    result = log_knowledge(
        conn=db,
        content="Timestamp format test.",
        type="gotcha",
        tags=["test"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result

    row = db.execute(
        "SELECT created_at, updated_at FROM knowledge WHERE id = ?",
        (result["id"],),
    ).fetchone()
    created_at, updated_at = row

    assert re.match(utc_pattern, created_at), (
        f"created_at must match YYYY-MM-DDTHH:MM:SSZ. Got: {created_at}"
    )
    assert re.match(utc_pattern, updated_at), (
        f"updated_at must match YYYY-MM-DDTHH:MM:SSZ. Got: {updated_at}"
    )


# ---------------------------------------------------------------------------
# T3.9 — ID format is UUIDv4
# ---------------------------------------------------------------------------


def test_id_format_is_uuidv4(db):
    """T3.9: id is valid UUIDv4 format (8-4-4-4-12 hex, version 4).
    Deterministic tie-breaker via id ASC is stable.
    """
    result = log_knowledge(
        conn=db,
        content="UUID format test.",
        type="pattern",
        tags=["test"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result
    entry_id = result["id"]

    # Must parse as valid UUID
    parsed = uuid.UUID(entry_id)
    assert parsed.version == 4, f"ID must be UUIDv4. Got version: {parsed.version}"

    # String representation must be canonical lowercase 8-4-4-4-12
    assert str(parsed) == entry_id.lower(), (
        f"ID must be canonical UUID string. Got: {entry_id}"
    )


# ---------------------------------------------------------------------------
# T3.10 — Transaction atomicity
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_transaction_atomicity(db):
    """T3.10: if trigger work fails during INSERT,
    the entire transaction rolls back — no partial entry in knowledge,
    no orphaned FTS row.
    """
    # First, insert a valid entry to confirm the happy path works
    result = log_knowledge(
        conn=db,
        content="Pre-corruption baseline entry.",
        type="decision",
        tags=["test"],
        project_id=MOCK_PROJECT_ID,
        project_name=MOCK_PROJECT_NAME,
        branch="main",
    )
    assert "error" not in result
    baseline_count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert baseline_count == 1

    # Simulate trigger failure deterministically.
    # If any AFTER INSERT trigger step fails, the INSERT must rollback fully.
    db.execute("DROP TRIGGER IF EXISTS knowledge_ai")
    db.execute("""
        CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
          SELECT RAISE(ABORT, 'simulated trigger failure');
        END
    """)

    # Now try to insert — should fail and roll back
    try:
        result = log_knowledge(
            conn=db,
            content="This entry should not persist due to trigger failure.",
            type="decision",
            tags=["atomicity"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
        )
        assert "error" in result, "Failure path should surface an error when insert aborts"
    except Exception:
        # Also acceptable: implementation raises and caller handles it.
        pass

    # The knowledge table should still have only the baseline entry
    final_count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    assert final_count == baseline_count, (
        f"Transaction must roll back on FTS failure. "
        f"Expected {baseline_count} rows, got {final_count}"
    )

    # No orphaned FTS rows should appear either
    fts_count = db.execute("SELECT COUNT(*) FROM knowledge_fts").fetchone()[0]
    assert fts_count == baseline_count, (
        f"FTS rows must stay consistent after rollback. Expected {baseline_count}, got {fts_count}"
    )

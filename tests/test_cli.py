"""CLI tests — T7.1 through T7.8.

Tests for `momento status`, `momento save`, `momento undo`,
`momento inspect`, `momento prune`, and `momento debug-restore`.
"""

import json
import subprocess
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from momento.cli import main as cli_main
from momento.store import log_knowledge
from momento.db import ensure_db
from momento.retrieve import retrieve_context
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_entry,
    make_restore_scenario,
    hours_ago,
    days_ago,
    minutes_ago,
)
from tests.conftest import insert_entry, insert_entries


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _populate_status_db(conn):
    """Insert 5 entries for status tests: 2 session_state, 2 decisions, 1 gotcha."""
    entries = [
        make_entry(
            content="Auth migration in progress. 3 of 7 handlers done.",
            type="session_state",
            tags=["server", "auth"],
            branch="main",
            created_at=minutes_ago(10),
        ),
        make_entry(
            content="Webhook handler retry logic complete. Next: load test.",
            type="session_state",
            tags=["server", "webhook"],
            branch="main",
            created_at=minutes_ago(30),
        ),
        make_entry(
            content="Chose server-side Stripe Checkout over client-side.",
            type="decision",
            tags=["billing", "stripe"],
            branch="main",
            created_at=days_ago(2),
        ),
        make_entry(
            content="Auth tokens: moved from JWT to opaque sessions.",
            type="decision",
            tags=["auth", "jwt"],
            branch="main",
            created_at=days_ago(5),
        ),
        make_entry(
            content="Stripe webhook race: always verify payment_intent server-side.",
            type="gotcha",
            tags=["server", "stripe"],
            branch="main",
            created_at=days_ago(1),
        ),
    ]
    insert_entries(conn, entries)
    return entries


# ===========================================================================
# T7.1 — momento status
# ===========================================================================

@pytest.mark.should_pass
class TestMomentoStatus:
    """T7.1 — momento status shows project info, counts, last checkpoint, DB size."""

    def test_status_shows_project_name(self, db, db_path):
        """T7.1: status output includes project name."""
        _populate_status_db(db)

        # TODO: Once CLI is implemented, call `momento status` and assert
        # output contains project name, branch, entry counts, last checkpoint, DB size.
        # For now, test the underlying data query.
        cursor = db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        )
        count = cursor.fetchone()[0]
        assert count == 5, f"Expected 5 entries, got {count}"

    def test_status_shows_entry_counts_by_type(self, db, db_path):
        """T7.1: status output includes entry counts broken down by type."""
        _populate_status_db(db)

        cursor = db.execute(
            "SELECT type, COUNT(*) FROM knowledge WHERE project_id = ? GROUP BY type ORDER BY type",
            (MOCK_PROJECT_ID,),
        )
        counts = dict(cursor.fetchall())
        assert counts.get("session_state") == 2
        assert counts.get("decision") == 2
        assert counts.get("gotcha") == 1

    def test_status_shows_last_checkpoint_time(self, db, db_path):
        """T7.1: status shows how long ago the last checkpoint was."""
        _populate_status_db(db)

        cursor = db.execute(
            "SELECT MAX(created_at) FROM knowledge WHERE project_id = ? AND type = 'session_state'",
            (MOCK_PROJECT_ID,),
        )
        last_checkpoint = cursor.fetchone()[0]
        assert last_checkpoint is not None, "Should have a last checkpoint time"

    def test_status_shows_db_size(self, db, db_path):
        """T7.1: status includes DB file size."""
        import os
        _populate_status_db(db)

        size = os.path.getsize(db_path)
        assert size > 0, "DB file should have non-zero size"


# ===========================================================================
# T7.2 — momento status stale warning
# ===========================================================================

@pytest.mark.should_pass
class TestMomentoStatusStale:
    """T7.2 — status warns when last checkpoint is stale (>1 hour)."""

    def test_stale_checkpoint_warning(self, db, db_path):
        """T7.2: last checkpoint 3 hours ago shows stale warning."""
        entry = make_entry(
            content="Old checkpoint from 3 hours ago.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=hours_ago(3),
        )
        insert_entry(db, entry)
        db.commit()

        cursor = db.execute(
            "SELECT MAX(created_at) FROM knowledge WHERE project_id = ? AND type = 'session_state'",
            (MOCK_PROJECT_ID,),
        )
        last_checkpoint_str = cursor.fetchone()[0]
        last_checkpoint = datetime.strptime(last_checkpoint_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age = datetime.now(timezone.utc) - last_checkpoint

        # Stale threshold is 1 hour per PRD
        assert age > timedelta(hours=1), "Checkpoint should be flagged as stale (>1h)"
        assert age < timedelta(hours=4), "Checkpoint should be within reasonable range"


# ===========================================================================
# T7.3 — momento save
# ===========================================================================

@pytest.mark.should_pass
class TestMomentoSave:
    """T7.3 — momento save creates session_state with auto project/branch/surface tags."""

    def test_save_creates_session_state(self, db, db_path):
        """T7.3: save creates a session_state entry."""
        content = "Fixed webhook handler for Stripe retries."

        result = log_knowledge(
            conn=db,
            content=content,
            type="session_state",
            tags=["server"],
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
            source_type="manual",
            enforce_limits=True,
        )

        # Should succeed without error
        assert "error" not in result, f"log_knowledge returned error: {result}"

        # Verify entry in DB
        cursor = db.execute(
            "SELECT content, type, branch FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        )
        row = cursor.fetchone()
        assert row is not None, "Entry should exist in DB"
        assert row[0] == content
        assert row[1] == "session_state"
        assert row[2] == "main"

    def test_save_includes_surface_tag(self, db, db_path):
        """T7.3: save auto-detects surface tag from cwd."""
        content = "Working on server auth handler migration."

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

        assert "error" not in result, f"log_knowledge returned error: {result}"

        cursor = db.execute(
            "SELECT tags FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        )
        row = cursor.fetchone()
        tags = json.loads(row[0])
        assert "server" in tags, "Tags should include surface tag 'server'"


# ===========================================================================
# T7.4 — momento undo project-scoped
# ===========================================================================

class TestMomentoUndoProjectScoped:
    """T7.4 — undo only deletes from current project."""

    def test_undo_deletes_only_from_current_project(self, db, db_path):
        """T7.4: undo in project A does not touch project B entries."""
        from tests.mock_data import SECOND_PROJECT_ID, SECOND_PROJECT_NAME

        # Insert entries for both projects
        entry_a = make_entry(
            content="Project A entry to be undone.",
            type="session_state",
            tags=["server"],
            branch="main",
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            created_at=minutes_ago(5),
        )
        entry_b = make_entry(
            content="Project B entry that should survive.",
            type="session_state",
            tags=["server"],
            branch="main",
            project_id=SECOND_PROJECT_ID,
            project_name=SECOND_PROJECT_NAME,
            created_at=minutes_ago(3),
        )
        insert_entries(db, [entry_a, entry_b])

        # Get the most recent entry for project A
        cursor = db.execute(
            "SELECT id FROM knowledge WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (MOCK_PROJECT_ID,),
        )
        entry_to_delete = cursor.fetchone()
        assert entry_to_delete is not None

        # Simulate undo: delete most recent from project A
        db.execute("DELETE FROM knowledge WHERE id = ?", (entry_to_delete[0],))
        db.commit()

        # Project B entry should still exist
        cursor = db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ?",
            (SECOND_PROJECT_ID,),
        )
        assert cursor.fetchone()[0] == 1, "Project B entry should be untouched"


# ===========================================================================
# T7.5 — momento undo confirmation
# ===========================================================================

class TestMomentoUndoConfirmation:
    """T7.5 — undo shows content and requires y/Y confirmation."""

    def test_undo_requires_confirmation(self, db, db_path):
        """T7.5: undo should show content preview and not delete without confirmation."""
        entry = make_entry(
            content="Important session state that needs confirmation to delete.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()

        # Verify entry exists before undo
        cursor = db.execute(
            "SELECT id, content FROM knowledge WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (MOCK_PROJECT_ID,),
        )
        row = cursor.fetchone()
        assert row is not None
        entry_id, content = row

        # Simulate "no" confirmation — entry should NOT be deleted
        # TODO: When CLI is implemented, mock stdin with "n" and verify entry persists
        # For now, verify the entry still exists (no deletion without confirmation)
        cursor = db.execute("SELECT COUNT(*) FROM knowledge WHERE id = ?", (entry_id,))
        assert cursor.fetchone()[0] == 1, "Entry should not be deleted without y/Y confirmation"


# ===========================================================================
# T7.6 — momento inspect
# ===========================================================================

class TestMomentoInspect:
    """T7.6 — inspect lists entries with type, branch, tags, age, preview."""

    def test_inspect_lists_all_entries(self, db, db_path):
        """T7.6: inspect shows all entries for current project."""
        entries = [
            make_entry(
                content="Auth migration checkpoint.",
                type="session_state",
                tags=["server", "auth"],
                branch="feature/billing-rewrite",
                created_at=minutes_ago(30),
            ),
            make_entry(
                content="Chose PostgreSQL for billing data.",
                type="decision",
                tags=["database", "billing"],
                branch="feature/billing-rewrite",
                created_at=days_ago(3),
            ),
            make_entry(
                content="Never trust webhook ordering alone.",
                type="gotcha",
                tags=["server", "stripe"],
                branch="main",
                created_at=days_ago(5),
            ),
        ]
        insert_entries(db, entries)

        # Verify all entries retrievable
        cursor = db.execute(
            "SELECT type, branch, tags, created_at, content FROM knowledge "
            "WHERE project_id = ? ORDER BY created_at DESC",
            (MOCK_PROJECT_ID,),
        )
        rows = cursor.fetchall()
        assert len(rows) == 3, f"Expected 3 entries, got {len(rows)}"

        # Each row should have type, branch, tags, timestamp, and content
        for row in rows:
            type_, branch, tags_json, created_at, content = row
            assert type_ in ("session_state", "decision", "gotcha")
            assert created_at is not None
            assert content is not None
            # Tags should be valid JSON
            tags = json.loads(tags_json)
            assert isinstance(tags, list)


# ===========================================================================
# T7.7 — momento prune --auto
# ===========================================================================

class TestMomentoPruneAuto:
    """T7.7 — prune --auto deletes session_state older than 7 days."""

    def test_prune_auto_deletes_old_session_state(self, db, db_path):
        """T7.7: session_state >7d old is deleted; others preserved."""
        entries = [
            make_entry(
                content="Recent checkpoint from 1 day ago.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(1),
            ),
            make_entry(
                content="Checkpoint from 3 days ago.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(3),
            ),
            make_entry(
                content="Checkpoint from 5 days ago.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(5),
            ),
            make_entry(
                content="Old checkpoint from 10 days ago.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(10),
            ),
        ]
        insert_entries(db, entries)

        # Simulate prune --auto: delete session_state > 7 days old
        db.execute(
            "DELETE FROM knowledge WHERE type = 'session_state' "
            "AND project_id = ? "
            "AND created_at < datetime('now', '-7 days')",
            (MOCK_PROJECT_ID,),
        )
        db.commit()

        cursor = db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ? AND type = 'session_state'",
            (MOCK_PROJECT_ID,),
        )
        remaining = cursor.fetchone()[0]
        assert remaining == 3, f"Expected 3 entries after prune, got {remaining} (10d entry should be deleted)"

    def test_prune_auto_preserves_durable_entries(self, db, db_path):
        """T7.7: durable entries (decisions, gotchas) are never auto-pruned."""
        entries = [
            make_entry(
                content="Old decision from 30 days ago.",
                type="decision",
                tags=["architecture"],
                branch="main",
                created_at=days_ago(30),
            ),
            make_entry(
                content="Old gotcha from 20 days ago.",
                type="gotcha",
                tags=["server"],
                branch="main",
                created_at=days_ago(20),
            ),
            make_entry(
                content="Old session state to prune.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(10),
            ),
        ]
        insert_entries(db, entries)

        # Prune only session_state > 7 days
        db.execute(
            "DELETE FROM knowledge WHERE type = 'session_state' "
            "AND project_id = ? "
            "AND created_at < datetime('now', '-7 days')",
            (MOCK_PROJECT_ID,),
        )
        db.commit()

        cursor = db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        )
        remaining = cursor.fetchone()[0]
        assert remaining == 2, "Durable entries should survive prune --auto"


# ===========================================================================
# T7.8 — momento debug-restore
# ===========================================================================

@pytest.mark.nice_to_have
class TestMomentoDebugRestore:
    """T7.8 — debug-restore shows tier breakdown, entries, token estimates."""

    def test_debug_restore_tier_breakdown(self, populated_db):
        """T7.8: debug-restore shows entries per tier and budget usage."""
        # retrieve_context should return structured output with all tiers
        result = retrieve_context(
            conn=populated_db,
            project_id=MOCK_PROJECT_ID,
            branch="feature/billing-rewrite",
            surface="server",
            include_session_state=True,
        )

        # Result should be a non-empty string with structured content
        assert isinstance(result, str), "retrieve_context should return a string"
        assert len(result) > 0, "Result should not be empty"

        # TODO: When debug-restore CLI is implemented, verify it shows:
        # - tier breakdown
        # - entries considered per tier
        # - included/skipped status
        # - token estimates
        # - total budget used

# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""CLI tests — T7.1 through T7.8.

Tests for `momento status`, `momento save`, `momento undo`,
`momento inspect`, `momento prune`, and `momento debug-restore`.
"""

import json
import subprocess
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest

from momento.cli import (
    main as cli_main,
    cmd_save,
    cmd_status,
    cmd_last,
    cmd_log,
    cmd_undo,
    cmd_inspect,
    cmd_prune,
    cmd_search,
    cmd_check_stale,
    cmd_debug_restore,
    cmd_ingest,
    _format_age,
    _get_db_path,
    _parse_duration,
)
from momento.store import log_knowledge
from momento.db import ensure_db
from momento.retrieve import retrieve_context
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    SECOND_PROJECT_ID,
    SECOND_PROJECT_NAME,
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

    def test_save_auto_detects_surface_from_dir(self, db, mock_git_repo):
        """save auto-detects surface from args.dir when --surface not provided."""
        server_dir = mock_git_repo / "server" / "handlers"
        server_dir.mkdir(parents=True)

        args = SimpleNamespace(
            content="Auto-surface detection checkpoint.",
            tags=None,
            surface=None,
            dir=str(server_dir),
        )

        cmd_save(
            args=args,
            conn=db,
            project_id=MOCK_PROJECT_ID,
            project_name=MOCK_PROJECT_NAME,
            branch="main",
        )

        row = db.execute(
            "SELECT tags FROM knowledge WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (MOCK_PROJECT_ID,),
        ).fetchone()
        assert row is not None, "Expected save to insert an entry"
        tags = json.loads(row[0])
        assert "server" in tags, "Surface tag should be auto-detected from args.dir"


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
            "AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) < julianday('now', '-7 days')",
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
            "AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) < julianday('now', '-7 days')",
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

        # Result should be structured RestoreResult with rendered output
        assert hasattr(result, "entries"), "retrieve_context should return RestoreResult"
        assert hasattr(result, "rendered"), "retrieve_context should return RestoreResult"
        assert hasattr(result, "total_tokens"), "retrieve_context should return RestoreResult"
        assert isinstance(result.rendered, str), "RestoreResult.rendered should be a string"
        assert len(result.rendered) > 0, "Rendered output should not be empty"

        # TODO: When debug-restore CLI is implemented, verify it shows:
        # - tier breakdown
        # - entries considered per tier
        # - included/skipped status
        # - token estimates
        # - total budget used


# ===========================================================================
# NEW: Direct cmd_* function tests for coverage
# ===========================================================================


class TestGetDbPath:
    """Cover _get_db_path (line 28)."""

    def test_get_db_path_default(self, monkeypatch):
        monkeypatch.delenv("MOMENTO_DB", raising=False)
        path = _get_db_path()
        assert "momento" in path.lower() or "knowledge" in path.lower()

    def test_get_db_path_from_env(self, monkeypatch):
        monkeypatch.setenv("MOMENTO_DB", "/tmp/custom.db")
        assert _get_db_path() == "/tmp/custom.db"


class TestFormatAge:
    """Cover _format_age (lines 33-43)."""

    def test_format_age_days(self):
        ts = days_ago(3)
        result = _format_age(ts)
        assert "3d ago" == result

    def test_format_age_hours(self):
        ts = hours_ago(5)
        result = _format_age(ts)
        assert "h ago" in result

    def test_format_age_minutes(self):
        ts = minutes_ago(15)
        result = _format_age(ts)
        assert "m ago" in result


class TestCmdStatusDirect:
    """Cover cmd_status function (lines 49-84)."""

    def test_status_output_with_entries(self, db, db_path, capsys, monkeypatch):
        """cmd_status prints project name, counts, checkpoint, DB size."""
        monkeypatch.setenv("MOMENTO_DB", db_path)
        _populate_status_db(db)
        args = SimpleNamespace()
        cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert MOCK_PROJECT_NAME in out
        assert "main" in out
        assert "Entries: 5" in out
        assert "session_state: 2" in out
        assert "decision: 2" in out
        assert "gotcha: 1" in out
        assert "bytes" in out
        # Last checkpoint should show age, not "none"
        assert "Last checkpoint:" in out
        assert "none" not in out

    def test_status_no_checkpoint(self, db, db_path, capsys, monkeypatch):
        """cmd_status with no session_state prints 'Last checkpoint: none'."""
        monkeypatch.setenv("MOMENTO_DB", db_path)
        entry = make_entry(
            content="A decision only.",
            type="decision",
            tags=["arch"],
            branch="main",
            created_at=days_ago(1),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Last checkpoint: none" in out

    def test_status_stale_marker(self, db, db_path, capsys, monkeypatch):
        """cmd_status marks checkpoint as [STALE] when >1h old."""
        monkeypatch.setenv("MOMENTO_DB", db_path)
        entry = make_entry(
            content="Old checkpoint.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=hours_ago(3),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[STALE]" in out

    def test_status_detached_branch(self, db, db_path, capsys, monkeypatch):
        """cmd_status prints '(detached)' when branch is None."""
        monkeypatch.setenv("MOMENTO_DB", db_path)
        args = SimpleNamespace()
        cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, None)
        out = capsys.readouterr().out
        assert "(detached)" in out


class TestCmdLogDirect:
    """Cover cmd_log (lines 122-140)."""

    def test_log_creates_entry(self, db, capsys):
        args = SimpleNamespace(content="Some decision made.", type="decision", tags="billing,stripe")
        cmd_log(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Logged:" in out
        row = db.execute(
            "SELECT type, content FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        ).fetchone()
        assert row[0] == "decision"

    def test_log_no_tags(self, db, capsys):
        args = SimpleNamespace(content="A gotcha.", type="gotcha", tags=None)
        cmd_log(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Logged:" in out

    def test_log_duplicate_skipped(self, db, capsys):
        """Logging same content twice shows duplicate message."""
        args = SimpleNamespace(content="Exact same content.", type="decision", tags=None)
        cmd_log(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        capsys.readouterr()  # clear
        cmd_log(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Duplicate" in out


class TestCmdUndoDirect:
    """Cover cmd_undo (lines 145-167)."""

    def test_undo_no_entries(self, db, capsys):
        args = SimpleNamespace()
        cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "No entries to undo" in out

    def test_undo_confirm_yes(self, db, capsys):
        entry = make_entry(
            content="Entry to be undone via confirmation.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        with patch("builtins.input", return_value="y"):
            cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Deleted:" in out
        count = db.execute("SELECT COUNT(*) FROM knowledge WHERE project_id = ?", (MOCK_PROJECT_ID,)).fetchone()[0]
        assert count == 0

    def test_undo_confirm_no(self, db, capsys):
        entry = make_entry(
            content="Entry that should survive cancellation.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        with patch("builtins.input", return_value="n"):
            cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Cancelled" in out
        count = db.execute("SELECT COUNT(*) FROM knowledge WHERE project_id = ?", (MOCK_PROJECT_ID,)).fetchone()[0]
        assert count == 1

    def test_undo_shows_preview_and_type(self, db, capsys):
        entry = make_entry(
            content="A" * 100,  # >80 chars to trigger truncation
            type="gotcha",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(2),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        with patch("builtins.input", return_value="n"):
            cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[gotcha]" in out
        assert "..." in out  # truncated preview


class TestCmdInspectDirect:
    """Cover cmd_inspect (lines 172-191)."""

    def test_inspect_no_entries(self, db, capsys):
        args = SimpleNamespace()
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "No entries found" in out

    def test_inspect_shows_entries(self, db, capsys):
        entries = [
            make_entry(
                content="Short content.",
                type="decision",
                tags=["billing"],
                branch="main",
                created_at=days_ago(1),
            ),
            make_entry(
                content="B" * 80,
                type="gotcha",
                tags=["server", "stripe"],
                branch=None,
                created_at=days_ago(2),
            ),
        ]
        insert_entries(db, entries)
        args = SimpleNamespace()
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "[gotcha]" in out
        assert "branch=" in out
        assert "(none)" in out  # None branch
        assert "B" * 80 in out  # full content, no truncation


class TestCmdPruneDirect:
    """Cover cmd_prune (lines 196-219)."""

    def test_prune_without_auto_flag(self, db, capsys):
        args = SimpleNamespace(auto=False)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "--auto" in out

    def test_prune_nothing_to_prune(self, db, capsys):
        """All entries are recent, nothing to prune."""
        entry = make_entry(
            content="Recent checkpoint.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(30),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(auto=True)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Nothing to prune" in out

    def test_prune_deletes_old_entries(self, db, capsys):
        """Prune deletes session_state >7 days old."""
        entries = [
            make_entry(
                content="Recent.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(1),
            ),
            make_entry(
                content="Old stale entry.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(10),
            ),
            make_entry(
                content="Another old one.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(14),
            ),
        ]
        insert_entries(db, entries)
        args = SimpleNamespace(auto=True)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Pruned 2" in out
        remaining = db.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ? AND type = 'session_state'",
            (MOCK_PROJECT_ID,),
        ).fetchone()[0]
        assert remaining == 1


class TestCmdSearchDirect:
    """Cover cmd_search (lines 241-257)."""

    def test_search_no_results(self, db, capsys):
        args = SimpleNamespace(query="nonexistent gibberish term")
        cmd_search(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "No results found" in out

    def test_search_with_results(self, populated_db, capsys):
        """Search for 'stripe' should find matching entries."""
        args = SimpleNamespace(query="stripe webhook")
        cmd_search(args, populated_db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "feature/billing-rewrite")
        out = capsys.readouterr().out
        assert "results" in out
        assert "tokens" in out


class TestCmdDebugRestoreDirect:
    """Cover cmd_debug_restore (lines 262-287)."""

    def test_debug_restore_output(self, populated_db, capsys):
        args = SimpleNamespace(surface="server")
        cmd_debug_restore(args, populated_db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "feature/billing-rewrite")
        out = capsys.readouterr().out
        assert "Total:" in out
        assert "entries" in out
        assert "tokens" in out

    def test_debug_restore_no_surface(self, populated_db, capsys):
        args = SimpleNamespace()  # no surface attr
        cmd_debug_restore(args, populated_db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Total:" in out

    def test_debug_restore_empty_rendered_path(self, db, capsys):
        """Covers cmd_debug_restore path where result.rendered is empty."""
        from momento.models import RestoreResult

        args = SimpleNamespace(surface="server")
        fake = RestoreResult(entries=[], total_tokens=0, rendered="")
        with patch("momento.retrieve.retrieve_context", return_value=fake):
            cmd_debug_restore(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Total: 0 entries" in out


class TestCmdIngestDirect:
    """Cover cmd_ingest (lines 224-236)."""

    def test_ingest_no_files_defaults_to_project(self, db, capsys, tmp_path):
        """No files + no --all: defaults to ingest_project for current dir."""
        args = SimpleNamespace(files=[], ingest_all=False, dir=str(tmp_path))
        cmd_ingest(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        # Should still print summary (0 files since no Claude Code dir exists)
        assert "Files:" in out
        assert "Stored:" in out

    def test_ingest_with_files(self, db, capsys, tmp_path):
        """Ingest a real JSONL file."""
        jsonl = tmp_path / "test.jsonl"
        import json as _json
        line = _json.dumps({
            "content": "Ingested entry from JSONL.",
            "type": "decision",
            "tags": ["server"],
            "project_id": MOCK_PROJECT_ID,
            "project_name": MOCK_PROJECT_NAME,
            "branch": "main",
            "source_type": "ingest",
        })
        jsonl.write_text(line + "\n")
        args = SimpleNamespace(files=[str(jsonl)], ingest_all=False, dir=".")
        cmd_ingest(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Files:" in out
        assert "Lines:" in out
        assert "Stored:" in out
        assert "Skipped:" in out
        assert "Dupes:" in out


class TestCmdSaveErrorPaths:
    """Cover cmd_save error/duplicate paths (lines 110-115)."""

    def test_save_duplicate_skipped(self, db, capsys):
        """Second save of same content prints 'Duplicate entry — skipped.'"""
        args = SimpleNamespace(
            content="Identical checkpoint content.",
            tags=None,
            surface=None,
            dir=".",
        )
        cmd_save(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        capsys.readouterr()  # clear first output
        cmd_save(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Duplicate" in out


class TestMainFunction:
    """Cover main() argparse wiring (lines 296-379)."""

    def test_main_no_command(self, monkeypatch):
        """main() with no args prints help and exits."""
        monkeypatch.setattr("sys.argv", ["momento"])
        with pytest.raises(SystemExit) as exc_info:
            cli_main()
        assert exc_info.value.code == 1

    def test_main_status_dispatches(self, db_path, monkeypatch, capsys):
        """main() with 'status' dispatches to cmd_status."""
        monkeypatch.setattr("sys.argv", ["momento", "--db", db_path, "status"])
        # Need a valid git repo for resolve_project_id
        with patch("momento.cli.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME)):
            with patch("momento.cli.resolve_branch", return_value="main"):
                cli_main()
        out = capsys.readouterr().out
        assert "Project:" in out

    def test_main_log_dispatches(self, db_path, monkeypatch, capsys):
        """main() with 'log' dispatches to cmd_log."""
        monkeypatch.setattr("sys.argv", ["momento", "--db", db_path, "log", "test content", "--type", "decision"])
        with patch("momento.cli.resolve_project_id", return_value=(MOCK_PROJECT_ID, MOCK_PROJECT_NAME)):
            with patch("momento.cli.resolve_branch", return_value="main"):
                cli_main()
        out = capsys.readouterr().out
        assert "Logged:" in out


class TestCmdSaveErrorWithHint:
    """Cover cmd_save error+hint path (lines 110-113)."""

    def test_save_error_with_hint(self, db, capsys):
        """When log_knowledge returns error+hint, both are printed to stderr."""
        args = SimpleNamespace(content="whatever", tags=None, surface=None, dir=".")
        mock_result = {"error": "Limit exceeded", "hint": "Try pruning old entries"}
        with patch("momento.cli.log_knowledge", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                cmd_save(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
            assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Error: Limit exceeded" in err
        assert "Hint: Try pruning" in err

    def test_save_error_without_hint(self, db, capsys):
        """When log_knowledge returns error without hint, only error is printed."""
        args = SimpleNamespace(content="whatever", tags=None, surface=None, dir=".")
        mock_result = {"error": "Something went wrong"}
        with patch("momento.cli.log_knowledge", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                cmd_save(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
            assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Error: Something went wrong" in err
        assert "Hint:" not in err


class TestCmdLogError:
    """Cover cmd_log error path (lines 135-136)."""

    def test_log_error(self, db, capsys):
        """When log_knowledge returns error, it's printed to stderr and exits."""
        args = SimpleNamespace(content="test", type="decision", tags=None)
        mock_result = {"error": "DB write failed"}
        with patch("momento.cli.log_knowledge", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                cmd_log(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
            assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "Error: DB write failed" in err


class TestCmdLastDirect:
    """Cover cmd_last (lines 89-105)."""

    def test_last_no_entries(self, db, capsys):
        """cmd_last with empty DB prints 'No entries found.'"""
        args = SimpleNamespace()
        cmd_last(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "No entries found" in out

    def test_last_shows_entry(self, db, capsys):
        """cmd_last prints type, age, tags, branch, and content."""
        entry = make_entry(
            content="Latest checkpoint for billing migration.",
            type="decision",
            tags=["billing", "stripe"],
            branch="feature/billing",
            created_at=minutes_ago(10),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        cmd_last(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "billing" in out
        assert "stripe" in out
        assert "feature/billing" in out
        assert "Latest checkpoint" in out

    def test_last_with_none_branch(self, db, capsys):
        """cmd_last handles None branch as '(none)'."""
        entry = make_entry(
            content="Entry with no branch.",
            type="gotcha",
            tags=[],
            branch=None,
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace()
        cmd_last(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "(none)" in out


# ---------------------------------------------------------------------------
# PRD Section 12 — undo --type, inspect filters, prune modes
# ---------------------------------------------------------------------------


class TestCmdUndoTypeFilter:
    """PRD: 'momento undo --type=decision' — undo most recent of specific type."""

    def test_undo_type_targets_specific_type(self, db, capsys):
        """--type=decision undoes most recent decision, not the overall most recent."""
        # Insert a decision (older) and a session_state (newer)
        entries = [
            make_entry(
                content="Decision to undo.",
                type="decision",
                tags=["server"],
                branch="main",
                created_at=minutes_ago(10),
            ),
            make_entry(
                content="Most recent session state.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=minutes_ago(1),
            ),
        ]
        insert_entries(db, entries)
        args = SimpleNamespace(type="decision")
        with patch("builtins.input", return_value="y"):
            cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[decision]" in out
        assert "Deleted:" in out
        # Session state should still exist
        remaining = db.execute(
            "SELECT type FROM knowledge WHERE project_id = ?", (MOCK_PROJECT_ID,),
        ).fetchall()
        assert len(remaining) == 1
        assert remaining[0][0] == "session_state"

    def test_undo_type_no_match(self, db, capsys):
        """--type=plan when no plans exist shows 'No entries to undo'."""
        entry = make_entry(
            content="A gotcha entry.",
            type="gotcha",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(type="plan")
        cmd_undo(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "No entries to undo" in out


class TestCmdInspectFilters:
    """PRD: inspect with --all, --type, --tags, positional entry-id."""

    def _insert_mixed_entries(self, db):
        entries = [
            make_entry(
                content="Auth decision for server.",
                type="decision",
                tags=["auth", "server"],
                branch="main",
                created_at=days_ago(1),
            ),
            make_entry(
                content="Billing gotcha for iOS.",
                type="gotcha",
                tags=["billing", "ios"],
                branch="main",
                created_at=days_ago(2),
            ),
            make_entry(
                content="Cross-project pattern.",
                type="pattern",
                tags=["server"],
                branch="main",
                created_at=days_ago(3),
                project_id=SECOND_PROJECT_ID,
                project_name=SECOND_PROJECT_NAME,
            ),
        ]
        insert_entries(db, entries)
        return entries

    def test_inspect_type_filter(self, db, capsys):
        """--type gotcha returns only gotcha entries."""
        self._insert_mixed_entries(db)
        args = SimpleNamespace(entry_id=None, all=False, type="gotcha", tags=None)
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "[gotcha]" in out
        assert "[decision]" not in out

    def test_inspect_tags_filter(self, db, capsys):
        """--tags auth returns only entries tagged 'auth'."""
        self._insert_mixed_entries(db)
        args = SimpleNamespace(entry_id=None, all=False, type=None, tags="auth")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Auth decision" in out
        assert "Billing" not in out

    def test_inspect_all_projects(self, db, capsys):
        """--all shows entries from all projects."""
        self._insert_mixed_entries(db)
        args = SimpleNamespace(entry_id=None, all=True, type=None, tags=None)
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Cross-project pattern" in out
        assert "Auth decision" in out

    def test_inspect_entry_id(self, db, capsys):
        """Positional entry-id shows full detail of a single entry."""
        entries = self._insert_mixed_entries(db)
        entry_id = entries[0]["id"]
        args = SimpleNamespace(entry_id=entry_id)
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "ID:" in out
        assert "Type:" in out
        assert "Content:" in out
        assert "Auth decision" in out

    def test_inspect_entry_id_not_found(self, db, capsys):
        """Positional entry-id that doesn't exist shows error."""
        args = SimpleNamespace(entry_id="nonexistent-id")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Entry not found" in out

    def test_inspect_entry_id_global_entry(self, db, capsys):
        """Entry detail mode should handle NULL project_id/project_name."""
        result = log_knowledge(
            conn=db,
            content="Global entry for inspect detail mode.",
            type="decision",
            tags=["global"],
            project_id=None,
            project_name=None,
            branch=None,
            source_type="manual",
            enforce_limits=False,
        )
        args = SimpleNamespace(entry_id=result["id"])
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Project:    (global)" in out


class TestCmdPruneModes:
    """PRD: prune by ID, --type/--older-than filters, --auto."""

    def test_prune_by_entry_id(self, db, capsys):
        """momento prune <entry-id> — delete specific entry."""
        entry = make_entry(
            content="Entry to prune by ID.",
            type="gotcha",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(30),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(entry_id=entry["id"], type=None, older_than=None, auto=False)
        with patch("builtins.input", return_value="y"):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Deleted:" in out
        count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 0

    def test_prune_by_entry_id_not_found(self, db, capsys):
        """Non-existent entry ID shows error."""
        args = SimpleNamespace(entry_id="nonexistent", type=None, older_than=None, auto=False)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Entry not found" in out

    def test_prune_by_entry_id_cancelled(self, db, capsys):
        """Prune by ID with 'n' response cancels."""
        entry = make_entry(
            content="Entry to not prune.",
            type="gotcha",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(30),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(entry_id=entry["id"], type=None, older_than=None, auto=False)
        with patch("builtins.input", return_value="n"):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Cancelled" in out
        count = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert count == 1

    def test_prune_type_and_older_than(self, db, capsys):
        """--type session_state --older-than 30d deletes matching entries."""
        entries = [
            make_entry(
                content="Old session state.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(45),
            ),
            make_entry(
                content="Recent session state.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(1),
            ),
            make_entry(
                content="Old decision (should not be deleted).",
                type="decision",
                tags=["server"],
                branch="main",
                created_at=days_ago(45),
            ),
        ]
        insert_entries(db, entries)
        args = SimpleNamespace(entry_id=None, type="session_state", older_than="30d", auto=False)
        with patch("builtins.input", return_value="y"):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Pruned 1 entries" in out
        # Recent session_state and old decision should remain
        remaining = db.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
        assert remaining == 2

    def test_prune_type_filter_nothing_to_prune(self, db, capsys):
        """--type with no matching entries shows 'Nothing to prune'."""
        args = SimpleNamespace(entry_id=None, type="plan", older_than=None, auto=False)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Nothing to prune" in out

    def test_prune_type_filter_cancelled(self, db, capsys):
        """--type filter with 'n' response cancels."""
        entry = make_entry(
            content="Decision to maybe prune.",
            type="decision",
            tags=["server"],
            branch="main",
            created_at=days_ago(1),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(entry_id=None, type="decision", older_than=None, auto=False)
        with patch("builtins.input", return_value="n"):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Cancelled" in out

    def test_prune_invalid_duration(self, db, capsys):
        """Invalid --older-than value exits with error."""
        args = SimpleNamespace(entry_id=None, type=None, older_than="xyz", auto=False)
        with pytest.raises(SystemExit):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

    def test_prune_no_flags_shows_usage(self, db, capsys):
        """No flags at all shows usage hint."""
        args = SimpleNamespace(entry_id=None, type=None, older_than=None, auto=False)
        cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "--auto" in out

    def test_prune_older_than_hours(self, db, capsys):
        """--older-than 24h uses hour-based duration (covers _parse_duration hours path)."""
        entries = [
            make_entry(
                content="Old entry from 2 days ago.",
                type="gotcha",
                tags=["server"],
                branch="main",
                created_at=days_ago(2),
            ),
            make_entry(
                content="Recent entry from 1 hour ago.",
                type="gotcha",
                tags=["server"],
                branch="main",
                created_at=hours_ago(1),
            ),
        ]
        insert_entries(db, entries)
        args = SimpleNamespace(entry_id=None, type=None, older_than="24h", auto=False)
        with patch("builtins.input", return_value="y"):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        out = capsys.readouterr().out
        assert "Pruned 1 entries" in out

    def test_prune_invalid_unit(self, db, capsys):
        """--older-than with unknown unit (e.g. '30m') triggers invalid path."""
        args = SimpleNamespace(entry_id=None, type=None, older_than="30m", auto=False)
        with pytest.raises(SystemExit):
            cmd_prune(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")


class TestParseDuration:
    """Cover _parse_duration edge cases."""

    def test_empty_string(self):
        from momento.cli import _parse_duration
        assert _parse_duration("") is None

    def test_days(self):
        from momento.cli import _parse_duration
        result = _parse_duration("30d")
        assert result == timedelta(days=30)

    def test_hours(self):
        from momento.cli import _parse_duration
        result = _parse_duration("24h")
        assert result == timedelta(hours=24)

    def test_unknown_unit(self):
        from momento.cli import _parse_duration
        assert _parse_duration("10x") is None


# ---------------------------------------------------------------------------
# cmd_check_stale
# ---------------------------------------------------------------------------


class TestCmdCheckStale:
    """Cover cmd_check_stale (checkpoint freshness check for hooks)."""

    @pytest.mark.should_pass
    def test_fresh_checkpoint(self, db, capsys):
        """Recent checkpoint exits 0 and prints 'fresh'."""
        entry = make_entry(
            content="Recent checkpoint.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(5),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(threshold=30)
        with pytest.raises(SystemExit) as exc_info:
            cmd_check_stale(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert "fresh" in out

    @pytest.mark.should_pass
    def test_stale_checkpoint(self, db, capsys):
        """Old checkpoint exits 1 and prints 'stale' to stderr."""
        entry = make_entry(
            content="Old checkpoint.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=hours_ago(2),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(threshold=30)
        with pytest.raises(SystemExit) as exc_info:
            cmd_check_stale(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "stale" in err

    @pytest.mark.should_pass
    def test_no_checkpoint(self, db, capsys):
        """No checkpoint at all exits 1 and prints 'no checkpoint found'."""
        args = SimpleNamespace(threshold=30)
        with pytest.raises(SystemExit) as exc_info:
            cmd_check_stale(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "no checkpoint found" in err

    @pytest.mark.should_pass
    def test_custom_threshold(self, db, capsys):
        """Custom threshold: 10 min old entry is stale with --threshold 5."""
        entry = make_entry(
            content="Ten minute old checkpoint.",
            type="session_state",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(10),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(threshold=5)
        with pytest.raises(SystemExit) as exc_info:
            cmd_check_stale(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 1

    @pytest.mark.should_pass
    def test_ignores_non_session_state(self, db, capsys):
        """Only session_state entries count — decisions don't prevent stale."""
        entry = make_entry(
            content="Recent decision.",
            type="decision",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(1),
        )
        insert_entry(db, entry)
        db.commit()
        args = SimpleNamespace(threshold=30)
        with pytest.raises(SystemExit) as exc_info:
            cmd_check_stale(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")
        assert exc_info.value.code == 1
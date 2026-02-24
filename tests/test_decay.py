# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for knowledge decay / freshness-based sorting (TD.1–TD.10).

Verifies that last_retrieved_at drives freshness, restore mode refreshes
entries, search/inspect are read-only, tier ordering is preserved, and
CLI output reflects decay state.

Uses fixtures from conftest.py and factories from mock_data.py.
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from momento.models import Entry
from momento.retrieve import retrieve_context, _sort_entries, _freshness
from tests.conftest import insert_entry, insert_entries
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_entry,
    hours_ago,
    days_ago,
)


# ---------------------------------------------------------------------------
# TD.1 — Freshness replaces created_at in sort
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD1FreshnessReplacesCreatedAt:
    """TD.1 — Entry A (old but recently retrieved) outranks Entry B (newer, never retrieved).

    Entry A: created 30d ago, last_retrieved_at = yesterday.
    Entry B: created 2d ago, never retrieved (last_retrieved_at = NULL).
    Same tier (decision), same surface, same branch.
    A should rank above B because its freshness (yesterday) beats B's freshness (2d ago).
    """

    def test_recently_retrieved_ranks_higher(self, db):
        """A old entry retrieved yesterday beats a 2d-old entry never retrieved."""
        entry_a = make_entry(
            content="Decided on PostgreSQL for billing data — ACID required for financial records.",
            type="decision",
            tags=["server", "database"],
            branch="main",
            surface="server",
            created_at=days_ago(30),
        )
        entry_b = make_entry(
            content="Decided on Redis for session cache — sub-ms latency requirement.",
            type="decision",
            tags=["server", "cache"],
            branch="main",
            surface="server",
            created_at=days_ago(2),
        )
        insert_entries(db, [entry_a, entry_b])

        # Set last_retrieved_at on entry A to yesterday
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (hours_ago(24), entry_a["id"]),
        )
        db.commit()

        # Build stats dict as _restore_mode would
        stats = {entry_a["id"]: hours_ago(24)}  # B has no stats → NULL

        # Convert to Entry objects
        rows = db.execute(
            "SELECT id, content, content_hash, type, tags, project_id, "
            "project_name, branch, source_type, confidence, created_at, updated_at "
            "FROM knowledge WHERE project_id = ? AND type = 'decision' "
            "ORDER BY created_at DESC",
            (MOCK_PROJECT_ID,),
        ).fetchall()
        entries = [Entry(*r) for r in rows]

        sorted_entries = _sort_entries(entries, surface="server", branch="main", stats=stats)

        # A (freshness=yesterday) should come before B (freshness=2d ago)
        ids = [e.id for e in sorted_entries]
        assert ids.index(entry_a["id"]) < ids.index(entry_b["id"]), (
            "Entry with recent retrieval should rank above never-retrieved entry"
        )

    def test_freshness_function_returns_max(self):
        """_freshness returns MAX(created_at, last_retrieved_at)."""
        old_ts = days_ago(30)
        recent_ts = hours_ago(1)
        entry = Entry(
            id="test-id", content="x", content_hash="h", type="decision",
            tags="[]", project_id=MOCK_PROJECT_ID, project_name=MOCK_PROJECT_NAME,
            branch="main", source_type="manual", confidence=0.9,
            created_at=old_ts, updated_at=old_ts,
        )

        # With stats: freshness = last_retrieved_at (more recent)
        stats = {"test-id": recent_ts}
        assert _freshness(entry, stats) == recent_ts

        # With NULL stats: freshness = created_at
        stats_null = {"test-id": None}
        assert _freshness(entry, stats_null) == old_ts

        # With no stats at all: freshness = created_at
        assert _freshness(entry, {}) == old_ts
        assert _freshness(entry, None) == old_ts


# ---------------------------------------------------------------------------
# TD.2 — NULL last_retrieved_at defaults to created_at
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD2NullLastRetrievedFallback:
    """TD.2 — With no retrieval history, sort by created_at (v0.1 backward compat).

    Two entries with NULL last_retrieved_at, different created_at.
    Should sort by created_at DESC.
    """

    def test_null_last_retrieved_sorts_by_created_at(self, db):
        """Entries with no retrieval history sort by created_at DESC."""
        older = make_entry(
            content="Chose gRPC over REST for internal services — bidirectional streaming needed.",
            type="decision",
            tags=["server", "api"],
            branch="main",
            surface="server",
            created_at=days_ago(5),
        )
        newer = make_entry(
            content="Chose protobuf over JSON for service-to-service — schema enforcement + size.",
            type="decision",
            tags=["server", "serialization"],
            branch="main",
            surface="server",
            created_at=days_ago(1),
        )
        insert_entries(db, [older, newer])

        # No last_retrieved_at set — both NULL
        entries = [Entry(*r) for r in db.execute(
            "SELECT id, content, content_hash, type, tags, project_id, "
            "project_name, branch, source_type, confidence, created_at, updated_at "
            "FROM knowledge WHERE project_id = ? AND type = 'decision'",
            (MOCK_PROJECT_ID,),
        ).fetchall()]

        # Empty stats dict = all NULL
        sorted_entries = _sort_entries(entries, surface="server", branch="main", stats={})
        ids = [e.id for e in sorted_entries]

        assert ids.index(newer["id"]) < ids.index(older["id"]), (
            "With NULL last_retrieved_at, newer created_at should rank first"
        )

    def test_null_stats_backward_compat(self, db):
        """stats=None (v1 DB without column) still works — falls back to created_at."""
        entry = make_entry(
            content="Use feature flags for gradual rollout of billing V2.",
            type="decision",
            tags=["server"],
            branch="main",
            created_at=days_ago(3),
        )
        insert_entries(db, [entry])

        entries = [Entry(*r) for r in db.execute(
            "SELECT id, content, content_hash, type, tags, project_id, "
            "project_name, branch, source_type, confidence, created_at, updated_at "
            "FROM knowledge WHERE id = ?",
            (entry["id"],),
        ).fetchall()]

        sorted_entries = _sort_entries(entries, surface=None, branch="main", stats=None)
        assert len(sorted_entries) == 1
        assert sorted_entries[0].id == entry["id"]


# ---------------------------------------------------------------------------
# TD.3 — Retrieval updates last_retrieved_at
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD3RestoreUpdatesLastRetrieved:
    """TD.3 — Calling retrieve_context in restore mode updates last_retrieved_at.

    After a restore call, all returned entries should have last_retrieved_at
    set in knowledge_stats.
    """

    def test_restore_sets_last_retrieved_at(self, db):
        """Restore mode writes last_retrieved_at for returned entries."""
        entry = make_entry(
            content="Webhook handler refactored to async. Next: add retry logic.",
            type="session_state",
            tags=["server", "webhook"],
            branch="main",
            surface="server",
            created_at=hours_ago(1),
        )
        insert_entries(db, [entry])

        # Verify NULL before restore
        before = db.execute(
            "SELECT last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert before[0] is None, "last_retrieved_at should be NULL before restore"

        # Run restore
        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        # Entry should be in results
        returned_ids = [e.id for e in result.entries]
        assert entry["id"] in returned_ids, "Entry should be returned by restore"

        # Verify last_retrieved_at is now set
        after = db.execute(
            "SELECT last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert after[0] is not None, "last_retrieved_at should be set after restore"

    def test_restore_updates_multiple_entries(self, db):
        """All entries returned by restore get last_retrieved_at updated."""
        entries = [
            make_entry(
                content=f"Session checkpoint {i}: working on billing feature.",
                type="session_state",
                tags=["server"],
                branch="main",
                surface="server",
                created_at=hours_ago(i),
            )
            for i in range(1, 4)
        ]
        insert_entries(db, entries)

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        returned_ids = {e.id for e in result.entries}
        for entry in entries:
            if entry["id"] in returned_ids:
                row = db.execute(
                    "SELECT last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
                    (entry["id"],),
                ).fetchone()
                assert row[0] is not None, (
                    f"Entry {entry['id']} was returned but last_retrieved_at is still NULL"
                )


# ---------------------------------------------------------------------------
# TD.4 — Search does NOT update last_retrieved_at
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD4SearchDoesNotUpdateLastRetrieved:
    """TD.4 — Search mode does NOT update last_retrieved_at.

    Search updates retrieval_count but leaves last_retrieved_at untouched.
    Only restore mode refreshes freshness.
    """

    def test_search_does_not_set_last_retrieved_at(self, db):
        """Search mode leaves last_retrieved_at as NULL."""
        entry = make_entry(
            content="PostgreSQL chosen for billing data — ACID transactions required.",
            type="decision",
            tags=["server", "database", "postgres"],
            branch="main",
            surface="server",
            created_at=hours_ago(2),
        )
        insert_entries(db, [entry])

        # Search for this entry
        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            query="postgres billing database",
        )

        # Entry should be found
        assert len(result.entries) > 0, "Search should find the entry"

        # last_retrieved_at should still be NULL
        row = db.execute(
            "SELECT last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert row[0] is None, (
            "Search mode should NOT update last_retrieved_at"
        )

    def test_search_still_updates_retrieval_count(self, db):
        """Search mode increments retrieval_count (just not last_retrieved_at)."""
        entry = make_entry(
            content="Redis session cache with 15-min TTL for auth tokens.",
            type="decision",
            tags=["server", "cache", "redis"],
            branch="main",
            surface="server",
            created_at=hours_ago(2),
        )
        insert_entries(db, [entry])

        # Check count before
        before = db.execute(
            "SELECT retrieval_count FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()[0]

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            query="redis cache session",
        )

        if result.entries:  # Only check if entry was actually returned
            after = db.execute(
                "SELECT retrieval_count FROM knowledge_stats WHERE entry_id = ?",
                (entry["id"],),
            ).fetchone()[0]
            assert after > before, "Search should increment retrieval_count"


# ---------------------------------------------------------------------------
# TD.5 — Inspect does NOT update last_retrieved_at
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD5InspectDoesNotUpdateLastRetrieved:
    """TD.5 — Inspect is read-only: does not touch knowledge_stats.

    The inspect command queries knowledge directly (with LEFT JOIN to
    knowledge_stats) but never writes to it.
    """

    def test_inspect_list_does_not_modify_stats(self, db):
        """cmd_inspect (list mode) does not write to knowledge_stats."""
        entry = make_entry(
            content="Webhook handler uses idempotency keys to prevent duplicate processing.",
            type="gotcha",
            tags=["server", "webhook"],
            branch="main",
            surface="server",
            created_at=hours_ago(5),
        )
        insert_entries(db, [entry])

        # Snapshot stats before
        before = db.execute(
            "SELECT retrieval_count, last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()

        # Run inspect (list mode)
        from momento.cli import cmd_inspect
        args = SimpleNamespace(entry_id=None, all=False, type=None, tags=None, dir=".")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        # Stats unchanged
        after = db.execute(
            "SELECT retrieval_count, last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert before == after, "Inspect should not modify knowledge_stats"

    def test_inspect_detail_does_not_modify_stats(self, db):
        """cmd_inspect (detail mode, single entry) does not write to knowledge_stats."""
        entry = make_entry(
            content="Always use content-hash dedup to prevent duplicate entries.",
            type="pattern",
            tags=["server", "dedup"],
            branch="main",
            surface="server",
            created_at=hours_ago(3),
        )
        insert_entries(db, [entry])

        before = db.execute(
            "SELECT retrieval_count, last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()

        from momento.cli import cmd_inspect
        args = SimpleNamespace(entry_id=entry["id"], all=False, type=None, tags=None, dir=".")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        after = db.execute(
            "SELECT retrieval_count, last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert before == after, "Inspect detail view should not modify knowledge_stats"


# ---------------------------------------------------------------------------
# TD.6 — Freshness does not cross tiers
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD6FreshnessDoesNotCrossTiers:
    """TD.6 — A very fresh gotcha does not outrank a stale decision.

    Tier ordering (session_state > plan > decision > gotcha/pattern) is
    always preserved regardless of freshness within each tier.
    """

    def test_fresh_gotcha_does_not_outrank_stale_decision(self, db):
        """Tier ordering preserved: decisions before gotchas regardless of freshness."""
        # Stale decision: created 20d ago, never retrieved
        stale_decision = make_entry(
            content="Chose opaque session tokens over JWT — revocation without blocklist.",
            type="decision",
            tags=["server", "auth"],
            branch="main",
            surface="server",
            created_at=days_ago(20),
        )
        # Very fresh gotcha: created just now, retrieved 1h ago
        fresh_gotcha = make_entry(
            content="SQLite PRAGMA busy_timeout must be set per-connection, not per-DB.",
            type="gotcha",
            tags=["server", "sqlite"],
            branch="main",
            surface="server",
            created_at=hours_ago(1),
        )
        insert_entries(db, [stale_decision, fresh_gotcha])

        # Make the gotcha super fresh
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (hours_ago(1), fresh_gotcha["id"]),
        )
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        types = [e.type for e in result.entries]
        if "decision" in types and "gotcha" in types:
            first_decision = types.index("decision")
            first_gotcha = types.index("gotcha")
            assert first_decision < first_gotcha, (
                "Decisions must appear before gotchas regardless of freshness"
            )

    def test_fresh_plan_does_not_outrank_session_state(self, db):
        """Tier ordering: session_state always before plan."""
        stale_session = make_entry(
            content="Working on billing V2 migration. 3 of 7 handlers done.",
            type="session_state",
            tags=["server"],
            branch="main",
            surface="server",
            created_at=hours_ago(6),
        )
        fresh_plan = make_entry(
            content="Phase 1: billing migration. Phase 2: auth overhaul. Phase 3: dashboard.",
            type="plan",
            tags=["server", "roadmap"],
            branch="main",
            surface="server",
            created_at=hours_ago(1),
        )
        insert_entries(db, [stale_session, fresh_plan])

        # Make the plan super fresh
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (hours_ago(0), fresh_plan["id"]),
        )
        db.commit()

        result = retrieve_context(
            db,
            project_id=MOCK_PROJECT_ID,
            branch="main",
            surface="server",
            query=None,
            include_session_state=True,
        )

        types = [e.type for e in result.entries]
        if "session_state" in types and "plan" in types:
            first_session = types.index("session_state")
            first_plan = types.index("plan")
            assert first_session < first_plan, (
                "session_state must appear before plan regardless of freshness"
            )


# ---------------------------------------------------------------------------
# TD.7 — Surface/branch still outrank freshness
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD7SurfaceBranchOutrankFreshness:
    """TD.7 — Within a tier, surface/branch matching beats freshness.

    A stale surface-matching entry beats a fresh non-surface entry
    within the same tier.
    """

    def test_stale_surface_match_beats_fresh_non_surface(self, db):
        """Surface-matching entry ranks above non-surface entry despite worse freshness."""
        # Stale but surface-matching
        stale_surface = make_entry(
            content="Server-side Stripe Checkout chosen for PCI scope reduction.",
            type="decision",
            tags=["server", "stripe"],
            branch="main",
            surface="server",
            created_at=days_ago(15),
        )
        # Fresh but no surface match (ios tagged)
        fresh_no_surface = make_entry(
            content="iOS Keychain wrapper chosen over raw kSecAttrAccount access.",
            type="decision",
            tags=["ios", "keychain"],
            branch="main",
            surface="ios",
            created_at=hours_ago(1),
        )
        insert_entries(db, [stale_surface, fresh_no_surface])

        # Make the non-surface entry super fresh
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (hours_ago(0), fresh_no_surface["id"]),
        )
        db.commit()

        # Build stats for _sort_entries
        stats = {fresh_no_surface["id"]: hours_ago(0)}

        entries = [Entry(*r) for r in db.execute(
            "SELECT id, content, content_hash, type, tags, project_id, "
            "project_name, branch, source_type, confidence, created_at, updated_at "
            "FROM knowledge WHERE project_id = ? AND type = 'decision'",
            (MOCK_PROJECT_ID,),
        ).fetchall()]

        # Sort with surface="server" — stale_surface should win
        sorted_entries = _sort_entries(entries, surface="server", branch="main", stats=stats)
        ids = [e.id for e in sorted_entries]

        assert ids.index(stale_surface["id"]) < ids.index(fresh_no_surface["id"]), (
            "Surface-matching entry should rank above non-surface entry despite worse freshness"
        )

    def test_stale_branch_match_beats_fresh_non_branch(self, db):
        """Branch-matching entry ranks above non-branch entry despite worse freshness."""
        # Stale but branch-matching
        stale_branch = make_entry(
            content="Billing rewrite uses event sourcing for audit trail.",
            type="decision",
            tags=["server"],
            branch="feature/billing-rewrite",
            created_at=days_ago(10),
        )
        # Fresh but different branch
        fresh_other_branch = make_entry(
            content="Auth migration uses gradual rollout with feature flags.",
            type="decision",
            tags=["server"],
            branch="main",
            created_at=hours_ago(1),
        )
        insert_entries(db, [stale_branch, fresh_other_branch])

        # Make the non-matching branch entry super fresh
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (hours_ago(0), fresh_other_branch["id"]),
        )
        db.commit()

        stats = {fresh_other_branch["id"]: hours_ago(0)}

        entries = [Entry(*r) for r in db.execute(
            "SELECT id, content, content_hash, type, tags, project_id, "
            "project_name, branch, source_type, confidence, created_at, updated_at "
            "FROM knowledge WHERE project_id = ? AND type = 'decision'",
            (MOCK_PROJECT_ID,),
        ).fetchall()]

        sorted_entries = _sort_entries(
            entries, surface=None, branch="feature/billing-rewrite", stats=stats,
        )
        ids = [e.id for e in sorted_entries]

        assert ids.index(stale_branch["id"]) < ids.index(fresh_other_branch["id"]), (
            "Branch-matching entry should rank above non-branch entry despite worse freshness"
        )


# ---------------------------------------------------------------------------
# TD.8 — Schema migration v1→v2
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD8SchemaMigrationV1ToV2:
    """TD.8 — Migrating a v1 schema DB adds last_retrieved_at column.

    Creates a v1 schema (without last_retrieved_at), runs migration,
    verifies column exists and existing entries have NULL last_retrieved_at.
    """

    @staticmethod
    def _create_v1_schema(conn: sqlite3.Connection) -> None:
        """Create a v1 schema: knowledge_stats WITHOUT last_retrieved_at."""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('gotcha','decision','pattern','plan','session_state')),
                tags TEXT NOT NULL,
                project_id TEXT,
                project_name TEXT,
                branch TEXT,
                source_type TEXT NOT NULL CHECK(source_type IN ('manual','compaction','error_pair')),
                confidence REAL NOT NULL DEFAULT 0.9,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS knowledge_stats (
                entry_id TEXT PRIMARY KEY REFERENCES knowledge(id) ON DELETE CASCADE,
                retrieval_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS momento_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO momento_meta (key, value) VALUES ('schema_version', '1');

            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                content, tags,
                content=knowledge,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS knowledge_ai AFTER INSERT ON knowledge BEGIN
                INSERT INTO knowledge_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_ad AFTER DELETE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, tags)
                VALUES('delete', old.rowid, old.content, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS knowledge_au AFTER UPDATE ON knowledge BEGIN
                INSERT INTO knowledge_fts(knowledge_fts, rowid, content, tags)
                VALUES('delete', old.rowid, old.content, old.tags);
                INSERT INTO knowledge_fts(rowid, content, tags)
                VALUES (new.rowid, new.content, new.tags);
            END;

            CREATE INDEX IF NOT EXISTS idx_knowledge_project_type
                ON knowledge(project_id, type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_knowledge_type_confidence
                ON knowledge(type, confidence DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_content_hash
                ON knowledge(content_hash, COALESCE(project_id, '__global__'));
        """)

    def test_v1_schema_has_no_last_retrieved_at(self, tmp_path):
        """Verify our v1 schema fixture doesn't have the column."""
        db_path = str(tmp_path / "v1.db")
        conn = sqlite3.connect(db_path)
        self._create_v1_schema(conn)

        cols = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_stats)").fetchall()}
        assert "last_retrieved_at" not in cols, "v1 schema should NOT have last_retrieved_at"
        conn.close()

    def test_migration_adds_column(self, tmp_path):
        """run_migrations(v1) adds last_retrieved_at to knowledge_stats."""
        from momento.db import run_migrations, get_schema_version

        db_path = str(tmp_path / "v1_migrate.db")
        conn = sqlite3.connect(db_path)
        self._create_v1_schema(conn)

        # Verify v1
        version = get_schema_version(conn)
        assert version == 1

        # Run migration
        run_migrations(conn, current_version=1)

        # Column should exist
        cols = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_stats)").fetchall()}
        assert "last_retrieved_at" in cols, "Migration should add last_retrieved_at column"

        # Schema version bumped
        version = get_schema_version(conn)
        assert version == 2

        conn.close()

    def test_existing_entries_have_null_last_retrieved_at(self, tmp_path):
        """Existing stats rows have NULL last_retrieved_at after migration."""
        from momento.db import run_migrations

        db_path = str(tmp_path / "v1_data.db")
        conn = sqlite3.connect(db_path)
        self._create_v1_schema(conn)

        # Insert an entry in v1 schema
        entry = make_entry(
            content="Pre-migration entry for testing.",
            type="decision",
            tags=["server"],
            branch="main",
        )
        conn.execute(
            """INSERT INTO knowledge
               (id, content, content_hash, type, tags, project_id,
                project_name, branch, source_type, confidence,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["id"], entry["content"], entry["content_hash"], entry["type"],
                entry["tags"], entry["project_id"], entry["project_name"],
                entry["branch"], entry["source_type"], entry["confidence"],
                entry["created_at"], entry["updated_at"],
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 3)",
            (entry["id"],),
        )
        conn.commit()

        # Migrate
        run_migrations(conn, current_version=1)

        # Existing row should have NULL last_retrieved_at but preserved retrieval_count
        row = conn.execute(
            "SELECT retrieval_count, last_retrieved_at FROM knowledge_stats WHERE entry_id = ?",
            (entry["id"],),
        ).fetchone()
        assert row[0] == 3, "retrieval_count should be preserved"
        assert row[1] is None, "last_retrieved_at should be NULL after migration"

        conn.close()

    def test_ensure_db_handles_v1_to_v2(self, tmp_path):
        """ensure_db on a v1 database runs the migration automatically."""
        from momento.db import ensure_db, get_schema_version

        db_path = str(tmp_path / "v1_ensure.db")
        conn = sqlite3.connect(db_path)
        self._create_v1_schema(conn)
        conn.close()

        # Re-open via ensure_db — should detect v1 and migrate
        conn = ensure_db(db_path)
        version = get_schema_version(conn)
        assert version == 2

        cols = {row[1] for row in conn.execute("PRAGMA table_info(knowledge_stats)").fetchall()}
        assert "last_retrieved_at" in cols
        conn.close()


# ---------------------------------------------------------------------------
# TD.9 — Decay visibility in inspect
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD9DecayVisibilityInInspect:
    """TD.9 — cmd_inspect output shows decay indicator for old entries.

    Entries with freshness > 21 days show "decaying" indicator.
    """

    def test_decaying_indicator_in_inspect_detail(self, db, capsys):
        """Single-entry inspect shows decay indicator for stale freshness."""
        entry = make_entry(
            content="Webhook idempotency check uses Redis SETNX with 24h TTL.",
            type="gotcha",
            tags=["server", "webhook"],
            branch="main",
            surface="server",
            created_at=days_ago(30),
        )
        insert_entries(db, [entry])

        # Set last_retrieved_at to 25 days ago (> 21d threshold)
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (days_ago(25), entry["id"]),
        )
        db.commit()

        from momento.cli import cmd_inspect
        args = SimpleNamespace(entry_id=entry["id"], all=False, type=None, tags=None, dir=".")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        output = capsys.readouterr().out
        assert "decaying" in output, (
            "Inspect detail should show 'decaying' for entries with freshness > 21d"
        )

    def test_no_decay_indicator_for_fresh_entries(self, db, capsys):
        """Single-entry inspect does NOT show decay indicator for fresh entries."""
        entry = make_entry(
            content="Use database transactions for all payment operations.",
            type="pattern",
            tags=["server", "payments"],
            branch="main",
            surface="server",
            created_at=days_ago(30),
        )
        insert_entries(db, [entry])

        # Set last_retrieved_at to 2 days ago (< 21d threshold → no decay)
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (days_ago(2), entry["id"]),
        )
        db.commit()

        from momento.cli import cmd_inspect
        args = SimpleNamespace(entry_id=entry["id"], all=False, type=None, tags=None, dir=".")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        output = capsys.readouterr().out
        assert "decaying" not in output, (
            "Inspect detail should NOT show 'decaying' for entries with freshness < 21d"
        )

    def test_decaying_indicator_in_inspect_list(self, db, capsys):
        """Inspect list mode shows decay indicator on stale entries."""
        entry = make_entry(
            content="Always verify webhook signatures before processing payloads.",
            type="gotcha",
            tags=["server", "security"],
            branch="main",
            surface="server",
            created_at=days_ago(40),
        )
        insert_entries(db, [entry])

        # Set last_retrieved_at to 25 days ago (> 21d threshold)
        db.execute(
            "UPDATE knowledge_stats SET last_retrieved_at = ? WHERE entry_id = ?",
            (days_ago(25), entry["id"]),
        )
        db.commit()

        from momento.cli import cmd_inspect
        args = SimpleNamespace(entry_id=None, all=False, type=None, tags=None, dir=".")
        cmd_inspect(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

        output = capsys.readouterr().out
        assert "decaying" in output, (
            "Inspect list should show 'decaying' for entries with freshness > 21d"
        )


# ---------------------------------------------------------------------------
# TD.10 — Status shows freshness distribution
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
class TestTD10StatusShowsFreshnessDistribution:
    """TD.10 — cmd_status output includes active/aging/decaying counts.

    Active: ≤7d, Aging: 7–30d, Decaying: >30d (based on freshness).
    """

    def test_status_shows_freshness_buckets(self, db, capsys, tmp_path):
        """Status output contains freshness distribution with correct buckets."""
        import os
        # Create entries in different freshness buckets
        active_entry = make_entry(
            content="Active: working on webhook retry logic right now.",
            type="session_state",
            tags=["server"],
            branch="main",
            surface="server",
            created_at=hours_ago(2),  # 2h ago → active (≤7d)
        )
        aging_entry = make_entry(
            content="Aging: chose PostgreSQL for billing two weeks ago.",
            type="decision",
            tags=["server", "database"],
            branch="main",
            surface="server",
            created_at=days_ago(14),  # 14d ago → aging (7-30d)
        )
        decaying_entry = make_entry(
            content="Decaying: initial project setup notes from last month.",
            type="pattern",
            tags=["server", "setup"],
            branch="main",
            surface="server",
            created_at=days_ago(45),  # 45d ago → decaying (>30d)
        )
        insert_entries(db, [active_entry, aging_entry, decaying_entry])

        # Point MOMENTO_DB to a real file so os.path.getsize works
        db_file = str(tmp_path / "status_test.db")
        with open(db_file, "w") as f:
            f.write("")  # Create empty file for size check
        old_env = os.environ.get("MOMENTO_DB")
        os.environ["MOMENTO_DB"] = db_file

        try:
            from momento.cli import cmd_status
            args = SimpleNamespace(dir=".")
            cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

            output = capsys.readouterr().out

            # Check that freshness section exists
            assert "Freshness:" in output, "Status should include Freshness section"
            assert "Active" in output, "Status should show Active bucket"
            assert "Aging" in output, "Status should show Aging bucket"
            assert "Decaying" in output, "Status should show Decaying bucket"
        finally:
            if old_env is not None:
                os.environ["MOMENTO_DB"] = old_env
            else:
                os.environ.pop("MOMENTO_DB", None)

    def test_status_freshness_counts_are_correct(self, db, capsys, tmp_path):
        """Freshness buckets have correct counts for known entry ages."""
        import os

        # 2 active, 1 aging, 1 decaying
        entries = [
            make_entry(
                content="Active entry 1: current session work.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=hours_ago(1),
            ),
            make_entry(
                content="Active entry 2: working on tests.",
                type="session_state",
                tags=["server"],
                branch="main",
                created_at=days_ago(3),
            ),
            make_entry(
                content="Aging entry: decision made 2 weeks ago.",
                type="decision",
                tags=["server"],
                branch="main",
                created_at=days_ago(14),
            ),
            make_entry(
                content="Decaying entry: old pattern from 2 months ago.",
                type="pattern",
                tags=["server"],
                branch="main",
                created_at=days_ago(60),
            ),
        ]
        insert_entries(db, entries)

        db_file = str(tmp_path / "status_count.db")
        with open(db_file, "w") as f:
            f.write("")
        old_env = os.environ.get("MOMENTO_DB")
        os.environ["MOMENTO_DB"] = db_file

        try:
            from momento.cli import cmd_status
            args = SimpleNamespace(dir=".")
            cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

            output = capsys.readouterr().out

            # Parse counts from output
            # Format: "  Active (≤7d):   N entries"
            assert "2 entries" in output or "  2 " in output, (
                "Should show 2 active entries"
            )
        finally:
            if old_env is not None:
                os.environ["MOMENTO_DB"] = old_env
            else:
                os.environ.pop("MOMENTO_DB", None)

    def test_status_no_freshness_when_empty(self, db, capsys, tmp_path):
        """Status with zero entries does not show Freshness section."""
        import os

        db_file = str(tmp_path / "status_empty.db")
        with open(db_file, "w") as f:
            f.write("")
        old_env = os.environ.get("MOMENTO_DB")
        os.environ["MOMENTO_DB"] = db_file

        try:
            from momento.cli import cmd_status
            args = SimpleNamespace(dir=".")
            cmd_status(args, db, MOCK_PROJECT_ID, MOCK_PROJECT_NAME, "main")

            output = capsys.readouterr().out

            # No entries → no freshness section
            assert "Freshness:" not in output, (
                "Empty project should not show Freshness section"
            )
        finally:
            if old_env is not None:
                os.environ["MOMENTO_DB"] = old_env
            else:
                os.environ.pop("MOMENTO_DB", None)

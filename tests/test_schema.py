"""Tests for schema creation and migration (T2.1–T2.6).

These are RED tests — they will fail because features don't exist yet.
All db functions raise NotImplementedError in their stubs.
"""

import os
import sqlite3

import pytest

from momento.db import ensure_db, run_migrations


# ---------------------------------------------------------------------------
# T2.1 — Fresh DB creation
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_schema_fresh_db_creates_all_tables_and_wal(db_path):
    """T2.1 — Fresh DB creation

    DB must be created with all tables, indexes, triggers, momento_meta,
    schema_version = 1, journal_mode = WAL.
    """
    assert not os.path.exists(db_path), "DB should not exist before ensure_db"

    conn = ensure_db(db_path)

    assert os.path.exists(db_path), "DB file must be created"

    # Check schema_version = 1
    version = conn.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version is not None, "momento_meta must contain schema_version"
    assert int(version[0]) == 1

    # Check WAL mode
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode.lower() == "wal", "Journal mode must be WAL"

    # Check core tables exist
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "knowledge" in tables, "knowledge table must exist"
    assert "momento_meta" in tables, "momento_meta table must exist"
    assert "knowledge_stats" in tables, "knowledge_stats table must exist"

    # Check FTS virtual table exists
    fts_tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%fts%'"
        ).fetchall()
    }
    assert "knowledge_fts" in fts_tables, "knowledge_fts virtual table must exist"

    conn.close()


# ---------------------------------------------------------------------------
# T2.2 — Idempotent creation
# ---------------------------------------------------------------------------


def test_schema_idempotent_creation_no_error(db_path):
    """T2.2 — Idempotent creation

    Calling ensure_db() twice must not error, create duplicate tables,
    or change schema_version.
    """
    conn1 = ensure_db(db_path)
    version1 = conn1.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    conn1.close()

    # Second call — must not raise
    conn2 = ensure_db(db_path)
    version2 = conn2.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()[0]

    assert version1 == version2, "schema_version must not change on second call"

    # Verify no duplicate tables
    table_names = [
        row[0]
        for row in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert len(table_names) == len(set(table_names)), "No duplicate table names"

    conn2.close()


# ---------------------------------------------------------------------------
# T2.3 — DB deleted mid-session
# ---------------------------------------------------------------------------


def test_schema_db_deleted_mid_session_recreates_cleanly(db_path):
    """T2.3 — DB deleted mid-session

    If the DB file is deleted after initial creation, the next ensure_db()
    call must recreate it cleanly.
    """
    conn1 = ensure_db(db_path)
    conn1.close()

    # Simulate deletion mid-session
    os.unlink(db_path)
    # Also remove WAL and SHM files if they exist
    for suffix in ("-wal", "-shm"):
        wal_path = db_path + suffix
        if os.path.exists(wal_path):
            os.unlink(wal_path)

    assert not os.path.exists(db_path), "DB must be deleted"

    # Recreate — must not crash
    conn2 = ensure_db(db_path)

    assert os.path.exists(db_path), "DB must be recreated"

    # Verify schema is intact
    version = conn2.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version is not None
    assert int(version[0]) == 1

    tables = {
        row[0]
        for row in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "knowledge" in tables
    assert "knowledge_fts" in tables

    conn2.close()


# ---------------------------------------------------------------------------
# T2.4 — Partial schema (momento_meta missing)
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_schema_partial_db_missing_momento_meta_migrates(db_path):
    """T2.4 — Partial schema (momento_meta missing)

    If the DB exists with a knowledge table but no momento_meta,
    ensure_db() must treat schema_version as 0, run migrations,
    and create momento_meta with the correct version.
    """
    # Manually create a partial DB: knowledge table only, no momento_meta
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE knowledge (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            type TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            project_id TEXT,
            project_name TEXT,
            branch TEXT,
            source_type TEXT DEFAULT 'manual',
            confidence REAL DEFAULT 0.9,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Now call ensure_db — it should detect partial schema and migrate
    conn = ensure_db(db_path)

    # momento_meta must now exist with correct version
    version = conn.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version is not None, "momento_meta must be created during migration"
    assert int(version[0]) >= 1

    # FTS table and triggers must be created
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "knowledge_fts" in tables, "FTS table must be created by migration"

    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }
    assert "knowledge_ai" in triggers, "Insert trigger must exist after migration"
    assert "knowledge_ad" in triggers, "Delete trigger must exist after migration"
    assert "knowledge_au" in triggers, "Update trigger must exist after migration"

    conn.close()


# ---------------------------------------------------------------------------
# T2.5 — Corrupted DB file
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_schema_corrupted_db_raises_clear_error(db_path):
    """T2.5 — Corrupted DB file

    If the DB file contains non-SQLite data (random bytes), ensure_db()
    must raise a clear error. DB must not be silently overwritten.
    """
    # Write random garbage to the db file
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with open(db_path, "wb") as f:
        f.write(os.urandom(4096))

    original_size = os.path.getsize(db_path)

    # ensure_db must raise an error for corrupted files
    with pytest.raises(Exception) as exc_info:
        ensure_db(db_path)

    # Error message must mention corruption
    error_msg = str(exc_info.value).lower()
    assert "corrupt" in error_msg, (
        f"Error message must mention corruption, got: {exc_info.value}"
    )

    # File must NOT be silently overwritten
    assert os.path.exists(db_path), "Corrupted file must not be deleted"
    assert os.path.getsize(db_path) == original_size, (
        "Corrupted file must not be silently overwritten"
    )


# ---------------------------------------------------------------------------
# T2.6 — FTS5 triggers exist
# ---------------------------------------------------------------------------


@pytest.mark.must_pass
def test_schema_fts5_triggers_exist(db_path):
    """T2.6 — FTS5 triggers exist

    A fresh DB must have knowledge_ai, knowledge_ad, and knowledge_au
    triggers to keep the FTS5 index in sync with the knowledge table.
    """
    conn = ensure_db(db_path)

    triggers = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
    }

    assert "knowledge_ai" in triggers, (
        "AFTER INSERT trigger 'knowledge_ai' must exist"
    )
    assert "knowledge_ad" in triggers, (
        "AFTER DELETE trigger 'knowledge_ad' must exist"
    )
    assert "knowledge_au" in triggers, (
        "AFTER UPDATE trigger 'knowledge_au' must exist"
    )

    conn.close()


def test_run_migrations_noop_when_current_version_is_latest(db_path):
    """run_migrations is a no-op when current_version >= schema version."""
    conn = ensure_db(db_path)
    before = conn.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    run_migrations(conn, 1)
    after = conn.execute(
        "SELECT value FROM momento_meta WHERE key = 'schema_version'"
    ).fetchone()[0]
    assert before == after == "1"
    conn.close()

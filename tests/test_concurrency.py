# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Concurrency tests — T8.1 through T8.3.

Tests for WAL mode, simultaneous writes, and read-during-write isolation.
Uses threading for concurrent operations and tmp_path for DB isolation.
"""

import sqlite3
import threading
import time

import pytest

from momento.db import ensure_db
from momento.store import log_knowledge
from momento.retrieve import retrieve_context
from tests.mock_data import (
    MOCK_PROJECT_ID,
    MOCK_PROJECT_NAME,
    make_entry,
    minutes_ago,
)
from tests.conftest import insert_entry


# ===========================================================================
# T8.1 — WAL mode active
# ===========================================================================

@pytest.mark.must_pass
class TestWALMode:
    """T8.1 — ensure_db creates DB with PRAGMA journal_mode = WAL."""

    def test_wal_mode_active(self, db_path):
        """T8.1: ensure_db creates DB, PRAGMA journal_mode returns 'wal'."""
        conn = ensure_db(db_path)

        cursor = conn.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]

        assert journal_mode.lower() == "wal", (
            f"Expected journal_mode 'wal', got '{journal_mode}'. "
            "WAL mode must be set on DB creation for concurrent access."
        )

    def test_wal_mode_persists_across_connections(self, db_path):
        """T8.1: WAL mode persists in the DB file (not per-connection)."""
        conn1 = ensure_db(db_path)
        conn1.close()

        # Open a fresh connection — WAL should still be active
        conn2 = sqlite3.connect(db_path)
        cursor = conn2.execute("PRAGMA journal_mode")
        journal_mode = cursor.fetchone()[0]
        conn2.close()

        assert journal_mode.lower() == "wal", (
            "WAL mode should persist in the DB file across connections"
        )

    def test_busy_timeout_set(self, db_path):
        """T8.1: busy_timeout is set per-connection (5000ms per PRD)."""
        conn = ensure_db(db_path)

        cursor = conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]

        assert timeout >= 5000, (
            f"Expected busy_timeout >= 5000ms, got {timeout}. "
            "busy_timeout must be set per-connection to handle concurrent writes."
        )


# ===========================================================================
# T8.2 — Simultaneous writes
# ===========================================================================

@pytest.mark.should_pass
class TestSimultaneousWrites:
    """T8.2 — two threads writing log_knowledge, both succeed."""

    def test_two_threads_write_simultaneously(self, db_path):
        """T8.2: two threads writing log_knowledge — both succeed, no corruption."""
        # Initialize the DB first
        conn_init = ensure_db(db_path)
        conn_init.close()

        results = {"thread_1": None, "thread_2": None}
        errors = {"thread_1": None, "thread_2": None}

        def write_entry(thread_name, content, tags):
            try:
                conn = ensure_db(db_path)
                result = log_knowledge(
                    conn=conn,
                    content=content,
                    type="session_state",
                    tags=tags,
                    project_id=MOCK_PROJECT_ID,
                    project_name=MOCK_PROJECT_NAME,
                    branch="main",
                    enforce_limits=True,
                )
                results[thread_name] = result
                conn.close()
            except Exception as e:
                errors[thread_name] = e

        t1 = threading.Thread(
            target=write_entry,
            args=("thread_1", "Thread 1 checkpoint: auth migration.", ["server", "auth"]),
        )
        t2 = threading.Thread(
            target=write_entry,
            args=("thread_2", "Thread 2 checkpoint: billing webhook fix.", ["server", "billing"]),
        )

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Neither thread should have errored
        assert errors["thread_1"] is None, f"Thread 1 failed: {errors['thread_1']}"
        assert errors["thread_2"] is None, f"Thread 2 failed: {errors['thread_2']}"

        # Both writes should have succeeded
        assert results["thread_1"] is not None, "Thread 1 should have a result"
        assert results["thread_2"] is not None, "Thread 2 should have a result"

        # Verify both entries exist in DB
        conn = ensure_db(db_path)
        cursor = conn.execute(
            "SELECT COUNT(*) FROM knowledge WHERE project_id = ?",
            (MOCK_PROJECT_ID,),
        )
        count = cursor.fetchone()[0]
        conn.close()

        assert count == 2, f"Expected 2 entries from 2 threads, got {count}"

    def test_no_corruption_after_concurrent_writes(self, db_path):
        """T8.2: DB integrity check passes after concurrent writes."""
        conn_init = ensure_db(db_path)
        conn_init.close()

        errors = []

        def write_entry(i):
            try:
                conn = ensure_db(db_path)
                log_knowledge(
                    conn=conn,
                    content=f"Concurrent write #{i}: testing WAL isolation.",
                    type="decision",
                    tags=["test", f"thread-{i}"],
                    project_id=MOCK_PROJECT_ID,
                    project_name=MOCK_PROJECT_NAME,
                    branch="main",
                    enforce_limits=True,
                )
                conn.close()
            except Exception as e:
                errors.append((i, e))

        threads = [threading.Thread(target=write_entry, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert len(errors) == 0, f"Concurrent writes produced errors: {errors}"

        # Run integrity check
        conn = sqlite3.connect(db_path)
        cursor = conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()[0]
        conn.close()

        assert result == "ok", f"DB integrity check failed: {result}"


# ===========================================================================
# T8.3 — Read during write
# ===========================================================================

class TestReadDuringWrite:
    """T8.3 — one thread writing, another reading, no blocking."""

    def test_read_not_blocked_by_write(self, db_path):
        """T8.3: reader gets consistent snapshot while writer is active."""
        # Initialize DB with some data
        conn_init = ensure_db(db_path)
        entry = make_entry(
            content="Pre-existing entry for read test.",
            type="decision",
            tags=["server"],
            branch="main",
            created_at=minutes_ago(60),
        )
        insert_entry(conn_init, entry)
        conn_init.commit()
        conn_init.close()

        read_result = {"data": None, "error": None}
        write_result = {"error": None}
        read_started = threading.Event()
        write_started = threading.Event()

        def writer():
            try:
                conn = ensure_db(db_path)
                write_started.set()
                # Write while reader is active
                log_knowledge(
                    conn=conn,
                    content="New entry written during concurrent read.",
                    type="session_state",
                    tags=["server", "concurrent"],
                    project_id=MOCK_PROJECT_ID,
                    project_name=MOCK_PROJECT_NAME,
                    branch="main",
                    enforce_limits=True,
                )
                conn.close()
            except Exception as e:
                write_result["error"] = e

        def reader():
            try:
                conn = ensure_db(db_path)
                read_started.set()
                # Wait for write to start
                write_started.wait(timeout=5)
                # Small delay to ensure write is in progress
                time.sleep(0.05)

                result = retrieve_context(
                    conn=conn,
                    project_id=MOCK_PROJECT_ID,
                    branch="main",
                    surface="server",
                    include_session_state=True,
                )
                read_result["data"] = result
                conn.close()
            except Exception as e:
                read_result["error"] = e

        t_writer = threading.Thread(target=writer)
        t_reader = threading.Thread(target=reader)

        t_reader.start()
        read_started.wait(timeout=5)
        t_writer.start()

        t_writer.join(timeout=10)
        t_reader.join(timeout=10)

        # Neither should have errored
        assert read_result["error"] is None, f"Reader failed: {read_result['error']}"
        assert write_result["error"] is None, f"Writer failed: {write_result['error']}"

        # Reader should have gotten a result (either with or without the new entry —
        # WAL provides snapshot isolation, so it's fine either way)
        assert read_result["data"] is not None, "Reader should have received a result"
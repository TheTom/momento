"""Database initialization, schema creation, and migrations."""

import os
import sqlite3

_SCHEMA_VERSION = 1


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, triggers, and momento_meta."""
    conn.executescript("""
        -- knowledge table
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

        -- Stats table
        CREATE TABLE IF NOT EXISTS knowledge_stats (
            entry_id TEXT PRIMARY KEY REFERENCES knowledge(id) ON DELETE CASCADE,
            retrieval_count INTEGER NOT NULL DEFAULT 0
        );

        -- Schema versioning
        CREATE TABLE IF NOT EXISTS momento_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        INSERT OR IGNORE INTO momento_meta (key, value) VALUES ('schema_version', '1');

        -- FTS5 (content-synced)
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
            content, tags,
            content=knowledge,
            content_rowid=rowid
        );

        -- TRIGGERS for content-synced FTS
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

        -- INDEXES
        CREATE INDEX IF NOT EXISTS idx_knowledge_project_type
            ON knowledge(project_id, type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_knowledge_type_confidence
            ON knowledge(type, confidence DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_content_hash
            ON knowledge(content_hash, COALESCE(project_id, '__global__'));
    """)


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Read schema_version from momento_meta. Returns 0 if table missing."""
    try:
        row = conn.execute(
            "SELECT value FROM momento_meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def run_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Run forward-only migrations from current_version to latest."""
    if current_version < 1:
        # v0 -> v1: full schema creation handles everything
        create_schema(conn)


def ensure_db(path: str) -> sqlite3.Connection:
    """Initialize or open the Momento database.

    Creates the database with full schema if it doesn't exist.
    Runs migrations if schema_version is outdated.
    Sets WAL mode and pragmas on first creation.
    Sets busy_timeout per connection.

    Returns an open sqlite3.Connection.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    conn = sqlite3.connect(path)

    # Detect corruption early by probing the file
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1")
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise sqlite3.DatabaseError(
            f"Database file is corrupt or not a valid SQLite database: {path}"
        ) from exc

    # Pragmas
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")

    # Check if knowledge table exists
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'"
    ).fetchone()

    if not table_exists:
        # Fresh DB
        create_schema(conn)
    else:
        # Existing DB — check version and migrate if needed
        version = get_schema_version(conn)
        if version < _SCHEMA_VERSION:
            run_migrations(conn, version)

    return conn

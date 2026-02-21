"""Database initialization, schema creation, and migrations."""

import sqlite3


def ensure_db(path: str) -> sqlite3.Connection:
    """Initialize or open the Momento database.

    Creates the database with full schema if it doesn't exist.
    Runs migrations if schema_version is outdated.
    Sets WAL mode and pragmas on first creation.
    Sets busy_timeout per connection.

    Returns an open sqlite3.Connection.
    """
    raise NotImplementedError("db.ensure_db")


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Read schema_version from momento_meta. Returns 0 if table missing."""
    raise NotImplementedError("db.get_schema_version")


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables, indexes, triggers, and momento_meta."""
    raise NotImplementedError("db.create_schema")


def run_migrations(conn: sqlite3.Connection, current_version: int) -> None:
    """Run forward-only migrations from current_version to latest."""
    raise NotImplementedError("db.run_migrations")

"""Shared fixtures for Momento tests.

All DB operations use tmp_path — never touches the real filesystem.
Fixtures are designed for independence: each test gets a fresh state.
"""

import subprocess
import sqlite3

import pytest


# ---------------------------------------------------------------------------
# Custom markers registration
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line("markers", "must_pass: blocks ship")
    config.addinivalue_line("markers", "should_pass: fix within days")
    config.addinivalue_line("markers", "nice_to_have: v0.1.1")


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Fresh DB path for each test. DB does not exist yet."""
    return str(tmp_path / "test.db")


@pytest.fixture
def db(db_path):
    """Initialized DB connection with full schema.

    Calls ensure_db() to create the database with all tables,
    indexes, triggers, and momento_meta. Connection is closed
    after the test completes.
    """
    from momento.db import ensure_db
    conn = ensure_db(db_path)
    yield conn
    conn.close()


@pytest.fixture
def populated_db(db):
    """DB with the full restore scenario loaded (T4.1).

    Inserts all entries from make_restore_scenario() into the DB.
    Returns the open connection.
    """
    from tests.mock_data import make_restore_scenario

    entries = make_restore_scenario()
    for entry in entries:
        db.execute(
            """INSERT INTO knowledge
               (id, content, content_hash, type, tags, project_id,
                project_name, branch, source_type, confidence,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry["id"],
                entry["content"],
                entry["content_hash"],
                entry["type"],
                entry["tags"],
                entry["project_id"],
                entry["project_name"],
                entry["branch"],
                entry["source_type"],
                entry["confidence"],
                entry["created_at"],
                entry["updated_at"],
            ),
        )
        # Insert stats row
        db.execute(
            "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 0)",
            (entry["id"],),
        )
    db.commit()
    return db


# ---------------------------------------------------------------------------
# Git fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_git_repo(tmp_path):
    """A real git repo with remote and branch for identity tests.

    Creates a minimal git repository with:
    - remote.origin.url = git@github.com:acme/payments-platform.git
    - branch: main
    - one initial commit
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin",
         "git@github.com:acme/payments-platform.git"],
        cwd=repo, capture_output=True, check=True,
    )
    # Configure git user for commits
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )
    # Need at least one commit for branch to exist
    (repo / "README.md").write_text("# Test")
    subprocess.run(
        ["git", "add", "."],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo, capture_output=True, check=True,
    )
    # Ensure we're on main
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture
def mock_git_repo_no_remote(tmp_path):
    """Git repo without a remote (T1.2 fallback test)."""
    repo = tmp_path / "repo_no_remote"
    repo.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo, capture_output=True, check=True,
    )
    (repo / "README.md").write_text("# No Remote")
    subprocess.run(
        ["git", "add", "."],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo, capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=repo, capture_output=True, check=True,
    )
    return repo


@pytest.fixture
def mock_non_git_dir(tmp_path):
    """A directory that is not a git repo (T1.3 fallback test)."""
    non_git = tmp_path / "not_a_repo"
    non_git.mkdir()
    (non_git / "file.txt").write_text("not a repo")
    return non_git


@pytest.fixture
def mock_feature_branch_repo(mock_git_repo):
    """Git repo checked out to feature/billing-rewrite (T1.5)."""
    subprocess.run(
        ["git", "checkout", "-b", "feature/billing-rewrite"],
        cwd=mock_git_repo, capture_output=True, check=True,
    )
    return mock_git_repo


@pytest.fixture
def mock_detached_head_repo(mock_git_repo):
    """Git repo in detached HEAD state (T1.6)."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=mock_git_repo, capture_output=True, text=True, check=True,
    )
    commit_hash = result.stdout.strip()
    subprocess.run(
        ["git", "checkout", commit_hash],
        cwd=mock_git_repo, capture_output=True, check=True,
    )
    return mock_git_repo


# ---------------------------------------------------------------------------
# Helper to insert entries directly (bypass store.py for setup)
# ---------------------------------------------------------------------------

def insert_entry(conn: sqlite3.Connection, entry: dict) -> None:
    """Insert a mock entry directly into the DB. For test setup only."""
    conn.execute(
        """INSERT INTO knowledge
           (id, content, content_hash, type, tags, project_id,
            project_name, branch, source_type, confidence,
            created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry["id"],
            entry["content"],
            entry["content_hash"],
            entry["type"],
            entry["tags"],
            entry["project_id"],
            entry["project_name"],
            entry["branch"],
            entry["source_type"],
            entry["confidence"],
            entry["created_at"],
            entry["updated_at"],
        ),
    )
    conn.execute(
        "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 0)",
        (entry["id"],),
    )


def insert_entries(conn: sqlite3.Connection, entries: list[dict]) -> None:
    """Insert multiple mock entries and commit."""
    for entry in entries:
        insert_entry(conn, entry)
    conn.commit()

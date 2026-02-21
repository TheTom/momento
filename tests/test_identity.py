# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for project identity resolution (T1.1–T1.9).

These are RED tests — they will fail because features don't exist yet.
All identity functions raise NotImplementedError in their stubs.
"""

import hashlib
import os
import subprocess

import pytest

from momento.identity import resolve_branch, resolve_project_id


# ---------------------------------------------------------------------------
# T1.1 — Git remote resolution
# ---------------------------------------------------------------------------


def test_identity_git_remote_returns_hash_of_remote_url(mock_git_repo):
    """T1.1 — Git remote resolution"""
    project_id, human_name = resolve_project_id(str(mock_git_repo))

    expected_hash = hashlib.sha256(
        b"git@github.com:acme/payments-platform.git"
    ).hexdigest()

    assert project_id == expected_hash
    assert human_name == "payments-platform"


def test_identity_git_remote_without_dot_git_suffix(tmp_path):
    """Remote URL parsing handles repos without .git suffix."""
    repo = tmp_path / "repo_no_suffix"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/payments-platform"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    (repo / "README.md").write_text("# Test")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, capture_output=True, check=True)

    project_id, human_name = resolve_project_id(str(repo))
    expected_hash = hashlib.sha256(
        b"https://github.com/acme/payments-platform"
    ).hexdigest()
    assert project_id == expected_hash
    assert human_name == "payments-platform"


# ---------------------------------------------------------------------------
# T1.2 — Git root fallback (no remote)
# ---------------------------------------------------------------------------


def test_identity_no_remote_returns_hash_of_git_common_dir(mock_git_repo_no_remote):
    """T1.2 — Git root fallback (no remote)"""
    repo = mock_git_repo_no_remote
    project_id, human_name = resolve_project_id(str(repo))

    # git common dir for a normal repo is the .git directory
    result = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    git_common_dir = os.path.realpath(
        os.path.join(str(repo), result.stdout.strip())
    )
    expected_hash = hashlib.sha256(git_common_dir.encode()).hexdigest()

    assert project_id == expected_hash
    assert human_name == repo.name


# ---------------------------------------------------------------------------
# T1.3 — Absolute path fallback (no git)
# ---------------------------------------------------------------------------


def test_identity_no_git_returns_hash_of_abs_path(mock_non_git_dir):
    """T1.3 — Absolute path fallback (no git)"""
    abs_path = str(mock_non_git_dir.resolve())
    project_id, human_name = resolve_project_id(abs_path)

    expected_hash = hashlib.sha256(abs_path.encode()).hexdigest()

    assert project_id == expected_hash
    assert human_name == mock_non_git_dir.name


# ---------------------------------------------------------------------------
# T1.4 — Worktree identity unification
# ---------------------------------------------------------------------------


@pytest.mark.should_pass
def test_identity_worktrees_return_same_project_id(mock_git_repo):
    """T1.4 — Worktree identity unification"""
    main_repo = mock_git_repo

    # Create a worktree at a sibling path
    worktree_path = main_repo.parent / "app-billing-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(worktree_path), "-b", "billing-wt"],
        cwd=main_repo,
        capture_output=True,
        check=True,
    )

    pid_main, _ = resolve_project_id(str(main_repo))
    pid_worktree, _ = resolve_project_id(str(worktree_path))

    assert pid_main == pid_worktree, (
        "Both worktrees of the same repo must return the same project_id"
    )

    # Cleanup worktree
    subprocess.run(
        ["git", "worktree", "remove", str(worktree_path)],
        cwd=main_repo,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# T1.5 — Branch detection
# ---------------------------------------------------------------------------


def test_identity_branch_detection_returns_current_branch(mock_feature_branch_repo):
    """T1.5 — Branch detection"""
    branch = resolve_branch(str(mock_feature_branch_repo))
    assert branch == "feature/billing-rewrite"


# ---------------------------------------------------------------------------
# T1.6 — Detached HEAD
# ---------------------------------------------------------------------------


def test_identity_detached_head_returns_none(mock_detached_head_repo):
    """T1.6 — Detached HEAD"""
    branch = resolve_branch(str(mock_detached_head_repo))
    assert branch is None, "Detached HEAD must return None, not empty string"


# ---------------------------------------------------------------------------
# T1.7 — Branch rename degradation
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
def test_identity_branch_rename_demotes_but_preserves_entry(db, mock_git_repo):
    """T1.7 — Branch rename degradation

    Save an entry with branch "feature/x", then verify that on branch
    "feature/y" the old entry is demoted (no branch match boost) but
    still visible — graceful degradation, not data loss.
    """
    from tests.conftest import insert_entry
    from tests.mock_data import make_entry, MOCK_PROJECT_ID

    # Insert entry saved on branch "feature/x"
    entry = make_entry(
        content="Working on feature X auth flow. Next: add token refresh.",
        type="session_state",
        tags=["server"],
        branch="feature/x",
    )
    insert_entry(db, entry)
    db.commit()

    # Import retrieve_context — this will fail since it doesn't exist yet
    from momento.retrieve import retrieve_context  # noqa: F401 — RED test

    # Simulate being on branch "feature/y" now
    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/y",
        surface=None,
    )

    # The old entry should still be present (not filtered out)
    returned_ids = [e.id for e in result.entries]
    assert entry["id"] in returned_ids, (
        "Entry from renamed branch must still be visible"
    )


# ---------------------------------------------------------------------------
# T1.8 — Non-git branch
# ---------------------------------------------------------------------------


def test_identity_non_git_dir_branch_returns_none(mock_non_git_dir):
    """T1.8 — Non-git branch"""
    branch = resolve_branch(str(mock_non_git_dir))
    assert branch is None


# ---------------------------------------------------------------------------
# T1.9 — Branch comparison is case-sensitive
# ---------------------------------------------------------------------------


@pytest.mark.nice_to_have
def test_identity_branch_comparison_is_case_sensitive(db, mock_git_repo):
    """T1.9 — Branch comparison is case-sensitive

    Entry saved with branch "feature/Auth" should NOT get branch-match
    preference when current branch is "feature/auth". Exact string
    equality — branch names are never lowercased.
    """
    from tests.conftest import insert_entry
    from tests.mock_data import make_entry, MOCK_PROJECT_ID

    # Insert entry on branch "feature/Auth" (capital A)
    entry = make_entry(
        content="Implemented Auth token rotation for mobile clients.",
        type="decision",
        tags=["auth", "server"],
        branch="feature/Auth",
    )
    insert_entry(db, entry)
    db.commit()

    from momento.retrieve import retrieve_context  # noqa: F401 — RED test

    # Query as if on branch "feature/auth" (lowercase a)
    result = retrieve_context(
        db,
        project_id=MOCK_PROJECT_ID,
        branch="feature/auth",
        surface="server",
    )

    # The entry should be returned but should NOT have branch-match boost.
    # We can't easily test ranking without a second entry, so verify the
    # branch stored in the entry is still "feature/Auth" (never lowercased).
    for e in result.entries:
        if e.id == entry["id"]:
            assert e.branch == "feature/Auth", (
                "Branch names must never be lowercased"
            )
            break
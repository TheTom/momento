# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Project identity resolution from git and filesystem."""

import hashlib
import os
import subprocess


def resolve_project_id(working_dir: str) -> tuple[str, str]:
    """Resolve project identity from working directory.

    Resolution order:
    1. hash(git remote.origin.url) — survives folder moves
    2. hash(git --git-common-dir) — no remote, local git root
    3. hash(absolute working directory) — not a git repo

    Returns (project_id, human_name).
    """
    # Tier 1: git remote URL (most stable)
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=working_dir, capture_output=True, text=True, check=True,
        )
        remote_url = result.stdout.strip()

        # Derive human_name from the remote URL (repo name)
        human_name = remote_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        if human_name.endswith(".git"):
            human_name = human_name[:-4]

        project_id = hashlib.sha256(remote_url.encode()).hexdigest()
        return (project_id, human_name)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    # Tier 2: git common dir (no remote, local git)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=working_dir, capture_output=True, text=True, check=True,
        )
        common_dir = result.stdout.strip()
        # CRITICAL: resolve relative path from working_dir
        abs_common = os.path.realpath(os.path.join(working_dir, common_dir))

        toplevel = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=working_dir, capture_output=True, text=True, check=True,
        )
        human_name = os.path.basename(toplevel.stdout.strip())

        project_id = hashlib.sha256(abs_common.encode()).hexdigest()
        return (project_id, human_name)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        pass

    # Tier 3: absolute path (not a git repo)
    abs_path = os.path.abspath(working_dir)
    human_name = os.path.basename(abs_path)
    project_id = hashlib.sha256(abs_path.encode()).hexdigest()
    return (project_id, human_name)


def resolve_branch(working_dir: str) -> str | None:
    """Resolve current git branch.

    Returns branch name string, or None for detached HEAD / non-git.
    Branch names are case-sensitive — never lowercased.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=working_dir, capture_output=True, text=True, check=True,
        )
        branch = result.stdout.strip()
        return branch if branch else None  # empty = detached HEAD
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None  # not a git repo
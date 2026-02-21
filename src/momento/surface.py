# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Surface detection from working directory structure.

Surface is a fixed hint derived from cwd path segments:
- server/backend -> server
- web/frontend -> web
- ios -> ios
- android -> android
"""

import subprocess
from pathlib import Path


def _resolve_git_root(cwd: str) -> str | None:
    """Resolve the git repository root for the given directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd, capture_output=True, text=True, check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def derive_surface(cwd: str, git_root: str) -> str | None:
    """Derive surface from mapped directory segments under git root.

    Rules:
    - Only mapped directory names are recognized.
    - Matching is case-insensitive and segment-boundary aware.
    - If no mapped segment is present, return None.

    Surface is a preference signal, never a filter.
    """
    cwd_path = Path(cwd).resolve()
    root_path = Path(git_root).resolve()

    try:
        relative = cwd_path.relative_to(root_path)
    except ValueError:
        return None  # Not inside project (safety fallback)

    parts = [p.lower() for p in relative.parts]
    if not parts:
        return None

    mapping = {
        "server": "server",
        "backend": "server",
        "web": "web",
        "frontend": "web",
        "ios": "ios",
        "android": "android",
    }
    for segment in parts:
        if segment.startswith("."):
            continue
        if segment in mapping:
            return mapping[segment]
    return None


def detect_surface(cwd: str) -> str | None:
    """Detect development surface from current working directory.

    Resolves git root automatically, then scans path segments for
    recognized surface keywords (server/backend, web/frontend, ios,
    android). Returns the mapped surface name or None.

    Returns lowercased surface string or None.
    """
    if not cwd or cwd == "/":
        return None

    git_root = _resolve_git_root(cwd)
    if git_root is None:
        return None  # Not a git repo — no surface

    return derive_surface(cwd, git_root)
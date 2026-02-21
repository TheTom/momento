"""Knowledge storage — the write path."""

import sqlite3


def log_knowledge(
    conn: sqlite3.Connection,
    content: str,
    type: str,
    tags: list[str],
    project_id: str,
    project_name: str,
    branch: str | None = None,
    source_type: str = "manual",
    confidence: float = 0.9,
    enforce_limits: bool = True,
) -> dict:
    """Store a knowledge entry.

    Validates content size (if enforce_limits=True), normalizes tags,
    computes content_hash for dedup, inserts in a transaction.

    Returns the created entry dict, or error dict on validation failure.
    """
    raise NotImplementedError("store.log_knowledge")

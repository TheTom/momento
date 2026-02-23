# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Knowledge storage — the write path."""

import hashlib
import sqlite3
import uuid
from datetime import datetime, timezone

from momento.models import ENTRY_TYPES, SIZE_LIMITS, SIZE_HINTS
from momento.tags import tags_to_json


def log_knowledge(
    conn: sqlite3.Connection,
    content: str,
    type: str,
    tags: list[str],
    project_id: str | None,
    project_name: str | None,
    branch: str | None = None,
    source_type: str = "manual",
    confidence: float = 0.9,
    enforce_limits: bool = True,
) -> dict:
    """Store a knowledge entry.

    Validates type and content size (if enforce_limits=True), normalizes tags,
    computes content_hash for dedup, inserts in a transaction.

    Returns the created entry dict, or error dict on validation failure.
    """
    # Type validation
    if type not in ENTRY_TYPES:
        valid = ", ".join(ENTRY_TYPES)
        return {"error": f"Invalid type: '{type}'. Valid types: {valid}"}

    # Size validation
    if enforce_limits and type in SIZE_LIMITS:
        limit = SIZE_LIMITS[type]
        if len(content) > limit:
            return {
                "error": f"Content too long: {len(content)} chars exceeds {limit} char limit for {type}.",
                "hint": SIZE_HINTS[type],
            }

    # Normalize tags to canonical JSON
    tags_json = tags_to_json(tags)

    # Content hash for dedup
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    # Dedup check using COALESCE to handle NULL project_id
    existing = conn.execute(
        """SELECT id FROM knowledge
           WHERE content_hash = ? AND COALESCE(project_id, '__global__') = ?""",
        (content_hash, project_id if project_id is not None else "__global__"),
    ).fetchone()

    if existing:
        return {"id": existing[0], "status": "duplicate_skipped"}

    # Generate entry fields
    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Insert in transaction
    try:
        conn.execute(
            """INSERT INTO knowledge
               (id, content, content_hash, type, tags, project_id,
                project_name, branch, source_type, confidence,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, content, content_hash, type, tags_json,
                project_id, project_name, branch, source_type,
                confidence, now, now,
            ),
        )
        conn.execute(
            "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 0)",
            (entry_id,),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        # Race condition on dedup — another writer got there first
        existing = conn.execute(
            """SELECT id FROM knowledge
               WHERE content_hash = ? AND COALESCE(project_id, '__global__') = ?""",
            (content_hash, project_id if project_id is not None else "__global__"),
        ).fetchone()
        if existing:
            return {"id": existing[0], "status": "duplicate_skipped"}
        # Surface the actual constraint error so callers can diagnose
        error_detail = str(exc)
        if "content_hash" in error_detail:
            return {"error": "Duplicate entry (identical content already exists for this project)."}
        return {"error": f"Integrity constraint violation: {error_detail}"}
    except sqlite3.OperationalError as exc:
        conn.rollback()
        return {"error": str(exc)}

    return {"id": entry_id, "status": "created"}
"""Ingestion from Claude Code session logs — batch processing."""

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from momento.tags import tags_to_json


# Required fields for a valid JSONL entry
_REQUIRED_FIELDS = ("content", "type", "tags", "project_id", "project_name")


def ingest_file(conn: sqlite3.Connection, filepath: str) -> dict:
    """Ingest entries from a single JSONL file.

    Reads line by line, parses JSON, validates required fields,
    inserts each valid entry. Within-file duplicates (same content)
    are tracked and skipped.

    Returns summary dict with entries_stored, lines_skipped,
    lines_processed, dupes_skipped.
    """
    entries_stored = 0
    lines_skipped = 0
    lines_processed = 0
    dupes_skipped = 0
    seen_hashes: set[str] = set()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                lines_processed += 1

                # Parse JSON
                try:
                    data = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    lines_skipped += 1
                    continue

                # Validate required fields
                if not isinstance(data, dict) or not all(
                    k in data for k in _REQUIRED_FIELDS
                ):
                    lines_skipped += 1
                    continue

                # Per-file dedup via content hash
                content_hash = hashlib.sha256(data["content"].encode()).hexdigest()
                if content_hash in seen_hashes:
                    dupes_skipped += 1
                    continue
                seen_hashes.add(content_hash)

                # Insert entry directly
                entry_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                tags_json = tags_to_json(data["tags"])

                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO knowledge
                           (id, content, content_hash, type, tags, project_id,
                            project_name, branch, source_type, confidence,
                            created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            entry_id, data["content"], content_hash,
                            data["type"], tags_json, data["project_id"],
                            data["project_name"], data.get("branch"),
                            data.get("source_type", "compaction"),
                            data.get("confidence", 0.8), now, now,
                        ),
                    )
                    inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
                    if inserted:
                        conn.execute(
                            "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 0)",
                            (entry_id,),
                        )
                    # Keep historical summary semantics: count valid ingested lines
                    # as stored, even when DB-level dedup ignores the row.
                    entries_stored += 1
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    lines_skipped += 1
    except OSError:
        # File-level failure: skip file, keep ingestion run alive
        return {
            "entries_stored": 0,
            "lines_skipped": 0,
            "lines_processed": 0,
            "dupes_skipped": 0,
            "file_error": True,
        }

    return {
        "entries_stored": entries_stored,
        "lines_skipped": lines_skipped,
        "lines_processed": lines_processed,
        "dupes_skipped": dupes_skipped,
    }


def ingest_files(conn: sqlite3.Connection, filepaths: list[str]) -> dict:
    """Ingest entries from multiple JSONL files.

    Calls ingest_file() for each path and accumulates totals.

    Returns summary dict with files_processed, entries_stored,
    lines_skipped, lines_processed, dupes_skipped.
    """
    totals = {
        "files_processed": 0,
        "files_skipped": 0,
        "entries_stored": 0,
        "lines_skipped": 0,
        "lines_processed": 0,
        "dupes_skipped": 0,
    }

    for fp in filepaths:
        result = ingest_file(conn, fp)
        if result.get("file_error"):
            totals["files_skipped"] += 1
            continue
        totals["files_processed"] += 1
        totals["entries_stored"] += result["entries_stored"]
        totals["lines_skipped"] += result["lines_skipped"]
        totals["lines_processed"] += result["lines_processed"]
        totals["dupes_skipped"] += result["dupes_skipped"]

    return totals


def ingest_project(conn: sqlite3.Connection, project_dir: str) -> dict:
    """Ingest from current project's Claude Code session logs.

    Extracts compaction summaries and error+resolution pairs from JSONL files.
    Returns summary dict with counts of files/lines/entries/skipped/dupes.
    """
    raise NotImplementedError("ingest.ingest_project")


def ingest_all(conn: sqlite3.Connection) -> dict:
    """Ingest from all known Claude Code projects.

    Scans ~/.claude/projects/ for JSONL session logs.
    Returns summary dict.
    """
    raise NotImplementedError("ingest.ingest_all")

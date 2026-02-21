"""Ingestion from Claude Code session logs — batch processing."""

import sqlite3
from pathlib import Path


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

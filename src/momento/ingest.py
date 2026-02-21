# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Ingestion from Claude Code session logs — batch processing."""

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from momento.tags import tags_to_json


logger = logging.getLogger(__name__)

# Required fields for a valid JSONL entry
_REQUIRED_FIELDS = ("content", "type", "tags", "project_id", "project_name")

# Keyword heuristic: compaction summaries must contain at least one of these
# to be worth persisting. Deliberately simple — filters out fluff.
_INSIGHT_KEYWORDS = frozenset({
    "because", "decided", "must", "avoid", "never", "always", "bug", "race",
    "error", "security", "gotcha", "pattern", "chose", "instead", "tradeoff",
    "constraint", "important", "careful", "warning",
})

# Claude Code projects directory
_CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


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
                if not _is_valid_jsonl_entry(data):
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
                        entries_stored += 1
                    else:
                        dupes_skipped += 1
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


def _is_valid_jsonl_entry(data: dict) -> bool:
    """Validate JSONL entry types before attempting DB insert."""
    if data.get("type") not in {"gotcha", "decision", "pattern", "plan", "session_state"}:
        return False
    if not isinstance(data.get("content"), str) or not data["content"].strip():
        return False
    if not isinstance(data.get("tags"), list) or not all(
        isinstance(t, str) for t in data["tags"]
    ):
        return False
    project_id = data.get("project_id")
    project_name = data.get("project_name")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        return False
    if project_name is not None and (not isinstance(project_name, str) or not project_name.strip()):
        return False
    return True


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


def _encode_project_path(project_dir: str) -> str:
    """Encode a project directory path the way Claude Code does it.

    Claude Code replaces `/` with `-` and prepends `-`.
    E.g. `/Users/tom/myproject` -> `-Users-tom-myproject`
    """
    # Normalize: resolve symlinks, remove trailing slash
    normalized = str(Path(project_dir).resolve())
    # Replace all `/` with `-`, then prepend `-`
    # Since the path starts with `/`, replacing `/` with `-` already gives us
    # a leading `-`, e.g. `/Users/tom` -> `-Users-tom`
    return normalized.replace("/", "-")


def _passes_keyword_filter(content: str) -> bool:
    """Check if content contains at least one insight keyword.

    Deliberately simple heuristic — just checks if any keyword
    appears in the lowercased content string.
    """
    lowered = content.lower()
    return any(kw in lowered for kw in _INSIGHT_KEYWORDS)


def _classify_compaction_type(content: str) -> str:
    """Classify a compaction summary into a Momento entry type.

    Uses simple keyword analysis to pick the best type:
    - "gotcha" if it mentions bugs, errors, race conditions, warnings
    - "decision" if it discusses choices, rationale, tradeoffs
    - "pattern" if it describes conventions or architecture patterns
    - "session_state" as fallback (general progress summary)
    """
    lowered = content.lower()

    # Check for gotcha signals first (errors, warnings, pitfalls)
    gotcha_signals = {"bug", "race", "error", "gotcha", "warning", "careful",
                      "never", "avoid", "security"}
    if any(s in lowered for s in gotcha_signals):
        return "gotcha"

    # Check for decision signals
    decision_signals = {"decided", "chose", "instead", "tradeoff", "because",
                        "constraint", "rationale", "rejected"}
    if any(s in lowered for s in decision_signals):
        return "decision"

    # Check for pattern signals
    pattern_signals = {"pattern", "always", "convention", "must", "architecture"}
    if any(s in lowered for s in pattern_signals):
        return "pattern"

    # Default: session_state (general progress)
    return "session_state"


def _extract_entries_from_session(filepath: str, project_id: str,
                                   project_name: str) -> list[dict]:
    """Extract compaction summaries and error+resolution pairs from a raw
    Claude Code session JSONL file.

    Returns list of Momento-compatible entry dicts ready for DB insertion.

    Entry extraction strategy:
    1. Compaction summaries: entries with `isCompactSummary: true` — these are
       user messages that contain the compacted conversation summary. Filter
       with keyword heuristic to keep only insightful content.
    2. Error+resolution pairs: tool results with `is_error: true` followed by
       a successful assistant response — indicates a problem that was solved.
    """
    entries = []
    seen_hashes: set[str] = set()

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []

    # First pass: extract compaction summaries
    for raw_line in lines:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            continue

        # Compaction summary: isCompactSummary flag on user messages
        if data.get("isCompactSummary"):
            msg = data.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                # Apply keyword heuristic filter
                if _passes_keyword_filter(content):
                    content_hash = hashlib.sha256(content.encode()).hexdigest()
                    if content_hash not in seen_hashes:
                        seen_hashes.add(content_hash)
                        entry_type = _classify_compaction_type(content)
                        entries.append({
                            "content": content,
                            "type": entry_type,
                            "tags": ["compaction"],
                            "project_id": project_id,
                            "project_name": project_name,
                            "branch": data.get("gitBranch"),
                            "source_type": "compaction",
                            "confidence": 0.8,
                        })

    # Second pass: extract error+resolution pairs
    # Look for user messages containing is_error tool_results, then find
    # the next assistant message as the resolution
    for i, raw_line in enumerate(lines):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            data = json.loads(raw_line)
        except (json.JSONDecodeError, ValueError):
            continue

        if data.get("type") != "user":
            continue

        msg = data.get("message", {})
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue

        # Check for is_error tool results in this user message
        error_text = None
        for block in content:
            if isinstance(block, dict) and block.get("is_error") and block.get("content"):
                error_text = block["content"]
                break

        if not error_text:
            continue

        # Look forward for the next assistant message with a text response
        # (the resolution)
        resolution_text = None
        for j in range(i + 1, min(i + 20, len(lines))):
            fwd_line = lines[j].strip()
            if not fwd_line:
                continue
            try:
                fwd_data = json.loads(fwd_line)
            except (json.JSONDecodeError, ValueError):
                continue

            if fwd_data.get("type") != "assistant":
                continue

            fwd_msg = fwd_data.get("message", {})
            fwd_content = fwd_msg.get("content", "")

            # Assistant content can be string or list of blocks
            if isinstance(fwd_content, str) and fwd_content.strip():
                resolution_text = fwd_content.strip()
                break
            elif isinstance(fwd_content, list):
                for block in fwd_content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text:
                            resolution_text = text
                            break
                if resolution_text:
                    break

        if not resolution_text:
            continue

        # Build the error+resolution entry
        # Truncate to reasonable size for gotcha entries (400 char limit)
        error_preview = error_text[:200]
        resolution_preview = resolution_text[:200]
        combined = f"Error: {error_preview}\nResolution: {resolution_preview}"

        content_hash = hashlib.sha256(combined.encode()).hexdigest()
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            entries.append({
                "content": combined,
                "type": "gotcha",
                "tags": ["error-resolution"],
                "project_id": project_id,
                "project_name": project_name,
                "branch": data.get("gitBranch"),
                "source_type": "error_pair",
                "confidence": 0.7,
            })

    return entries


def _insert_extracted_entry(conn: sqlite3.Connection, entry: dict) -> bool:
    """Insert a single extracted entry into the DB.

    Returns True if inserted, False if skipped (dupe or error).
    """
    content_hash = hashlib.sha256(entry["content"].encode()).hexdigest()
    entry_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tags_json = tags_to_json(entry["tags"])

    try:
        conn.execute(
            """INSERT OR IGNORE INTO knowledge
               (id, content, content_hash, type, tags, project_id,
                project_name, branch, source_type, confidence,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, entry["content"], content_hash,
                entry["type"], tags_json, entry["project_id"],
                entry["project_name"], entry.get("branch"),
                entry.get("source_type", "compaction"),
                entry.get("confidence", 0.8), now, now,
            ),
        )
        inserted = conn.execute("SELECT changes()").fetchone()[0] > 0
        if inserted:
            conn.execute(
                "INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 0)",
                (entry_id,),
            )
        conn.commit()
        return inserted
    except sqlite3.Error:
        conn.rollback()
        return False


def _decode_project_path(encoded_name: str) -> str:
    """Decode a Claude Code encoded project path back to a filesystem path.

    E.g. `-Users-tom-myproject` -> `/Users/tom/myproject`

    This is a best-effort reverse: replace leading `-` with `/`, then
    replace remaining `-` with `/`. Not perfect for paths with real hyphens,
    but sufficient for resolve_project_id which just needs a plausible dir.
    """
    # The encoded name starts with `-` which represents the root `/`
    # Each `-` is a `/` separator
    if encoded_name.startswith("-"):
        return "/" + encoded_name[1:].replace("-", "/")
    return encoded_name.replace("-", "/")


def ingest_project(conn: sqlite3.Connection, project_dir: str) -> dict:
    """Ingest from current project's Claude Code session logs.

    Extracts compaction summaries and error+resolution pairs from JSONL files
    in ~/.claude/projects/{encoded-path}/.

    Args:
        conn: SQLite connection to Momento DB.
        project_dir: Absolute path to the project directory.

    Returns:
        Summary dict with files_processed, files_skipped, entries_stored,
        lines_skipped, lines_processed, dupes_skipped.
    """
    from momento.identity import resolve_project_id

    totals = {
        "files_processed": 0,
        "files_skipped": 0,
        "entries_stored": 0,
        "entries_skipped": 0,
        "lines_processed": 0,
        "lines_skipped": 0,
        "dupes_skipped": 0,
    }

    # Resolve project identity
    try:
        project_id, project_name = resolve_project_id(project_dir)
    except Exception:
        logger.warning("Failed to resolve project identity for %s", project_dir)
        return totals

    # Find the Claude Code project directory
    encoded_path = _encode_project_path(project_dir)
    session_dir = _CLAUDE_PROJECTS_DIR / encoded_path

    if not session_dir.is_dir():
        logger.debug("No Claude Code session dir found: %s", session_dir)
        return totals

    # Process all .jsonl files
    jsonl_files = sorted(session_dir.glob("*.jsonl"))
    if not jsonl_files:
        return totals

    for jsonl_path in jsonl_files:
        try:
            entries = _extract_entries_from_session(
                str(jsonl_path), project_id, project_name
            )
            totals["files_processed"] += 1
            totals["lines_processed"] += len(entries)

            for entry in entries:
                if _insert_extracted_entry(conn, entry):
                    totals["entries_stored"] += 1
                else:
                    totals["dupes_skipped"] += 1
        except Exception:
            # Never crash on bad input — partial failures don't stop the run
            logger.debug("Failed to process %s", jsonl_path, exc_info=True)
            totals["files_skipped"] += 1

    return totals


def ingest_all(conn: sqlite3.Connection) -> dict:
    """Ingest from all known Claude Code projects.

    Scans ~/.claude/projects/ for all subdirectories, decodes each back to a
    project path, and runs extraction on each.

    Returns:
        Summary dict with projects_scanned plus accumulated ingest totals.
    """
    totals = {
        "projects_scanned": 0,
        "files_processed": 0,
        "files_skipped": 0,
        "entries_stored": 0,
        "entries_skipped": 0,
        "lines_processed": 0,
        "lines_skipped": 0,
        "dupes_skipped": 0,
    }

    if not _CLAUDE_PROJECTS_DIR.is_dir():
        return totals

    for subdir in sorted(_CLAUDE_PROJECTS_DIR.iterdir()):
        if not subdir.is_dir():
            continue

        # Check if this directory has any .jsonl files
        jsonl_files = list(subdir.glob("*.jsonl"))
        if not jsonl_files:
            continue

        totals["projects_scanned"] += 1

        # Decode back to a filesystem path for identity resolution
        decoded_path = _decode_project_path(subdir.name)

        try:
            result = ingest_project(conn, decoded_path)
            totals["files_processed"] += result.get("files_processed", 0)
            totals["files_skipped"] += result.get("files_skipped", 0)
            totals["entries_stored"] += result.get("entries_stored", 0)
            totals["entries_skipped"] += result.get("entries_skipped", 0)
            totals["lines_processed"] += result.get("lines_processed", 0)
            totals["lines_skipped"] += result.get("lines_skipped", 0)
            totals["dupes_skipped"] += result.get("dupes_skipped", 0)
        except Exception:
            # Never crash — skip this project and continue
            logger.debug("Failed to ingest project %s", decoded_path, exc_info=True)
            totals["files_skipped"] += 1

    return totals
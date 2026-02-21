# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Momento CLI — trust anchors for developers."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from momento.db import ensure_db
from momento.identity import resolve_project_id, resolve_branch
from momento.surface import detect_surface
from momento.store import log_knowledge
from momento.tokens import format_age


# Default DB location
_DEFAULT_DB_DIR = os.path.expanduser("~/.momento")
_DEFAULT_DB_PATH = os.path.join(_DEFAULT_DB_DIR, "knowledge.db")

# Stale checkpoint threshold
_STALE_THRESHOLD = timedelta(hours=1)

# Auto-prune age for session_state
_PRUNE_SESSION_AGE_DAYS = 7


def _get_db_path() -> str:
    """Resolve database path from env or default."""
    return os.environ.get("MOMENTO_DB", _DEFAULT_DB_PATH)


_format_age = format_age  # Backward compat alias for internal callers


def cmd_status(args, conn, project_id, project_name, branch):
    """Show project info, entry counts, last checkpoint, DB size."""
    # Entry counts by type
    cursor = conn.execute(
        "SELECT type, COUNT(*) FROM knowledge WHERE project_id = ? GROUP BY type ORDER BY type",
        (project_id,),
    )
    counts = dict(cursor.fetchall())
    total = sum(counts.values())

    # Last checkpoint
    cursor = conn.execute(
        "SELECT MAX(created_at) FROM knowledge WHERE project_id = ? AND type = 'session_state'",
        (project_id,),
    )
    last_checkpoint = cursor.fetchone()[0]

    # DB size
    db_path = _get_db_path()
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    print(f"Project: {project_name}")
    print(f"Branch:  {branch or '(detached)'}")
    print(f"Entries: {total}")
    for entry_type in ("session_state", "plan", "decision", "gotcha", "pattern"):
        print(f"  {entry_type}: {counts.get(entry_type, 0)}")

    if last_checkpoint:
        age_str = _format_age(last_checkpoint)
        dt = datetime.strptime(last_checkpoint, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        age = datetime.now(timezone.utc) - dt
        stale = " [STALE]" if age > _STALE_THRESHOLD else ""
        print(f"Last checkpoint: {age_str}{stale}")
    else:
        print("Last checkpoint: none")

    print(f"DB size: {db_size:,} bytes")


def cmd_last(args, conn, project_id, project_name, branch):
    """Show the most recent entry for the current project."""
    cursor = conn.execute(
        "SELECT type, content, tags, branch, created_at FROM knowledge "
        "WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    )
    row = cursor.fetchone()
    if not row:
        print("No entries found.")
        return

    entry_type, content, tags_json, entry_branch, created_at = row
    tags = json.loads(tags_json)
    age = _format_age(created_at)
    branch_str = entry_branch or "(none)"
    tag_str = ", ".join(tags) if tags else ""
    print(f"[{entry_type}] {age} ({tag_str}, {branch_str})")
    print(f'"{content}"')


def cmd_save(args, conn, project_id, project_name, branch):
    """Save a session_state entry."""
    content = args.content
    tags = args.tags.split(",") if args.tags else []

    # Auto-detect surface from cwd unless explicitly provided
    surface = args.surface or detect_surface(os.path.abspath(args.dir))
    if surface and surface not in tags:
        tags.insert(0, surface)

    result = log_knowledge(
        conn=conn,
        content=content,
        type="session_state",
        tags=tags,
        project_id=project_id,
        project_name=project_name,
        branch=branch,
        source_type="manual",
        enforce_limits=True,
    )

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        if "hint" in result:
            print(f"Hint: {result['hint']}", file=sys.stderr)
        sys.exit(1)
    elif result.get("status") == "duplicate_skipped":
        print("Duplicate entry — skipped.")
    else:
        print(f"Saved: {result['id']}")


def cmd_log(args, conn, project_id, project_name, branch):
    """Log a knowledge entry of any type."""
    result = log_knowledge(
        conn=conn,
        content=args.content,
        type=args.type,
        tags=args.tags.split(",") if args.tags else [],
        project_id=project_id,
        project_name=project_name,
        branch=branch,
        source_type="manual",
        enforce_limits=False,
    )

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)
    elif result.get("status") == "duplicate_skipped":
        print("Duplicate entry — skipped.")
    else:
        print(f"Logged: {result['id']}")


def cmd_undo(args, conn, project_id, project_name, branch):
    """Delete most recent entry from current project (with confirmation).

    Supports --type to target a specific entry type.
    """
    type_filter = getattr(args, "type", None)
    if type_filter:
        cursor = conn.execute(
            "SELECT id, content, type, created_at FROM knowledge "
            "WHERE project_id = ? AND type = ? ORDER BY created_at DESC LIMIT 1",
            (project_id, type_filter),
        )
    else:
        cursor = conn.execute(
            "SELECT id, content, type, created_at FROM knowledge "
            "WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
            (project_id,),
        )
    row = cursor.fetchone()
    if not row:
        print("No entries to undo.")
        return

    entry_id, content, entry_type, created_at = row
    preview = content[:80] + "..." if len(content) > 80 else content
    print(f"Most recent [{entry_type}] ({_format_age(created_at)}):")
    print(f"  {preview}")
    print()

    confirm = input("Delete this entry? [y/N] ").strip().lower()
    if confirm in ("y", "yes"):
        conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
        conn.commit()
        print(f"Deleted: {entry_id}")
    else:
        print("Cancelled.")


def cmd_inspect(args, conn, project_id, project_name, branch):
    """List entries with type, branch, tags, age, content preview.

    Supports: --all (all projects), --type (filter), --tags (filter),
    positional entry_id (single entry detail).
    """
    entry_id = getattr(args, "entry_id", None)
    if entry_id:
        cursor = conn.execute(
            "SELECT id, type, branch, tags, created_at, content, project_id, project_name, "
            "source_type, confidence FROM knowledge WHERE id = ?",
            (entry_id,),
        )
        row = cursor.fetchone()
        if not row:
            print(f"Entry not found: {entry_id}")
            return
        eid, etype, ebranch, etags_json, ecreated, econtent, epid, epname, esrc, econf = row
        etags = json.loads(etags_json)
        project_label = f"{epname} ({epid[:12]}...)" if epid else "(global)"
        print(f"ID:         {eid}")
        print(f"Type:       {etype}")
        print(f"Project:    {project_label}")
        print(f"Branch:     {ebranch or '(none)'}")
        print(f"Tags:       {', '.join(etags) if etags else '(none)'}")
        print(f"Source:     {esrc}")
        print(f"Confidence: {econf}")
        print(f"Created:    {ecreated} ({_format_age(ecreated)})")
        print(f"Content:\n{econtent}")
        return

    # Build query with optional filters
    show_all = getattr(args, "all", False)
    type_filter = getattr(args, "type", None)
    tags_filter = getattr(args, "tags", None)

    conditions = []
    params = []
    if not show_all:
        conditions.append("project_id = ?")
        params.append(project_id)
    if type_filter:
        conditions.append("type = ?")
        params.append(type_filter)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    cursor = conn.execute(
        f"SELECT type, branch, tags, created_at, content FROM knowledge "
        f"{where} ORDER BY created_at DESC",
        params,
    )
    rows = cursor.fetchall()

    # Post-filter by tag (SQLite JSON filtering is messy, simpler in Python)
    if tags_filter:
        rows = [
            r for r in rows
            if tags_filter.lower() in [t.lower() for t in json.loads(r[2])]
        ]

    if not rows:
        print("No entries found.")
        return

    for row in rows:
        entry_type, entry_branch, tags_json, created_at, content = row
        tags = json.loads(tags_json)
        age = _format_age(created_at)
        preview = content[:60] + "..." if len(content) > 60 else content
        branch_str = entry_branch or "(none)"
        print(f"[{entry_type}] branch={branch_str} tags={tags} {age}")
        print(f"  {preview}")
        print()


def _parse_duration(duration_str: str) -> timedelta | None:
    """Parse duration string like '30d', '24h' into timedelta. Returns None on failure."""
    if not duration_str:
        return None
    unit = duration_str[-1].lower()
    try:
        value = int(duration_str[:-1])
    except (ValueError, IndexError):
        return None
    if unit == "d":
        return timedelta(days=value)
    if unit == "h":
        return timedelta(hours=value)
    return None


def cmd_prune(args, conn, project_id, project_name, branch):
    """Prune entries: by ID, by type+age, or auto-prune session_state.

    Modes (per PRD Section 12):
    - momento prune <entry-id>         — delete specific entry
    - momento prune --type X --older-than 30d — filter by type and age
    - momento prune --auto             — auto-prune session_state >7d + overflow
    """
    entry_id = getattr(args, "entry_id", None)
    type_filter = getattr(args, "type", None)
    older_than = getattr(args, "older_than", None)

    # Mode 1: delete specific entry by ID
    if entry_id:
        row = conn.execute(
            "SELECT id, type, content FROM knowledge WHERE id = ? AND project_id = ?",
            (entry_id, project_id),
        ).fetchone()
        if not row:
            print(f"Entry not found: {entry_id}")
            return
        preview = row[2][:60] + "..." if len(row[2]) > 60 else row[2]
        print(f"[{row[1]}] {preview}")
        confirm = input("Delete this entry? [y/N] ").strip().lower()
        if confirm in ("y", "yes"):
            conn.execute("DELETE FROM knowledge WHERE id = ?", (entry_id,))
            conn.commit()
            print(f"Deleted: {entry_id}")
        else:
            print("Cancelled.")
        return

    # Mode 2: filter by type and/or older-than
    if type_filter or older_than:
        conditions = ["project_id = ?"]
        params: list = [project_id]
        if type_filter:
            conditions.append("type = ?")
            params.append(type_filter)
        if older_than:
            delta = _parse_duration(older_than)
            if delta is None:
                print(f"Invalid duration: {older_than} (use e.g. 30d, 24h)", file=sys.stderr)
                sys.exit(1)
            cutoff = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
            conditions.append("created_at < ?")
            params.append(cutoff)

        where = " AND ".join(conditions)
        count = conn.execute(
            f"SELECT COUNT(*) FROM knowledge WHERE {where}", params,
        ).fetchone()[0]

        if count == 0:
            print("Nothing to prune.")
            return

        print(f"Will delete {count} entries matching filters.")
        confirm = input("Proceed? [y/N] ").strip().lower()
        if confirm in ("y", "yes"):
            conn.execute(f"DELETE FROM knowledge WHERE {where}", params)
            conn.commit()
            print(f"Pruned {count} entries.")
        else:
            print("Cancelled.")
        return

    # Mode 3: --auto
    if not args.auto:
        print("Use --auto, --type/--older-than filters, or provide an entry ID.")
        return

    old_count = conn.execute(
        "SELECT COUNT(*) FROM knowledge WHERE type = 'session_state' "
        "AND project_id = ? "
        "AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) < julianday('now', ?)",
        (project_id, f"-{_PRUNE_SESSION_AGE_DAYS} days"),
    ).fetchone()[0]

    overflow_count = conn.execute(
        "SELECT COUNT(*) FROM ("
        "  SELECT id FROM knowledge "
        "  WHERE type = 'session_state' AND project_id = ? "
        "    AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) >= julianday('now', '-1 day') "
        "  ORDER BY created_at DESC "
        "  LIMIT -1 OFFSET 5"
        ")",
        (project_id,),
    ).fetchone()[0]
    count = old_count + overflow_count

    if count == 0:
        print("Nothing to prune.")
        return

    conn.execute(
        "DELETE FROM knowledge WHERE type = 'session_state' "
        "AND project_id = ? "
        "AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) < julianday('now', ?)",
        (project_id, f"-{_PRUNE_SESSION_AGE_DAYS} days"),
    )
    conn.execute(
        "DELETE FROM knowledge WHERE id IN ("
        "  SELECT id FROM knowledge "
        "  WHERE type = 'session_state' AND project_id = ? "
        "    AND julianday(replace(replace(created_at, 'T', ' '), 'Z', '')) >= julianday('now', '-1 day') "
        "  ORDER BY created_at DESC "
        "  LIMIT -1 OFFSET 5"
        ")",
        (project_id,),
    )
    conn.commit()
    print(f"Pruned {count} stale session_state entries.")


def cmd_ingest(args, conn, project_id, project_name, branch):
    """Ingest JSONL files or Claude Code session logs.

    Modes:
    - `momento ingest` (no args): ingest current project's session logs
    - `momento ingest --all`: ingest all known Claude Code projects
    - `momento ingest file1.jsonl file2.jsonl`: ingest explicit JSONL files
    """
    from momento.ingest import ingest_file, ingest_files, ingest_project, ingest_all

    if args.ingest_all:
        result = ingest_all(conn)
        # Show projects_scanned for --all mode
        if "projects_scanned" in result:
            print(f"Projects: {result['projects_scanned']}")
    elif args.files:
        result = ingest_files(conn, args.files)
    else:
        # Default: ingest current project's Claude Code session logs
        working_dir = os.path.abspath(args.dir)
        result = ingest_project(conn, working_dir)

    print(f"Files:   {result.get('files_processed', 0)}")
    print(f"Lines:   {result.get('lines_processed', 0)}")
    print(f"Stored:  {result.get('entries_stored', 0)}")
    print(f"Skipped: {result.get('lines_skipped', 0)}")
    print(f"Dupes:   {result.get('dupes_skipped', 0)}")


def cmd_search(args, conn, project_id, project_name, branch):
    """Search knowledge entries via FTS5."""
    from momento.retrieve import retrieve_context

    result = retrieve_context(
        conn=conn,
        project_id=project_id,
        branch=branch,
        query=args.query,
    )

    if not result.entries:
        print("No results found.")
        return

    for entry in result.entries:
        preview = entry.content[:80] + "..." if len(entry.content) > 80 else entry.content
        print(f"[{entry.type}] {preview}")
    print(f"\n{len(result.entries)} results, ~{result.total_tokens} tokens")


def cmd_debug_restore(args, conn, project_id, project_name, branch):
    """Show tier breakdown of restore output."""
    from momento.retrieve import retrieve_context

    surface = args.surface if hasattr(args, "surface") else None

    result = retrieve_context(
        conn=conn,
        project_id=project_id,
        branch=branch,
        surface=surface,
        include_session_state=True,
    )

    # Group by type for tier breakdown
    tiers = {}
    for entry in result.entries:
        tiers.setdefault(entry.type, []).append(entry)

    for tier_type, entries in tiers.items():
        print(f"\n--- {tier_type} ({len(entries)} entries) ---")
        for e in entries:
            preview = e.content[:60] + "..." if len(e.content) > 60 else e.content
            print(f"  [{e.branch or 'none'}] {preview}")

    print(f"\nTotal: {len(result.entries)} entries, ~{result.total_tokens} tokens")
    if result.rendered:
        print(f"\n{result.rendered}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="momento",
        description="Momento — trust anchors for developers",
    )
    parser.add_argument("--db", help="Database path (default: ~/.momento/knowledge.db)")
    parser.add_argument("--dir", default=".", help="Working directory for project detection")

    subparsers = parser.add_subparsers(dest="command")

    # status
    subparsers.add_parser("status", help="Show project status")

    # last
    subparsers.add_parser("last", help="Show most recent entry")

    # save
    save_p = subparsers.add_parser("save", help="Save a session checkpoint")
    save_p.add_argument("content", help="Checkpoint content")
    save_p.add_argument("--tags", help="Comma-separated tags")
    save_p.add_argument("--surface", help="Surface tag (server, ios, web, etc.)")

    # log
    log_p = subparsers.add_parser("log", help="Log a knowledge entry")
    log_p.add_argument("content", help="Entry content")
    log_p.add_argument("--type", required=True, help="Entry type")
    log_p.add_argument("--tags", help="Comma-separated tags")

    # undo
    undo_p = subparsers.add_parser("undo", help="Delete most recent entry")
    undo_p.add_argument("--type", help="Undo most recent entry of this type")

    # inspect
    inspect_p = subparsers.add_parser("inspect", help="List all entries")
    inspect_p.add_argument("entry_id", nargs="?", help="Show single entry detail")
    inspect_p.add_argument("--all", action="store_true", help="Show entries from all projects")
    inspect_p.add_argument("--type", help="Filter by entry type")
    inspect_p.add_argument("--tags", help="Filter by tag")

    # prune
    prune_p = subparsers.add_parser("prune", help="Prune old entries")
    prune_p.add_argument("entry_id", nargs="?", help="Delete specific entry by ID")
    prune_p.add_argument("--auto", action="store_true", help="Auto-prune session_state >7d")
    prune_p.add_argument("--type", help="Filter by entry type")
    prune_p.add_argument("--older-than", dest="older_than", help="Age threshold (e.g. 30d, 24h)")

    # ingest
    ingest_p = subparsers.add_parser("ingest", help="Ingest JSONL files")
    ingest_p.add_argument("files", nargs="*", help="JSONL file paths (optional)")
    ingest_p.add_argument("--all", action="store_true", dest="ingest_all",
                          help="Ingest from all Claude Code projects")

    # search
    search_p = subparsers.add_parser("search", help="Search knowledge")
    search_p.add_argument("query", help="Search query")

    # debug-restore
    debug_p = subparsers.add_parser("debug-restore", help="Show restore tier breakdown")
    debug_p.add_argument("--surface", help="Surface filter")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve project identity
    working_dir = os.path.abspath(args.dir)
    project_id, project_name = resolve_project_id(working_dir)
    branch = resolve_branch(working_dir)

    # Open database
    db_path = args.db or _get_db_path()
    if "MOMENTO_DB" not in os.environ and args.db:
        os.environ["MOMENTO_DB"] = args.db
    conn = ensure_db(db_path)

    # Dispatch
    commands = {
        "status": cmd_status,
        "last": cmd_last,
        "save": cmd_save,
        "log": cmd_log,
        "undo": cmd_undo,
        "inspect": cmd_inspect,
        "prune": cmd_prune,
        "ingest": cmd_ingest,
        "search": cmd_search,
        "debug-restore": cmd_debug_restore,
    }

    try:
        # argparse subcommands guarantee args.command is one of these keys
        handler = commands[args.command]
        handler(args, conn, project_id, project_name, branch)
    finally:
        conn.close()
# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""CLAUDE.md audit — compare durable Momento entries against CLAUDE.md.

Detects gaps both directions: Momento knowledge missing from CLAUDE.md,
and CLAUDE.md references not backed by any Momento entry. Also checks
global adapter health.

No LLM. Keyword overlap only. Deterministic.
"""

import json
import os
import re
import shutil
import sqlite3

from momento.models import (
    AdapterCheck,
    AuditResult,
    Entry,
    FixResult,
    ThresholdReport,
)
from momento.surface import _resolve_git_root
from momento.tokens import format_age


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERLAP_THRESHOLD = 0.3

MATURITY_THRESHOLDS = {
    "total_entries": 10,
    "durable_entries": 4,
    "distinct_types": 2,
    "days_active": 3,
}

DURABLE_TYPES = ("decision", "gotcha", "pattern")

STOPWORDS = {
    "the", "is", "a", "an", "of", "for", "to", "in", "on", "at",
    "and", "or", "but", "not", "with", "from", "by", "as", "it",
    "this", "that", "be", "are", "was", "were", "been", "has",
    "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "must", "shall",
    "if", "then", "else", "when", "where", "how", "what", "which",
    "who", "all", "each", "every", "any", "some", "no", "more",
    "most", "other", "than", "too", "very", "also", "just", "about",
}

CODE_STOPWORDS = {
    "function", "class", "import", "return", "def", "var", "let",
    "const", "true", "false", "none", "null", "self", "str", "int",
    "list", "dict", "type", "value", "name", "data", "file",
}

SECTION_KEYWORDS = {
    "gotcha": ["gotcha", "pitfall", "known issue", "warning", "watch out", "caveat"],
    "decision": ["decision", "architecture", "chose", "rationale", "design"],
    "pattern": ["pattern", "convention", "standard", "workflow", "rule"],
}

FALLBACK_HEADERS = {
    "gotcha": "## Known Gotchas",
    "decision": "## Architecture Decisions",
    "pattern": "## Conventions",
}

ADAPTER_CHECKS = [
    {"name": "Read path (retrieve)", "terms": ["retrieve_context"], "critical": True},
    {"name": "Write path (log)", "terms": ["log_knowledge"], "critical": False},
    {"name": "Output rules", "terms": ["momento", "inline"], "critical": False},
    {"name": "Session start", "terms": ["session start", "start of every session", "start of each session"], "critical": True},
]

# Type → emoji prefix for report rendering
_TYPE_EMOJI = {
    "gotcha": "\u26a0",      # ⚠
    "decision": "\U0001f4cc",  # 📌
    "pattern": "\U0001f4d0",   # 📐
}


# ---------------------------------------------------------------------------
# Term extraction & overlap
# ---------------------------------------------------------------------------

def extract_key_terms(text: str) -> set[str]:
    """Extract significant terms from text. Remove stopwords, keep >=3 chars."""
    tokens = re.findall(r"[a-zA-Z0-9_./:-]+", text.lower())
    return {
        t for t in tokens
        if len(t) >= 3
        and t not in STOPWORDS
        and t not in CODE_STOPWORDS
    }


def compute_overlap(entry_terms: set[str], target_text: str) -> float:
    """What fraction of entry_terms appear in target_text? Returns 0.0-1.0."""
    if not entry_terms:
        return 0.0
    target_lower = target_text.lower()
    found = sum(1 for t in entry_terms if t in target_lower)
    return found / len(entry_terms)


def is_project_identifier(term: str) -> bool:
    """Heuristic: is this a project-specific identifier?"""
    return (
        "." in term           # filenames: client.py, app.py
        or "_" in term        # identifiers: local_theology_bot
        or term.isupper()     # env vars: ANTHROPIC_API_KEY
        or "/" in term         # paths: indexer/app.py
    )


# ---------------------------------------------------------------------------
# Maturity threshold
# ---------------------------------------------------------------------------

def check_maturity(
    conn: sqlite3.Connection,
    project_id: str,
) -> tuple[bool, ThresholdReport]:
    """Check if project has enough data for a meaningful audit."""
    # Total entries
    total = conn.execute(
        "SELECT COUNT(*) FROM knowledge WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]

    # Durable entries (decision + gotcha + pattern)
    durable = conn.execute(
        "SELECT COUNT(*) FROM knowledge WHERE project_id = ? AND type IN ('decision', 'gotcha', 'pattern')",
        (project_id,),
    ).fetchone()[0]

    # Distinct durable types
    distinct = conn.execute(
        "SELECT COUNT(DISTINCT type) FROM knowledge WHERE project_id = ? AND type IN ('decision', 'gotcha', 'pattern')",
        (project_id,),
    ).fetchone()[0]

    # Days with entries
    days = conn.execute(
        "SELECT COUNT(DISTINCT date(created_at)) FROM knowledge WHERE project_id = ?",
        (project_id,),
    ).fetchone()[0]

    passed = (
        total >= MATURITY_THRESHOLDS["total_entries"]
        and durable >= MATURITY_THRESHOLDS["durable_entries"]
        and distinct >= MATURITY_THRESHOLDS["distinct_types"]
        and days >= MATURITY_THRESHOLDS["days_active"]
    )

    report = ThresholdReport(
        total_entries=total,
        durable_entries=durable,
        distinct_types=distinct,
        days_active=days,
        passed=passed,
    )
    return passed, report


# ---------------------------------------------------------------------------
# Missing entries (Momento has, CLAUDE.md doesn't)
# ---------------------------------------------------------------------------

def _fetch_durable_entries(
    conn: sqlite3.Connection,
    project_id: str,
) -> list[Entry]:
    """Fetch all durable entries for a project, oldest first."""
    cursor = conn.execute(
        "SELECT id, content, content_hash, type, tags, project_id, "
        "project_name, branch, source_type, confidence, created_at, updated_at "
        "FROM knowledge WHERE project_id = ? AND type IN ('decision', 'gotcha', 'pattern') "
        "ORDER BY created_at ASC",
        (project_id,),
    )
    entries = []
    for row in cursor.fetchall():
        tags = json.loads(row[4]) if row[4] else []
        entries.append(Entry(
            id=row[0], content=row[1], content_hash=row[2],
            type=row[3], tags=tags, project_id=row[5],
            project_name=row[6], branch=row[7], source_type=row[8],
            confidence=row[9], created_at=row[10], updated_at=row[11],
        ))
    return entries


def find_missing_entries(
    entries: list[Entry],
    claude_md_text: str,
    threshold: float = OVERLAP_THRESHOLD,
) -> list[Entry]:
    """Durable entries with <threshold overlap against CLAUDE.md text."""
    missing = []
    for entry in entries:
        if entry.type not in DURABLE_TYPES:
            continue
        terms = extract_key_terms(entry.content)
        # Include tags in the term set
        for tag in entry.tags:
            tag_lower = tag.lower().strip()
            if len(tag_lower) >= 3:
                terms.add(tag_lower)
        overlap = compute_overlap(terms, claude_md_text)
        if overlap < threshold:
            missing.append(entry)
    return missing


# ---------------------------------------------------------------------------
# Stale references (CLAUDE.md has, Momento doesn't)
# ---------------------------------------------------------------------------

def find_stale_references(
    claude_md_text: str,
    entries: list[Entry],
) -> list[str]:
    """CLAUDE.md identifiers not backed by any Momento entry."""
    # Build a combined text from all entries (content + tags)
    entry_text_parts = []
    for entry in entries:
        entry_text_parts.append(entry.content.lower())
        for tag in entry.tags:
            entry_text_parts.append(tag.lower())
    all_entry_text = " ".join(entry_text_parts)

    # Extract identifiers from CLAUDE.md
    stale = []
    seen = set()
    for line in claude_md_text.splitlines():
        stripped = line.strip()
        # Skip empty lines, pure headers, code fence markers
        if not stripped or stripped.startswith("```"):
            continue
        terms = extract_key_terms(stripped)
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            if is_project_identifier(term) and term not in all_entry_text:
                stale.append(term)

    return sorted(stale)


# ---------------------------------------------------------------------------
# Global adapter checks
# ---------------------------------------------------------------------------

def check_global_adapter(
    global_claude_md_text: str,
) -> list[AdapterCheck]:
    """Check global CLAUDE.md for read path, write path, output rules, session start."""
    results = []
    text_lower = global_claude_md_text.lower()
    for check in ADAPTER_CHECKS:
        # For "Output rules", both terms must be present
        if check["name"] == "Output rules":
            found = all(term.lower() in text_lower for term in check["terms"])
        else:
            found = any(term.lower() in text_lower for term in check["terms"])
        results.append(AdapterCheck(
            name=check["name"],
            found=found,
            critical=check["critical"],
        ))
    return results


# ---------------------------------------------------------------------------
# Fix mode — section detection + apply
# ---------------------------------------------------------------------------

def find_target_section(
    claude_md_lines: list[str],
    entry_type: str,
) -> int | None:
    """Find the line index to insert entries for this type.

    Returns the line index of the last content line in the matching section,
    or None if no matching section found.
    """
    keywords = SECTION_KEYWORDS.get(entry_type, [])
    if not keywords:
        return None

    section_start = None
    section_level = None

    for i, line in enumerate(claude_md_lines):
        stripped = line.strip()
        # Check if this is a markdown header
        header_match = re.match(r"^(#{1,6})\s+(.+)", stripped)
        if header_match:
            level = len(header_match.group(1))
            title = header_match.group(2).lower()
            # Check if this header matches our keywords
            if any(kw in title for kw in keywords):
                section_start = i
                section_level = level
                continue
            # If we already found our section and hit a same/higher level header, stop
            if section_start is not None and level <= section_level:
                return i - 1

    # If we found a section, return the last line of the file
    if section_start is not None:
        return len(claude_md_lines) - 1

    return None


def apply_fix(
    claude_md_path: str,
    missing_entries: list[Entry],
    claude_md_lines: list[str],
    dry_run: bool = False,
) -> FixResult:
    """Append missing entries to CLAUDE.md. Backs up first.

    Groups entries by type, finds target sections, appends.
    Idempotent: checks overlap before appending each entry.
    """
    lines_before = len(claude_md_lines)
    entries_added = 0
    entries_skipped = 0
    sections_created = 0
    backup_path = ""

    # Work on a copy of the lines
    new_lines = list(claude_md_lines)
    current_text = "\n".join(new_lines)

    # Group by type
    by_type: dict[str, list[Entry]] = {}
    for entry in missing_entries:
        by_type.setdefault(entry.type, []).append(entry)

    for entry_type in ("gotcha", "decision", "pattern"):
        type_entries = by_type.get(entry_type, [])
        if not type_entries:
            continue

        # Find or create target section
        insert_idx = find_target_section(new_lines, entry_type)
        if insert_idx is None:
            # Create fallback header at end
            header = FALLBACK_HEADERS[entry_type]
            new_lines.append("")
            new_lines.append(header)
            new_lines.append("")
            insert_idx = len(new_lines) - 1
            sections_created += 1

        # Append entries (idempotent: skip if already covered)
        additions = []
        for entry in type_entries:
            terms = extract_key_terms(entry.content)
            for tag in entry.tags:
                tag_lower = tag.lower().strip()
                if len(tag_lower) >= 3:
                    terms.add(tag_lower)
            overlap = compute_overlap(terms, current_text)
            if overlap >= OVERLAP_THRESHOLD:
                entries_skipped += 1
                continue
            line = f"- {entry.content}"
            additions.append(line)
            entries_added += 1
            # Update current_text so subsequent overlap checks see prior additions
            current_text += "\n" + line

        if additions:
            # Insert after the target index
            for j, addition in enumerate(additions):
                new_lines.insert(insert_idx + 1 + j, addition)

    lines_after = len(new_lines)

    if not dry_run and entries_added > 0:
        # Backup
        backup_path = claude_md_path + ".bak"
        if os.path.exists(claude_md_path):
            shutil.copy2(claude_md_path, backup_path)
        # Write
        with open(claude_md_path, "w") as f:
            f.write("\n".join(new_lines))
            if not new_lines[-1].endswith("\n"):
                f.write("\n")

    return FixResult(
        entries_added=entries_added,
        entries_skipped=entries_skipped,
        sections_created=sections_created,
        backup_path=backup_path,
        lines_before=lines_before,
        lines_after=lines_after,
    )


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_project_claude_md(git_root: str | None, cwd: str) -> str | None:
    """Find the project CLAUDE.md file.

    Search order:
    1. {git_root}/CLAUDE.md
    2. {git_root}/.claude/CLAUDE.md
    3. {cwd}/CLAUDE.md
    """
    candidates = []
    if git_root:
        candidates.append(os.path.join(git_root, "CLAUDE.md"))
        candidates.append(os.path.join(git_root, ".claude", "CLAUDE.md"))
    candidates.append(os.path.join(cwd, "CLAUDE.md"))

    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_report(
    result: AuditResult,
    fix_result: FixResult | None = None,
) -> str:
    """Render the 4-section formatted audit report."""
    lines: list[str] = []

    # Section 1: Missing from CLAUDE.md
    if result.missing_entries:
        lines.append("MISSING FROM CLAUDE.md \u2014 Momento knows, CLAUDE.md doesn't")
        lines.append("\u2500" * 48)
        lines.append("")

        # Group by type
        by_type: dict[str, list[Entry]] = {}
        for entry in result.missing_entries:
            by_type.setdefault(entry.type, []).append(entry)

        for entry_type in ("gotcha", "decision", "pattern"):
            type_entries = by_type.get(entry_type, [])
            if not type_entries:
                continue
            type_label = entry_type.capitalize() + "s" if not entry_type.endswith("s") else entry_type.capitalize()
            if entry_type == "gotcha":
                type_label = "Gotchas"
            lines.append(f"{type_label} ({len(type_entries)} not mentioned):")
            lines.append("")
            emoji = _TYPE_EMOJI.get(entry_type, "")
            for entry in type_entries:
                age = format_age(entry.created_at)
                tag_str = ", ".join(entry.tags) if entry.tags else ""
                lines.append(f"  {emoji} {entry.content}")
                lines.append(f"    (logged {age} \u00b7 tags: {tag_str})")
                lines.append("")

    # Section 2: Stale references
    if result.stale_references:
        lines.append("CLAUDE.md HAS, MOMENTO DOESN'T \u2014 may be stale or undocumented")
        lines.append("\u2500" * 48)
        lines.append("")
        for ref in result.stale_references:
            lines.append(f"  ? CLAUDE.md mentions \"{ref}\" but no Momento entry references it.")
        lines.append("")

    # Section 3: Adapter checks
    if result.adapter_checks:
        lines.append("GLOBAL ~/.claude/CLAUDE.md \u2014 adapter issues")
        lines.append("\u2500" * 48)
        lines.append("")
        for check in result.adapter_checks:
            symbol = "\u2713" if check.found else "\u2717"
            status = "Has" if check.found else "Missing"
            lines.append(f"  {symbol} {status}: {check.name}")
        lines.append("")

    # Section 4: Summary
    lines.append("SUMMARY")
    lines.append("\u2500" * 48)
    lines.append("")
    lines.append(f"  CLAUDE.md coverage: {result.coverage_pct}% of durable Momento knowledge")

    if result.missing_entries:
        # Count by type
        by_type_count: dict[str, int] = {}
        for entry in result.missing_entries:
            by_type_count[entry.type] = by_type_count.get(entry.type, 0) + 1
        gap_parts = [f"{count} {t}s" for t, count in sorted(by_type_count.items())]
        lines.append(f"  Gaps: {', '.join(gap_parts)} not in CLAUDE.md")
    else:
        lines.append("  No gaps found.")

    if result.stale_references:
        lines.append(f"  Stale risk: {len(result.stale_references)} CLAUDE.md items not backed by Momento entries")
    else:
        lines.append("  No stale references detected.")

    critical_missing = [c for c in result.adapter_checks if not c.found and c.critical]
    if critical_missing:
        names = ", ".join(c.name.lower() for c in critical_missing)
        lines.append(f"  Global adapter: missing {names} (critical)")
    elif result.adapter_checks:
        lines.append("  Global adapter: OK")

    # Fix result info
    if fix_result and fix_result.entries_added > 0:
        lines.append("")
        lines.append(f"  Fixed: {fix_result.entries_added} entries added, {fix_result.entries_skipped} skipped (already present)")
        if fix_result.backup_path:
            lines.append(f"  Backed up: CLAUDE.md \u2192 {os.path.basename(fix_result.backup_path)}")
    elif not fix_result:
        lines.append("")
        lines.append("  Run `momento audit-claude-md --fix` to append missing entries.")
        lines.append("  Run `momento audit-claude-md --dry-run` to preview changes.")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def audit_claude_md(
    conn: sqlite3.Connection,
    project_id: str,
    project_name: str,
    project_claude_md_path: str | None,
    global_claude_md_path: str | None,
    fix: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> tuple[AuditResult, FixResult | None]:
    """Run the full audit. Returns structured result + optional fix result."""
    # Fetch durable entries
    durable_entries = _fetch_durable_entries(conn, project_id)
    durable_total = len(durable_entries)

    # Read files
    project_text = ""
    if project_claude_md_path and os.path.isfile(project_claude_md_path):
        with open(project_claude_md_path) as f:
            project_text = f.read()

    global_text = ""
    if global_claude_md_path and os.path.isfile(global_claude_md_path):
        with open(global_claude_md_path) as f:
            global_text = f.read()

    # Combined text for overlap analysis
    combined_text = project_text + "\n" + global_text

    # Find missing entries
    missing = find_missing_entries(durable_entries, combined_text)

    # Coverage
    covered = durable_total - len(missing)
    coverage_pct = round(covered / durable_total * 100) if durable_total > 0 else 100

    # Stale references (only check project CLAUDE.md)
    stale = find_stale_references(project_text, durable_entries) if project_text else []

    # Adapter checks (global CLAUDE.md)
    adapter = check_global_adapter(global_text) if global_text else []

    result = AuditResult(
        project_name=project_name,
        threshold_passed=True,
        threshold_report=None,
        missing_entries=missing,
        stale_references=stale,
        adapter_checks=adapter,
        coverage_pct=coverage_pct,
        durable_total=durable_total,
    )

    # Fix mode
    fix_result = None
    if (fix or dry_run) and missing and project_claude_md_path:
        project_lines = project_text.splitlines() if project_text else []
        fix_result = apply_fix(
            claude_md_path=project_claude_md_path,
            missing_entries=missing,
            claude_md_lines=project_lines,
            dry_run=dry_run,
        )

    return result, fix_result

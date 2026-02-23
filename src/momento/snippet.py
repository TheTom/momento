# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Snippet generation — structured work summaries from knowledge entries."""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from momento.models import Entry


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SnippetMeta:
    """Metadata for a generated snippet."""

    project_name: str
    branch: str | None
    range_start: str
    range_end: str
    range_label: str
    entry_count: int
    empty: bool
    is_weekly: bool = False
    staleness_warning: str = ""


@dataclass
class SnippetSections:
    """Grouped entries for snippet rendering."""

    accomplished: list[Entry] = field(default_factory=list)
    decisions: list[Entry] = field(default_factory=list)
    discovered: list[Entry] = field(default_factory=list)
    in_progress: list[Entry] = field(default_factory=list)
    patterns: list[Entry] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Surface extraction from tags
# ---------------------------------------------------------------------------

_SURFACE_KEYWORDS = {"server", "backend", "web", "frontend", "ios", "android"}
_SURFACE_MAP = {"backend": "server", "frontend": "web"}


def extract_surface(tags) -> str | None:
    """Extract surface hint from tag list."""
    if isinstance(tags, str):
        tags = json.loads(tags)
    for tag in tags:
        if tag in _SURFACE_KEYWORDS:
            return _SURFACE_MAP.get(tag, tag)
    return None


# ---------------------------------------------------------------------------
# Time range resolution
# ---------------------------------------------------------------------------

def resolve_range(
    today: bool = True,
    yesterday: bool = False,
    week: bool = False,
    range_start: str | None = None,
    range_end: str | None = None,
) -> tuple[str, str, str]:
    """Resolve time range arguments to (start_iso, end_iso, label).

    Returns ISO 8601 timestamps and a human-readable label.
    range_end is exclusive (query uses created_at < range_end).
    """
    now = datetime.now(timezone.utc)

    if range_start and range_end:
        start = datetime.strptime(range_start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end = datetime.strptime(range_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_iso = end.strftime("%Y-%m-%dT%H:%M:%SZ")
        # Label shows inclusive dates (end - 1 day)
        label = _range_label(start, end - timedelta(days=1))
        return start_iso, end_iso, label

    if yesterday:
        day = now - timedelta(days=1)
        start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = _day_label(start)
        return (
            start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            label,
        )

    if week:
        start = (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        label = _range_label(start, now)
        return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end_iso, label

    # Default: today
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    label = _day_label(start)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        label,
    )


def _day_label(dt: datetime) -> str:
    """Format a single-day label: 'Friday, Feb 21 2026'."""
    return dt.strftime("%A, %b %-d %Y")


def _range_label(start: datetime, end: datetime) -> str:
    """Format a multi-day label: 'Feb 17-21 2026' or 'Jan 28-Feb 3 2026'."""
    if start.month == end.month and start.year == end.year:
        return f"{start.strftime('%b')} {start.day}-{end.day} {start.year}"
    elif start.year == end.year:
        return f"{start.strftime('%b')} {start.day}-{end.strftime('%b')} {end.day} {start.year}"
    else:
        return f"{start.strftime('%b')} {start.day} {start.year}-{end.strftime('%b')} {end.day} {end.year}"


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

_SELECT_COLS = (
    "id, content, content_hash, type, tags, project_id, "
    "project_name, branch, source_type, confidence, created_at, updated_at"
)


def _row_to_entry(row: tuple) -> Entry:
    """Convert a DB row to an Entry dataclass."""
    return Entry(
        id=row[0], content=row[1], content_hash=row[2], type=row[3],
        tags=row[4], project_id=row[5], project_name=row[6], branch=row[7],
        source_type=row[8], confidence=row[9], created_at=row[10], updated_at=row[11],
    )


def query_entries(
    conn: sqlite3.Connection,
    project_id: str | None,
    range_start: str,
    range_end: str,
    branch: str | None = None,
) -> list[Entry]:
    """Fetch entries for the time range. Pure SQL, no post-processing."""
    conditions = ["created_at >= ?", "created_at < ?"]
    params: list = [range_start, range_end]

    if project_id is not None:
        conditions.append("project_id = ?")
        params.append(project_id)

    if branch is not None:
        conditions.append("branch = ?")
        params.append(branch)

    where = " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM knowledge WHERE {where} ORDER BY type ASC, created_at ASC",
        params,
    ).fetchall()

    return [_row_to_entry(r) for r in rows]


# ---------------------------------------------------------------------------
# Keyword completion detection
# ---------------------------------------------------------------------------

COMPLETION_KEYWORDS = {"done", "completed", "finished", "shipped", "merged", "resolved"}


def is_completed(content: str) -> bool:
    """Check if session_state content signals completion via keyword."""
    content_lower = content.lower()
    for kw in COMPLETION_KEYWORDS:
        if re.search(rf'\b{kw}\b', content_lower):
            return True
    return False


# ---------------------------------------------------------------------------
# Section grouping
# ---------------------------------------------------------------------------

def split_session_states(entries: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """Split session_state entries into accomplished and in-progress.

    Most recent session_state per (surface, branch) key -> in-progress.
    All older ones -> accomplished.
    Keyword override: if content signals completion, always accomplished.
    """
    latest_by_key: dict[tuple[str | None, str | None], Entry] = {}

    for entry in entries:
        key = (extract_surface(entry.tags), entry.branch)
        if key not in latest_by_key or entry.created_at > latest_by_key[key].created_at:
            latest_by_key[key] = entry

    # Keyword override: if the latest entry signals completion, remove from latest
    for key, entry in list(latest_by_key.items()):
        if is_completed(entry.content):
            del latest_by_key[key]

    in_progress_ids = {e.id for e in latest_by_key.values()}

    accomplished = [e for e in entries if e.id not in in_progress_ids]
    in_progress = [e for e in entries if e.id in in_progress_ids]

    return accomplished, in_progress


def group_entries(entries: list[Entry]) -> SnippetSections:
    """Group entries into snippet sections by type + recency heuristic."""
    sections = SnippetSections()

    session_states = [e for e in entries if e.type == "session_state"]

    if session_states:
        accomplished, in_progress = split_session_states(session_states)
        sections.accomplished = accomplished
        sections.in_progress.extend(in_progress)

    for entry in entries:
        if entry.type == "decision":
            sections.decisions.append(entry)
        elif entry.type == "gotcha":
            sections.discovered.append(entry)
        elif entry.type == "pattern":
            sections.patterns.append(entry)
        elif entry.type == "plan":
            sections.in_progress.append(entry)

    return sections


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------

def render_markdown(sections: SnippetSections, meta: SnippetMeta) -> str:
    """Render snippet as markdown."""
    prefix = meta.staleness_warning

    if meta.empty:
        lines = [
            f"# Momento Snippet — {meta.range_label}",
            f"## {meta.project_name}",
            "",
            "No entries found for this time range.",
            "",
            "Tip: Use `momento save` or `log_knowledge()` to capture work in progress.",
        ]
        return prefix + "\n".join(lines) + "\n"

    header = f"# Momento Snippet — {meta.range_label}"
    subheader = f"## {meta.project_name}"
    if meta.branch:
        subheader += f" · {meta.branch}"

    lines = [header, subheader, ""]

    if meta.is_weekly:
        _render_weekly_markdown(sections, meta, lines)
    else:
        _render_daily_markdown(sections, lines)

    return prefix + "\n".join(lines).rstrip() + "\n"


def _render_daily_markdown(sections: SnippetSections, lines: list[str]) -> None:
    """Render daily markdown sections."""
    if sections.accomplished:
        lines.append("### Accomplished")
        for entry in sections.accomplished:
            lines.append(f"- {_first_line(entry.content)}")
        lines.append("")

    if sections.decisions:
        lines.append("### Decisions Made")
        for entry in sections.decisions:
            lines.append(f"- {entry.content}")
        lines.append("")

    if sections.discovered:
        lines.append("### Discovered")
        for entry in sections.discovered:
            lines.append(f"- {entry.content}")
        lines.append("")

    if sections.in_progress:
        lines.append("### Still In Progress")
        for entry in sections.in_progress:
            lines.append(f"- {_first_line(entry.content)}")
        lines.append("")

    if sections.patterns:
        lines.append("### Conventions Established")
        for entry in sections.patterns:
            lines.append(f"- {entry.content}")
        lines.append("")


def _render_weekly_markdown(sections: SnippetSections, meta: SnippetMeta, lines: list[str]) -> None:
    """Render weekly markdown with Key Moments and Progress."""
    # Key Moments: decisions + gotchas with day labels
    key_moments = sorted(
        sections.decisions + sections.discovered,
        key=lambda e: e.created_at,
    )
    if key_moments:
        lines.append("### Key Moments")
        for entry in key_moments:
            day_label = _entry_day_label(entry.created_at)
            summary = _first_line(entry.content)
            lines.append(f"- **{day_label}:** {summary}")
        lines.append("")

    # Progress: in-progress items
    if sections.in_progress:
        lines.append("### Progress")
        for entry in sections.in_progress:
            lines.append(f"- {_first_line(entry.content)}")
        lines.append("")

    # Decisions with date annotations
    if sections.decisions:
        lines.append(f"### Decisions Made ({len(sections.decisions)})")
        for entry in sections.decisions:
            date_str = _entry_date_short(entry.created_at)
            lines.append(f"- {_first_line(entry.content)} ({date_str})")
        lines.append("")

    # Discovered with date annotations
    if sections.discovered:
        lines.append(f"### Discovered ({len(sections.discovered)})")
        for entry in sections.discovered:
            date_str = _entry_date_short(entry.created_at)
            lines.append(f"- {_first_line(entry.content)} ({date_str})")
        lines.append("")

    # Conventions
    if sections.patterns:
        lines.append(f"### Conventions Established ({len(sections.patterns)})")
        for entry in sections.patterns:
            lines.append(f"- {entry.content}")
        lines.append("")


def render_standup(sections: SnippetSections, meta: SnippetMeta) -> str:
    """Render snippet as standup format."""
    prefix = meta.staleness_warning

    if meta.empty:
        if meta.is_weekly:
            return prefix + "*This week:* No entries recorded.\n*Next week:* —\n*Blockers:* —\n"
        return prefix + "*Yesterday:* No entries recorded.\n*Today:* —\n*Blockers:* —\n"

    past_label = "*This week:*" if meta.is_weekly else "*Yesterday:*"
    future_label = "*Next week:*" if meta.is_weekly else "*Today:*"

    # Past: accomplished items
    if sections.accomplished:
        items = [_ensure_period(_first_line(e.content)) for e in sections.accomplished]
        past = f"{past_label} {' '.join(items)}"
    else:
        past = f"{past_label} No entries recorded."

    # Future: in-progress items
    if sections.in_progress:
        items = [_ensure_period(_first_line(e.content)) for e in sections.in_progress]
        future = f"{future_label} {' '.join(items)}"
    else:
        future = f"{future_label} —"

    # Blockers: gotchas
    if sections.discovered:
        items = [_ensure_period(_first_line(e.content)) for e in sections.discovered]
        blockers = f"*Blockers:* {' '.join(items)}"
    else:
        blockers = "*Blockers:* None detected."

    return prefix + f"{past}\n{future}\n{blockers}\n"


def render_slack(sections: SnippetSections, meta: SnippetMeta) -> str:
    """Render snippet as slack format."""
    prefix = meta.staleness_warning
    header = f"\U0001f4cb *{meta.range_label} snippet — {meta.project_name}*"

    if meta.empty:
        return prefix + f"{header}\n(no entries for this period)\n"

    lines = [header]
    max_lines = 15

    for entry in sections.accomplished:
        lines.append(f"\u2705 {_single_line(entry.content)}")
    for entry in sections.decisions:
        lines.append(f"\U0001f4cc Decided: {_single_line(entry.content)}")
    for entry in sections.discovered:
        lines.append(f"\u26a0\ufe0f Gotcha: {_single_line(entry.content)}")
    for entry in sections.in_progress:
        lines.append(f"\U0001f504 In progress: {_single_line(entry.content)}")
    for entry in sections.patterns:
        lines.append(f"\U0001f4d0 Convention: {_single_line(entry.content)}")

    # Enforce max 15 content lines (header doesn't count)
    content_lines = lines[1:]
    if len(content_lines) > max_lines:
        extra = len(content_lines) - max_lines
        lines = [lines[0]] + content_lines[:max_lines] + [f"(+{extra} more)"]

    return prefix + "\n".join(lines) + "\n"


def render_json(sections: SnippetSections, meta: SnippetMeta) -> str:
    """Render snippet as JSON."""
    if meta.empty:
        result = {"empty": True, "entry_count": 0, "sections": {}}
        if meta.staleness_warning:
            result["staleness_warning"] = meta.staleness_warning.strip()
        return json.dumps(result, indent=2) + "\n"

    def _entry_to_dict(entry: Entry, include_source_type: bool = False) -> dict:
        d = {"content": entry.content, "entry_id": entry.id}
        if include_source_type:
            d["source_type"] = entry.source_type
        return d

    result = {
        "project": meta.project_name,
        "branch": meta.branch,
        "range": {
            "start": meta.range_start,
            "end": meta.range_end,
        },
        "sections": {
            "accomplished": [_entry_to_dict(e, include_source_type=True) for e in sections.accomplished],
            "decisions": [_entry_to_dict(e) for e in sections.decisions],
            "discovered": [_entry_to_dict(e) for e in sections.discovered],
            "in_progress": [_entry_to_dict(e, include_source_type=True) for e in sections.in_progress],
            "patterns": [_entry_to_dict(e) for e in sections.patterns],
        },
        "entry_count": meta.entry_count,
        "empty": False,
    }
    if meta.staleness_warning:
        result["staleness_warning"] = meta.staleness_warning.strip()

    return json.dumps(result, indent=2) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _first_line(content: str) -> str:
    """Extract first line from content."""
    return content.split("\n")[0].strip()


def _single_line(content: str) -> str:
    """Collapse content to a single line for slack output."""
    return content.replace("\n", " ").strip()


def _ensure_period(text: str) -> str:
    """Ensure text ends with a period."""
    if text and not text.endswith((".", "!", "?")):
        return text + "."
    return text


def _entry_day_label(created_at: str) -> str:
    """Format entry date as 'Tue Feb 18'."""
    dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%a %b %-d")


def _entry_date_short(created_at: str) -> str:
    """Format entry date as 'Feb 18'."""
    dt = datetime.strptime(created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return dt.strftime("%b %-d")


def _compute_label(start_dt: datetime, end_dt: datetime, is_weekly: bool) -> str:
    """Compute a human-readable label from the range."""
    if is_weekly:
        return _range_label(start_dt, end_dt)
    return _day_label(start_dt)


_RENDERERS = {
    "markdown": render_markdown,
    "standup": render_standup,
    "slack": render_slack,
    "json": render_json,
}


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

_STALE_THRESHOLD_MINUTES = 10


def _check_staleness(conn: sqlite3.Connection, project_id: str | None) -> str:
    """Return a staleness warning string, or empty if fresh."""
    if project_id is None:
        return ""
    cursor = conn.execute(
        "SELECT MAX(created_at) FROM knowledge "
        "WHERE project_id = ? AND type = 'session_state'",
        (project_id,),
    )
    row = cursor.fetchone()
    if not row or not row[0]:
        return ""
    last_ts = datetime.strptime(row[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - last_ts
    age_minutes = int(age.total_seconds() / 60)
    if age_minutes >= _STALE_THRESHOLD_MINUTES:
        return (
            f"Note: Last checkpoint was {age_minutes}m ago. "
            "Recent work may not be reflected. "
            "Run `momento save` or call log_knowledge() to capture latest progress.\n\n"
        )
    return ""


def generate_snippet(
    conn: sqlite3.Connection,
    project_id: str,
    range_start: str,
    range_end: str,
    format: str = "markdown",
    branch: str | None = None,
    all_projects: bool = False,
    project_name: str = "",
) -> str:
    """Generate a formatted work summary from entries in the time range."""
    effective_project_id = None if all_projects else project_id
    entries = query_entries(conn, effective_project_id, range_start, range_end, branch)

    # Determine if weekly mode (range > ~1.5 days)
    start_dt = datetime.strptime(range_start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    end_dt = datetime.strptime(range_end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    is_weekly = (end_dt - start_dt) > timedelta(days=1, hours=12)

    label = _compute_label(start_dt, end_dt, is_weekly)

    meta = SnippetMeta(
        project_name=project_name,
        branch=branch,
        range_start=range_start,
        range_end=range_end,
        range_label=label,
        entry_count=len(entries),
        empty=len(entries) == 0,
        is_weekly=is_weekly,
        staleness_warning=_check_staleness(conn, project_id),
    )

    if not entries:
        renderer = _RENDERERS.get(format, render_markdown)
        return renderer(SnippetSections(), meta)

    sections = group_entries(entries)

    renderer = _RENDERERS.get(format, render_markdown)
    return renderer(sections, meta)

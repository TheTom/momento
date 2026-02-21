"""Knowledge retrieval — the read path."""

import json
import sqlite3
from datetime import datetime, timezone, timedelta

from momento.models import Entry, RestoreResult
from momento.tokens import estimate_tokens


# Tier quotas
_SESSION_SURFACE_QUOTA = 4
_SESSION_OTHER_QUOTA = 2
_PLAN_QUOTA = 2
_DECISION_QUOTA = 3
_GOTCHA_PATTERN_QUOTA = 4
_CROSS_PROJECT_QUOTA = 1

_TOKEN_BUDGET = 2000
_SEARCH_MAX_RESULTS = 10

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


def _render_entry(entry: Entry) -> str:
    """Render a single entry as markdown."""
    tags = json.loads(entry.tags) if isinstance(entry.tags, str) else entry.tags
    tag_str = ", ".join(tags) if tags else ""
    meta = f"[{entry.type} | {tag_str} | {entry.branch}]" if entry.branch else f"[{entry.type} | {tag_str}]"
    return f"{meta}\n{entry.content}\n"


def _tag_set(tags) -> set[str]:
    """Extract tag set from tags (JSON string or list)."""
    if isinstance(tags, str):
        return set(json.loads(tags))
    return set(tags)


def _sort_entries(entries: list[Entry], surface: str | None, branch: str | None) -> list[Entry]:
    """Sort: surface_match DESC, branch_match DESC, created_at DESC, id ASC.

    Uses stable multi-pass sort (Python's sort is stable).
    """
    entries = list(entries)
    entries.sort(key=lambda e: e.id)  # id ASC (final tiebreaker)
    entries.sort(key=lambda e: e.created_at or "", reverse=True)  # created_at DESC
    entries.sort(key=lambda e: -(1 if (branch and e.branch == branch) else 0))  # branch match DESC
    entries.sort(key=lambda e: -(1 if (surface and surface in _tag_set(e.tags)) else 0))  # surface match DESC
    return entries


def _greedy_fill(candidates: list[Entry], budget_remaining: int) -> tuple[list[Entry], int]:
    """Greedy fill: add entries until budget exhausted. Never truncate."""
    selected = []
    used = 0
    for entry in candidates:
        cost = estimate_tokens(_render_entry(entry))
        if used + cost > budget_remaining:
            break
        selected.append(entry)
        used += cost
    return selected, used


def _render_restore(entries: list[Entry], project_id: str) -> str:
    """Render full restore markdown output."""
    if not entries:
        return (
            "## Momento — Project Context\n\n"
            "No session checkpoints found for this project.\n\n"
            "**Tip:** Use `log_knowledge` to save decisions, gotchas, "
            "and session state as you work.\n"
        )

    sections: list[str] = []
    current_type = None
    type_headers = {
        "session_state": "## Active Task",
        "plan": "## Plans",
        "decision": "## Decisions",
        "gotcha": "## Gotchas",
        "pattern": "## Patterns",
    }
    cross_header_added = False

    for entry in entries:
        if entry.project_id != project_id and entry.project_id is not None:
            if not cross_header_added:
                sections.append("\n## Cross-Project\n")
                cross_header_added = True
            sections.append(_render_entry(entry))
            continue

        if entry.type != current_type:
            sections.append(f"\n{type_headers.get(entry.type, '## ' + entry.type)}\n")
            current_type = entry.type
        sections.append(_render_entry(entry))

    return "".join(sections).strip() + "\n"


def _render_search(entries: list[Entry]) -> str:
    """Render search results as markdown."""
    if not entries:
        return "## Search Results\n\nNo matching entries found.\n"
    parts = ["## Search Results\n"]
    for entry in entries:
        parts.append(_render_entry(entry))
    return "\n".join(parts).strip() + "\n"


def _restore_mode(
    conn: sqlite3.Connection,
    project_id: str,
    branch: str | None,
    surface: str | None,
    include_session_state: bool,
) -> RestoreResult:
    """Deterministic 5-tier state reconstruction."""
    all_entries: list[Entry] = []
    budget_used = 0

    # --- Tier 1: session_state (48h window) ---
    if include_session_state:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM knowledge "
            "WHERE project_id = ? AND type = 'session_state' AND created_at >= ? ",
            (project_id, cutoff),
        ).fetchall()
        candidates = _sort_entries([_row_to_entry(r) for r in rows], surface, branch)
        # Split surface-matching vs other
        surface_entries = [e for e in candidates if surface and surface in _tag_set(e.tags)]
        other_entries = [e for e in candidates if not (surface and surface in _tag_set(e.tags))]
        tier1 = surface_entries[:_SESSION_SURFACE_QUOTA] + other_entries[:_SESSION_OTHER_QUOTA]

        filled, cost = _greedy_fill(tier1, _TOKEN_BUDGET - budget_used)
        all_entries.extend(filled)
        budget_used += cost

    # --- Tier 2: plan ---
    if budget_used < _TOKEN_BUDGET:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM knowledge "
            "WHERE project_id = ? AND type = 'plan' ",
            (project_id,),
        ).fetchall()
        candidates = _sort_entries([_row_to_entry(r) for r in rows], surface, branch)[:_PLAN_QUOTA]
        filled, cost = _greedy_fill(candidates, _TOKEN_BUDGET - budget_used)
        all_entries.extend(filled)
        budget_used += cost

    # --- Tier 3: decision ---
    if budget_used < _TOKEN_BUDGET:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM knowledge "
            "WHERE project_id = ? AND type = 'decision' ",
            (project_id,),
        ).fetchall()
        candidates = _sort_entries([_row_to_entry(r) for r in rows], surface, branch)[:_DECISION_QUOTA]
        filled, cost = _greedy_fill(candidates, _TOKEN_BUDGET - budget_used)
        all_entries.extend(filled)
        budget_used += cost

    # --- Tier 4: gotcha + pattern (combined quota) ---
    if budget_used < _TOKEN_BUDGET:
        rows = conn.execute(
            f"SELECT {_SELECT_COLS} FROM knowledge "
            "WHERE project_id = ? AND type IN ('gotcha', 'pattern') ",
            (project_id,),
        ).fetchall()
        candidates = _sort_entries([_row_to_entry(r) for r in rows], surface, branch)[:_GOTCHA_PATTERN_QUOTA]
        filled, cost = _greedy_fill(candidates, _TOKEN_BUDGET - budget_used)
        all_entries.extend(filled)
        budget_used += cost

    # --- Tier 5: cross-project (tag overlap required, respects type quotas) ---
    if budget_used < _TOKEN_BUDGET:
        tag_rows = conn.execute(
            "SELECT tags FROM knowledge WHERE project_id = ?", (project_id,),
        ).fetchall()
        project_tags: set[str] = set()
        for (tags_json,) in tag_rows:
            project_tags.update(json.loads(tags_json))

        if project_tags:
            # Track how many of each type already included from project tiers.
            # Cross-project entries should not violate primary tier quotas.
            type_counts: dict[str, int] = {}
            for e in all_entries:
                type_counts[e.type] = type_counts.get(e.type, 0) + 1

            type_quotas = {
                "decision": _DECISION_QUOTA,
                "plan": _PLAN_QUOTA,
            }
            # gotcha+pattern share a combined quota
            gp_used = type_counts.get("gotcha", 0) + type_counts.get("pattern", 0)

            rows = conn.execute(
                f"SELECT {_SELECT_COLS} FROM knowledge "
                "WHERE project_id != ? AND project_id IS NOT NULL "
                "ORDER BY created_at DESC, id ASC",
                (project_id,),
            ).fetchall()

            candidates = []
            for r in rows:
                if len(candidates) >= _CROSS_PROJECT_QUOTA:
                    break
                entry = _row_to_entry(r)
                entry_tags = _tag_set(entry.tags)
                if not (entry_tags & project_tags):
                    continue
                # Respect per-type quotas globally
                if entry.type in type_quotas:
                    if type_counts.get(entry.type, 0) >= type_quotas[entry.type]:
                        continue
                elif entry.type in ("gotcha", "pattern"):
                    if gp_used >= _GOTCHA_PATTERN_QUOTA:
                        continue
                candidates.append(entry)
                # Update counts for subsequent cross-project entries
                type_counts[entry.type] = type_counts.get(entry.type, 0) + 1
                if entry.type in ("gotcha", "pattern"):
                    gp_used += 1

            filled, cost = _greedy_fill(candidates, _TOKEN_BUDGET - budget_used)
            all_entries.extend(filled)
            budget_used += cost

    # --- Increment retrieval counts (in knowledge_stats, NOT knowledge) ---
    if all_entries:
        ids = [e.id for e in all_entries]
        ph = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE knowledge_stats SET retrieval_count = retrieval_count + 1 WHERE entry_id IN ({ph})",
            ids,
        )
        conn.commit()

    # --- Render and compute final token count ---
    rendered = _render_restore(all_entries, project_id)
    total_tokens = estimate_tokens(rendered)

    return RestoreResult(entries=all_entries, total_tokens=total_tokens, rendered=rendered)


def _search_mode(
    conn: sqlite3.Connection,
    project_id: str,
    query: str,
) -> RestoreResult:
    """FTS5 keyword search ranked by relevance."""
    select_cols = (
        "k.id, k.content, k.content_hash, k.type, k.tags, k.project_id, "
        "k.project_name, k.branch, k.source_type, k.confidence, k.created_at, k.updated_at"
    )
    rows = conn.execute(
        f"SELECT {select_cols} FROM knowledge_fts f "
        "JOIN knowledge k ON k.rowid = f.rowid "
        "WHERE knowledge_fts MATCH ? ORDER BY rank",
        (query,),
    ).fetchall()

    selected = []
    budget_used = 0
    for entry in (_row_to_entry(r) for r in rows):
        if len(selected) >= _SEARCH_MAX_RESULTS:
            break
        cost = estimate_tokens(_render_entry(entry))
        if budget_used + cost > _TOKEN_BUDGET:
            break
        selected.append(entry)
        budget_used += cost

    if selected:
        ids = [e.id for e in selected]
        ph = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE knowledge_stats SET retrieval_count = retrieval_count + 1 WHERE entry_id IN ({ph})",
            ids,
        )
        conn.commit()

    rendered = _render_search(selected)
    return RestoreResult(entries=selected, total_tokens=estimate_tokens(rendered), rendered=rendered)


def retrieve_context(
    conn: sqlite3.Connection,
    project_id: str,
    branch: str | None = None,
    surface: str | None = None,
    query: str | None = None,
    include_session_state: bool = True,
) -> RestoreResult:
    """Retrieve relevant knowledge for the current project.

    Two modes:
    - Restore mode (query is None/empty): deterministic 5-tier state reconstruction
    - Search mode (query provided): FTS5 keyword search ranked by relevance

    Returns RestoreResult with .entries, .rendered, .total_tokens.
    """
    if query:
        return _search_mode(conn, project_id, query)
    return _restore_mode(conn, project_id, branch, surface, include_session_state)

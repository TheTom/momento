# Momento Snippets — Engineering PRD

**Version:** 0.2.0
**Status:** Ready for Implementation
**Depends on:** v0.1.0 (shipped, 350 tests passing)
**Date:** February 23, 2026

---

## 1. Problem

Developers cannot answer "what did I accomplish today?" without manually reconstructing their day from git log, Slack, and memory. The data already exists in Momento — session_state checkpoints, decisions, gotchas, plans — but there is no view that assembles it into a human-readable summary.

The same problem repeats at weekly standup, sprint review, and PR description time.

---

## 2. Solution

A read-only query + formatter over existing knowledge entries. No new schema. No new entry types. No LLM. Same DB, different lens.

---

## 3. Core Concept

A **snippet** is a structured work summary derived from Momento entries within a time range.

```
momento snippet                      # today
momento snippet --yesterday          # yesterday  
momento snippet --week               # last 7 days
momento snippet --range 2026-02-17 2026-02-21
```

That is the product.

---

## 4. CLI Interface

### `momento snippet`

Generate a work summary from stored entries.

```bash
momento snippet                                    # today, markdown
momento snippet --yesterday                        # yesterday
momento snippet --week                             # last 7 days
momento snippet --range 2026-02-17 2026-02-21      # custom range
momento snippet --format standup                   # standup format
momento snippet --format slack                     # slack-paste format
momento snippet --format markdown                  # default
momento snippet --format json                      # machine-readable
momento snippet --branch feature/billing-rewrite   # filter to branch
momento snippet --all-projects                     # cross-project
```

| Flag | Default | Description |
|------|---------|-------------|
| `--yesterday` | — | Shorthand for yesterday 00:00–23:59 UTC |
| `--week` | — | Shorthand for last 7 days |
| `--range <start> <end>` | — | Custom date range, ISO format (YYYY-MM-DD) |
| `--format <fmt>` | `markdown` | One of: `markdown`, `standup`, `slack`, `json` |
| `--branch <name>` | current branch | Filter entries to specific branch |
| `--all-projects` | false | Include all projects, not just current |
| (no time flag) | today | Default time range is today (00:00 UTC to now) |

**Exit behavior:**
- If no entries exist in the time range, print a clear message — not an empty template.
- If no project is detected (not in a git repo, no entries), print an error and exit 1.

---

## 5. MCP Tool

### `generate_snippet`

Third MCP tool alongside `log_knowledge` and `retrieve_context`.

```json
{
  "name": "generate_snippet",
  "description": "Generate a work summary from stored memory entries for the current project.",
  "input_schema": {
    "type": "object",
    "properties": {
      "range": {
        "type": "string",
        "enum": ["today", "yesterday", "week", "custom"],
        "default": "today",
        "description": "Time range for the summary."
      },
      "start_date": {
        "type": "string",
        "description": "Start date for custom range. ISO format YYYY-MM-DD."
      },
      "end_date": {
        "type": "string",
        "description": "End date for custom range. ISO format YYYY-MM-DD."
      },
      "format": {
        "type": "string",
        "enum": ["markdown", "standup", "slack", "json"],
        "default": "markdown",
        "description": "Output format."
      }
    }
  }
}
```

Project, branch, and surface are auto-resolved from cwd, same as all other tools.

This enables:
> "Hey Claude, what did I get done this week?"
> → Agent calls `generate_snippet(range="week")`
> → Returns formatted summary from stored entries

---

## 6. Output Formats

### 6.1 Markdown (default)

```markdown
# Momento Snippet — Friday, Feb 21 2026
## payments-platform · feature/billing-rewrite

### Accomplished
- Migrated AuthService from sync to async/await (3 of 7 handlers done)
- Fixed webhook race condition workaround (200ms delay + idempotency check)

### Decisions Made
- Server-side Stripe Checkout over client-side
  → PCI scope reduction, webhook reliability
  → Rejected: Stripe.js elements
- Auth tokens: moved from JWT to opaque server-side sessions
  → JWTs can't be revoked without blocklist

### Discovered
- Stripe webhook race: fulfillment event arrives before DB commit
  → Always verify payment_intent status server-side
- iOS Keychain: kSecAttrAccessible must be AfterFirstUnlock
  → WhenUnlocked breaks background refresh

### Still In Progress
- iOS Keychain migration: 4 of 6 screens updated
- Billing rewrite phase 1: Stripe Checkout migration

### Conventions Established
- All new API endpoints: validate → authorize → execute → respond
- Error responses: error_code + message + request_id
```

### 6.2 Standup

```
*Yesterday:* Migrated 3/7 handlers to async AuthService. Fixed webhook race condition with idempotency guard. Decided on server-side Stripe Checkout.
*Today:* Continue handler migration (4 remaining). Start Keychain wrapper for remaining 2 iOS screens.
*Blockers:* None detected.
```

**Standup derivation rules:**
- "Yesterday" = accomplished entries from the time range
- "Today" = still-in-progress items (most recent session_state per surface/branch)
- "Blockers" = gotchas created in the range, or "(None detected)" if none

### 6.3 Slack

```
📋 *Feb 21 snippet — payments-platform*
✅ AuthService async migration (3/7 handlers)
✅ Webhook race condition fix
📌 Decided: server-side Stripe Checkout
📌 Decided: JWT → opaque sessions
⚠️ Gotcha: Stripe webhook race
⚠️ Gotcha: Keychain accessibility mode
🔄 In progress: Keychain migration 4/6
🔄 In progress: Billing phase 1
```

**Slack rules:**
- One line per item. No multiline.
- Emoji prefix by section: ✅ accomplished, 📌 decision, ⚠️ gotcha, 🔄 in progress, 📐 pattern
- Max 15 lines. If more entries exist, collapse with "(+N more)"

### 6.4 JSON

```json
{
  "project": "payments-platform",
  "branch": "feature/billing-rewrite",
  "range": { "start": "2026-02-21T00:00:00Z", "end": "2026-02-21T23:59:59Z" },
  "sections": {
    "accomplished": [
      { "content": "Migrated AuthService from sync to async/await (3 of 7 handlers done)", "source_type": "session_state", "entry_id": "..." }
    ],
    "decisions": [
      { "content": "Server-side Stripe Checkout over client-side...", "entry_id": "..." }
    ],
    "discovered": [
      { "content": "Stripe webhook race: fulfillment event arrives before DB commit...", "entry_id": "..." }
    ],
    "in_progress": [
      { "content": "iOS Keychain migration: 4 of 6 screens updated", "source_type": "session_state", "entry_id": "..." }
    ],
    "patterns": [
      { "content": "All new API endpoints: validate → authorize → execute → respond", "entry_id": "..." }
    ]
  },
  "entry_count": 14,
  "empty": false
}
```

### 6.5 Empty Range

When no entries exist for the time range:

**Markdown:**
```markdown
# Momento Snippet — Friday, Feb 21 2026
## payments-platform

No entries found for this time range.

Tip: Use `momento save` or `log_knowledge()` to capture work in progress.
```

**Standup:**
```
*Yesterday:* No entries recorded.
*Today:* —
*Blockers:* —
```

**Slack:**
```
📋 *Feb 21 snippet — payments-platform*
(no entries for this period)
```

**JSON:**
```json
{ "empty": true, "entry_count": 0, "sections": {} }
```

---

## 7. Query

Single query. No joins. No subqueries.

```sql
SELECT id, type, content, tags, branch, surface, created_at
FROM knowledge
WHERE project_id = :project_id
  AND created_at >= :range_start
  AND created_at < :range_end
ORDER BY type, created_at ASC;
```

Optional branch filter adds `AND branch = :branch`.

Cross-project mode (`--all-projects`) removes the `project_id` filter.

The `surface` value is derived from tags at render time (same as restore mode), not stored as a column. The query returns `tags`, and the snippet formatter extracts surface from tags using the same surface detection logic.

---

## 8. Section Mapping

Entries are grouped into snippet sections by type:

| Entry Type | Snippet Section | Rendering |
|------------|----------------|-----------|
| `session_state` | **Accomplished** or **Still In Progress** | Split by recency heuristic (see 8.1) |
| `decision` | **Decisions Made** | Chronological, full content |
| `gotcha` | **Discovered** | Chronological, full content |
| `pattern` | **Conventions Established** | Chronological, full content |
| `plan` | **Still In Progress** | Always in-progress section |

### 8.1 Session State Split: Accomplished vs. Still In Progress

The most recent `session_state` per surface+branch combination is **Still In Progress** (the developer's current working state). All older session_state entries for that surface+branch are **Accomplished** (superseded checkpoints representing completed work).

```python
def split_session_states(entries: list[Entry]) -> tuple[list, list]:
    """Split session_state entries into accomplished and in-progress."""
    latest_by_key: dict[tuple[str|None, str|None], Entry] = {}
    
    for entry in entries:
        key = (extract_surface(entry.tags), entry.branch)
        if key not in latest_by_key or entry.created_at > latest_by_key[key].created_at:
            latest_by_key[key] = entry
    
    in_progress_ids = {e.id for e in latest_by_key.values()}
    
    accomplished = [e for e in entries if e.id not in in_progress_ids]
    in_progress = [e for e in entries if e.id in in_progress_ids]
    
    return accomplished, in_progress
```

**Keyword override:** If a session_state content contains any of: `"done"`, `"completed"`, `"finished"`, `"shipped"`, `"merged"`, `"resolved"` (case-insensitive, word boundary match) — it moves to **Accomplished** regardless of recency.

The keyword list is hardcoded. Not configurable in v0.2. If it proves noisy, shrink it.

### 8.2 Plans

Plans always appear in **Still In Progress**. A plan represents ongoing work by definition. If a plan was completed, the developer would have logged a decision or let it age out.

### 8.3 Section Ordering in Output

Sections always render in this order:

1. Accomplished
2. Decisions Made
3. Discovered
4. Still In Progress
5. Conventions Established

Empty sections are omitted entirely — no "### Accomplished\n(none)" blocks.

---

## 9. Weekly Snippets

Weekly range (`--week` or `--range` spanning multiple days) uses the same query but adds day grouping.

### 9.1 Markdown Weekly

```markdown
# Momento Snippet — Feb 17–21 2026
## payments-platform

### Key Moments
- **Tue Feb 18:** Decided server-side Stripe Checkout (PCI scope reduction)
- **Wed Feb 19:** Discovered webhook race condition (Stripe fulfills before DB commit)
- **Thu Feb 20:** Moved auth from JWT to server-side sessions

### Progress
- AuthService async migration: 3/7 handlers done
- iOS Keychain migration: 4/6 screens updated
- Billing rewrite: phase 1 in progress

### Decisions Made (4)
- Server-side Stripe Checkout over client-side (Feb 18)
- Auth tokens: JWT → opaque sessions (Feb 20)
- Error response format standardized (Feb 20)
- Rate limiter: distributed counter via Redis (Feb 21)

### Discovered (3)
- Stripe webhook race condition (Feb 19)
- iOS Keychain accessibility mode (Feb 20)
- Redis session TTL / cookie maxAge mismatch (Feb 21)

### Conventions Established (2)
- API endpoints: validate → authorize → execute → respond
- Error responses: error_code + message + request_id
```

### 9.2 Weekly Derivation

**Key Moments** = decisions + gotchas, grouped by day, one line per entry. Shows the date and a short summary. This gives the week narrative arc.

**Progress** = most recent session_state per surface+branch. Shows current state of in-flight work.

**Decisions/Discovered/Conventions** = full listing with dates, same as daily but with date annotation.

### 9.3 Standup for Weekly

```
*This week:* Migrated 3/7 auth handlers to async. Fixed webhook race. Decided server-side Checkout + opaque sessions. Documented 2 gotchas, established 2 conventions.
*Next week:* Complete handler migration. Finish Keychain migration (2 screens). Start billing phase 1 testing.
*Blockers:* None detected.
```

"Next week" is derived from the most recent in-progress items.

---

## 10. Four-Fence Test

| Test | Pass? | Rationale |
|------|-------|-----------|
| Agent-agnostic | Yes | Read-only query. Any agent's entries are included. |
| Stateless server | Yes | No server state. Query existing DB. |
| Deterministic | Yes | Same time range + same DB = same output. |
| Zero coupling | Yes | No agent internals needed. |

---

## 11. What This Is NOT

- **Not an LLM summary.** No model generates or rewrites content. Snippets are assembled from stored entries using templates and grouping logic.
- **Not a new entry type.** Snippets are ephemeral output. They are not stored back into the DB.
- **Not a daemon.** No scheduled generation. Run it when you want it.
- **Not a replacement for `momento inspect`.** Inspect shows raw entries. Snippets show a narrative view.
- **Not a replacement for `retrieve_context`.** Restore mode is machine-optimized (token-budgeted, tier-ordered). Snippets are human-optimized (narrative, grouped by section).

---

## 12. Edge Cases

### 12.1 No Entries

Print format-appropriate empty message (Section 6.5). Exit 0 — absence of data is not an error.

### 12.2 Only Session States

Accomplished + Still In Progress sections only. Decisions/Discovered/Conventions sections omitted.

### 12.3 Only Durable Entries (No Session States)

Decisions/Discovered/Conventions sections render. Accomplished and Still In Progress are omitted. This happens when a developer returns after 48h+ (session_state expired from restore) but logged durable entries.

### 12.4 Single Entry

One entry, one section. No padding. No filler.

### 12.5 Very Long Time Range

`--range 2026-01-01 2026-12-31` returns everything in the year. No pagination in v0.2 — if this becomes a problem, add `--limit` later. For now, trust that Momento entries are intentionally small and curated.

### 12.6 Cross-Branch Entries

When no `--branch` filter is applied, entries from all branches appear. The snippet groups by section, not by branch. Branch metadata is shown inline for daily (`[feature/billing]`) and as date annotations for weekly.

### 12.7 Timezone Handling

All timestamps are UTC. The `--range` dates are interpreted as UTC midnight. No local timezone conversion in v0.2. If a developer works across timezones, they can use `--range` with explicit dates. Adding `--tz` is a v0.3 consideration.

---

## 13. Implementation

### 13.1 Module

```
src/momento/snippet.py
```

### 13.2 Core Functions

```python
def generate_snippet(
    db: Connection,
    project_id: str,
    range_start: str,   # ISO 8601
    range_end: str,      # ISO 8601
    format: str = "markdown",  # markdown | standup | slack | json
    branch: str | None = None,
    all_projects: bool = False,
) -> str:
    """Generate a formatted work summary from entries in the time range."""
```

```python
def query_entries(
    db: Connection,
    project_id: str | None,
    range_start: str,
    range_end: str,
    branch: str | None = None,
) -> list[Entry]:
    """Fetch entries for the time range. Pure SQL, no post-processing."""
```

```python
def group_entries(entries: list[Entry]) -> SnippetSections:
    """Group entries into snippet sections by type + recency heuristic."""
```

```python
def render_markdown(sections: SnippetSections, meta: SnippetMeta) -> str:
def render_standup(sections: SnippetSections, meta: SnippetMeta) -> str:
def render_slack(sections: SnippetSections, meta: SnippetMeta) -> str:
def render_json(sections: SnippetSections, meta: SnippetMeta) -> str:
```

### 13.3 Data Structures

```python
@dataclass
class SnippetMeta:
    project_name: str
    branch: str | None
    range_start: str
    range_end: str
    range_label: str   # "Friday, Feb 21 2026" or "Feb 17–21 2026"
    entry_count: int
    empty: bool

@dataclass
class SnippetSections:
    accomplished: list[Entry]
    decisions: list[Entry]
    discovered: list[Entry]      # gotchas
    in_progress: list[Entry]     # latest session_state + plans
    patterns: list[Entry]
```

### 13.4 Time Range Resolution

```python
def resolve_range(
    today: bool = True,
    yesterday: bool = False,
    week: bool = False,
    range_start: str | None = None,
    range_end: str | None = None,
) -> tuple[str, str, str]:
    """Returns (start_iso, end_iso, label)."""
```

- `today`: 00:00:00Z today → now
- `yesterday`: 00:00:00Z yesterday → 23:59:59Z yesterday
- `week`: 7 days ago 00:00:00Z → now
- `custom`: parse dates, midnight to midnight UTC

Uses `datetime.now(timezone.utc)`. Same clock source rule as v0.1.

### 13.5 Keyword Completion Detection

```python
COMPLETION_KEYWORDS = {"done", "completed", "finished", "shipped", "merged", "resolved"}

def is_completed(content: str) -> bool:
    """Check if session_state content signals completion."""
    content_lower = content.lower()
    for kw in COMPLETION_KEYWORDS:
        if re.search(rf'\b{kw}\b', content_lower):
            return True
    return False
```

Word boundary match. Not substring. "unfinished" does not match "finished".

---

## 14. CLI Registration

Add to existing Click CLI group:

```python
@cli.command()
@click.option("--yesterday", is_flag=True, help="Yesterday's summary")
@click.option("--week", is_flag=True, help="Last 7 days")
@click.option("--range", "date_range", nargs=2, type=str, help="Custom range: START END (YYYY-MM-DD)")
@click.option("--format", "fmt", type=click.Choice(["markdown", "standup", "slack", "json"]), default="markdown")
@click.option("--branch", type=str, default=None, help="Filter to branch")
@click.option("--all-projects", is_flag=True, help="Include all projects")
def snippet(yesterday, week, date_range, fmt, branch, all_projects):
    ...
```

---

## 15. MCP Registration

Add `generate_snippet` as a third tool in the MCP server handler. Same registration pattern as `log_knowledge` and `retrieve_context`.

Working directory is auto-resolved by the MCP server framework. Project ID, branch, and surface are derived from cwd.

---

## 16. Interaction with Existing Features

| Feature | Relationship |
|---------|-------------|
| `retrieve_context` (restore) | Different purpose. Restore is machine-optimized, token-budgeted, tier-ordered. Snippets are human-optimized, narrative, section-grouped. |
| `retrieve_context` (search) | Search finds individual entries by keyword. Snippets assemble entries by time. |
| `momento inspect` | Inspect shows raw entries with full metadata. Snippets show a narrative view. |
| `momento status` | Status shows aggregate counts. Snippets show content. |
| `momento last` | Last shows one entry. Snippets show a range. |

No conflicts. No overlapping behavior. Clean separation.

---

## 17. What Ships

**v0.2.0 Snippets scope:**
1. `momento snippet` CLI command — all four formats
2. `generate_snippet` MCP tool — same four formats
3. Daily and weekly time ranges (today, yesterday, week, custom)
4. Session state accomplished/in-progress split
5. Keyword completion detection
6. Branch filtering
7. Cross-project flag
8. Empty range handling (all four formats)

**Not in v0.2.0:**
- Timezone support (`--tz`)
- Pagination for long ranges
- Custom section ordering
- Natural language range parsing ("last Tuesday")
- Auto-scheduling / cron generation
- Snippet storage (snippets are ephemeral, never persisted)

---

## 18. Implementation Order

```
1. snippet.py — resolve_range() + query_entries()
2. snippet.py — group_entries() + split_session_states()
3. snippet.py — is_completed() keyword detection
4. snippet.py — render_markdown()
5. snippet.py — render_standup()
6. snippet.py — render_slack()
7. snippet.py — render_json()
8. cli.py — momento snippet command registration
9. mcp server — generate_snippet tool registration
10. Empty range handling across all formats
```

---

## 19. Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| New schema? | No | Pure read-path over existing tables. |
| LLM in pipeline? | No | Template-based rendering. Deterministic. |
| Snippets stored? | No | Ephemeral output. Run it when you want it. |
| Keyword list configurable? | No (v0.2) | Hardcoded. Shrink if noisy. |
| Timezone support? | No (v0.2) | UTC only. `--tz` in v0.3 if needed. |
| Token budget? | No | Snippets are for humans, not context windows. No cap. |
| Section ordering? | Fixed | Always: accomplished, decisions, discovered, in-progress, patterns. |
| Weekly grouping? | By section with dates | Not by day. Day grouping makes weekly snippets long and fragmented. |
| Surface in query? | Derived from tags | Not a column. Same logic as restore mode. |
| Clock source | `datetime.now(timezone.utc)` | Same rule as v0.1 writes. |

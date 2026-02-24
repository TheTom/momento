# Momento Knowledge Decay — Engineering PRD

**Version:** 0.2.0
**Status:** Ready for Implementation
**Depends on:** v0.1.3 (shipped, 514 tests passing)
**Date:** February 24, 2026

---

## 1. Problem

Durable entries never lose ranking priority. A gotcha logged 3 months ago that has never been retrieved ranks the same as a gotcha logged yesterday that gets retrieved every session. The old entry might be still critical, stale, or noise — Momento can't tell the difference.

As the knowledge base grows:
- Restore fills up with old entries that crowd out recent, relevant ones
- Tier quotas (3 decisions max) get consumed by stale decisions
- The developer has to manually `momento prune` to keep things useful
- Trust erodes — "Momento keeps showing me stuff from 2 months ago"

Without decay, manual pruning is the only hygiene mechanism. Developers won't do it. The knowledge base accumulates noise and restore quality degrades over weeks of real use.

---

## 2. Solution

Ranking demotion within a tier based on freshness. Entries that haven't been reinforced (retrieved, updated, or referenced) gradually sink below fresher entries of the same type.

Decay is NOT deletion. Nothing disappears automatically. Decayed entries remain in the DB, searchable, visible in `momento inspect`. They just lose their slot in the restore budget to entries that are more recently relevant.

No LLM. Pure timestamp comparison. Deterministic.

---

## 3. Core Concept

Replace `created_at` with **freshness** as the third sort key in restore ranking:

```
freshness = MAX(created_at, last_retrieved_at, last_updated_at)
```

- `created_at` — when the entry was first stored (never changes)
- `last_retrieved_at` — when the entry was last included in a restore result
- `last_updated_at` — when the entry content was last modified (future feature, uses existing `updated_at`)

If an entry has never been retrieved: `freshness = created_at` (v0.1 behavior preserved).
If an entry was retrieved yesterday: `freshness = yesterday` (refreshed, stays high in ranking).

```
Day 1:   gotcha created → high priority in restore
Day 30:  gotcha retrieved during session → priority refreshed
Day 60:  gotcha not retrieved → starts decaying
Day 90:  gotcha still not retrieved → ranks below newer gotchas
Day 180: gotcha deep in decay → unlikely to appear in restore
         but still in DB, still in search, still in inspect
```

---

## 4. CLI Interface

No new CLI commands. Decay affects existing commands:

### `momento inspect` — Shows Freshness

```bash
$ momento inspect

[decision] branch=main tags=['architecture', 'embeddings'] 18d ago | fresh: 2d ago
   Switched to all-MiniLM-L6-v2 embeddings...

[gotcha] branch=main tags=['deployment', 'mac_mini'] 12d ago | fresh: 12d ago
   Docker at /opt/homebrew/bin/docker not in SSH PATH...

[gotcha] branch=main tags=['retrieval', 'bm25'] 30d ago | fresh: 30d ago ⚠ decaying
   BM25 falls back to vector-only above 20k vectors...
```

- `18d ago` = `created_at` (when it was logged)
- `fresh: 2d ago` = freshness (last retrieved or created)
- `⚠ decaying` = freshness > 21 days (visual indicator only, does not affect ranking)

### `momento status` — Shows Decay Distribution

```bash
$ momento status

Project: momento
Branch:  main
Entries: 34
  ...
Freshness:
  Active (≤7d):    12 entries
  Aging (7-30d):   15 entries
  Decaying (>30d):  7 entries
```

### `momento debug-restore` — Shows Freshness Impact

```bash
$ momento debug-restore

Tier 2 — Decisions (showing 3 of 8):
  #1 [decision] embeddings change    created=18d  fresh=2d   ← retrieved recently
  #2 [decision] stripe checkout      created=25d  fresh=8d   ← retrieved last week
  #3 [decision] jwt to sessions      created=20d  fresh=20d  ← never retrieved since creation
  --- cut by quota (5 more decisions exist but quota=3) ---

  Excluded by decay:
  #4 [decision] old api format       created=60d  fresh=60d  ← would have been #3 without decay
```

---

## 5. Design Constraints

### 5.1 — Determinism Must Be Preserved

Current guarantee: same DB state + same cwd + same branch = identical restore output.

Decay does NOT break this. Decay is based on DB state (timestamps, counts), not external randomness. The difference is that "DB state" now includes `last_retrieved_at`, which changes when entries are retrieved.

### 5.2 — No Background Processes

Decay is computed at query time, not by a daemon. No cron jobs. No scheduled rewrites. The DB is never mutated by a background process. Decay is a sort calculation, not a state mutation.

### 5.3 — No Entry Deletion

Decay never deletes entries. The 48h session_state window in restore is a query filter, not a deletion rule. Decayed entries are deprioritized, not removed.

### 5.4 — Must Be Overridable

`momento inspect` shows all entries regardless of decay. `momento search` finds decayed entries. Only restore mode applies decay ranking. The developer always has full visibility.

### 5.5 — Four-Fence Test

1. **Agent-agnostic** — works regardless of which agent is calling
2. **Stateless server** — no session state on the server
3. **Deterministic** — same DB state = same output
4. **Zero coupling** — no agent internals needed

---

## 6. The Freshness Model

### 6.1 — Current Sort Order (v0.1)

Within each tier, entries sort by:
```
surface_match DESC → branch_match DESC → created_at DESC → id ASC
```

`created_at` never changes. A decision made 3 months ago always sorts behind a decision made yesterday, regardless of how useful the old one is.

### 6.2 — Proposed Sort Order (v0.2)

Replace `created_at` with **freshness**:

```
surface_match DESC → branch_match DESC → freshness DESC → id ASC
```

Where:

```python
freshness = max(created_at, last_retrieved_at or created_at)
```

This means:
- New entries start fresh (high priority)
- Entries that keep showing up in restore stay fresh (they're being used)
- Entries that stop being relevant naturally sink (no manual pruning needed)
- An entry can be "revived" by a single retrieval

### 6.3 — Why MAX, Not a Decay Function

Exponential decay, half-life models, weighted moving averages — all introduce tuning parameters that are hard to reason about. MAX is simple: **an entry is as fresh as the last time anything happened to it.** No coefficients. No configuration. No surprises.

### 6.4 — Decay Curve (Future, Not v0.2)

If pure MAX proves too binary, add a soft decay curve in v0.3:

```python
def effective_freshness(created_at, last_retrieved_at, now):
    base = max(created_at, last_retrieved_at or created_at)
    age_days = (now - base).days

    if age_days <= 7:
        return base                    # full freshness for 1 week
    elif age_days <= 30:
        penalty = (age_days - 7) * 0.5  # gentle decay 7-30 days
        return base - timedelta(hours=penalty)
    else:
        penalty = 11.5 + (age_days - 30) * 2  # steeper decay after 30 days
        return base - timedelta(hours=penalty)
```

Start with pure MAX. Add the curve only with evidence that pure MAX is insufficient.

---

## 7. Schema Change

### 7.1 — Add `last_retrieved_at` to `knowledge_stats`

```sql
ALTER TABLE knowledge_stats ADD COLUMN last_retrieved_at TEXT;
```

`knowledge_stats` already has `entry_id` and `retrieval_count`. Adding `last_retrieved_at` keeps all retrieval analytics in one place, away from the `knowledge` table (no FTS trigger churn).

### 7.2 — Update Retrieval Upsert

Current (in `retrieve.py`):
```sql
INSERT INTO knowledge_stats (entry_id, retrieval_count)
VALUES (?, 1)
ON CONFLICT(entry_id) DO UPDATE SET retrieval_count = retrieval_count + 1;
```

New:
```sql
INSERT INTO knowledge_stats (entry_id, retrieval_count, last_retrieved_at)
VALUES (?, 1, ?)
ON CONFLICT(entry_id) DO UPDATE SET
  retrieval_count = retrieval_count + 1,
  last_retrieved_at = ?;
```

Timestamp is `datetime.now(UTC).isoformat()`, same clock source rule as all writes.

### 7.3 — Migration v1 → v2

```python
def _migrate_v1_to_v2(conn):
    conn.execute("ALTER TABLE knowledge_stats ADD COLUMN last_retrieved_at TEXT")
    conn.execute("UPDATE momento_meta SET value = '2' WHERE key = 'schema_version'")
```

Existing entries get `last_retrieved_at = NULL`, which means `freshness = created_at` (v0.1 behavior preserved). No backfill needed.

### 7.4 — No Change to `knowledge` Table

The `knowledge` table is untouched. `created_at` and `updated_at` remain as-is. FTS triggers are unaffected. This is a `knowledge_stats` change only.

---

## 8. Restore Query Change

### 8.1 — Current Sort in `_sort_entries()` (v0.1)

```python
def _sort_entries(entries, surface, branch, use_confidence=False):
    """Sort: surface_match DESC, branch_match DESC, [confidence DESC], created_at DESC, id ASC."""
```

### 8.2 — New Sort (v0.2)

Replace `created_at` with freshness in the sort key:

```python
def _sort_entries(entries, surface, branch, use_confidence=False, stats=None):
    """Sort: surface_match DESC, branch_match DESC, [confidence DESC], freshness DESC, id ASC."""
```

Where `stats` is a `dict[str, str | None]` mapping `entry_id → last_retrieved_at`.

Freshness for an entry:
```python
def _freshness(entry, stats):
    last_retrieved = stats.get(entry.id) if stats else None
    return max(entry.created_at, last_retrieved or entry.created_at)
```

### 8.3 — Session State Exemption

Session states already have the 48h window filter. Decay is redundant for session_state — they're already ephemeral. The freshness sort still applies within the 48h window, but the practical impact is minimal.

### 8.4 — Search Mode Unaffected

Search mode uses pure FTS5 relevance. No freshness. No decay. No change.

---

## 9. Reinforcement Mechanics

### 9.1 — What Refreshes Freshness

| Action | Updates `last_retrieved_at`? | Rationale |
|--------|----------------------------|-----------|
| Entry appears in restore result | Yes | Agent used this knowledge |
| Entry appears in search result | No | Human browsed, not agent consumption |
| `momento inspect` views entry | No | Passive viewing, not active use |
| Entry content updated via CLI | Updates `updated_at` on knowledge table | Content change is a refresh signal |

**Only restore inclusion refreshes.** If search or inspect refreshed, casual browsing would prevent decay.

### 9.2 — Reinforcement Loop

```
1. Developer works → agent calls retrieve_context()
2. Relevant entries appear in restore (freshness refreshed)
3. Irrelevant entries don't appear (freshness untouched)
4. Over time, relevant entries stay high, irrelevant entries sink
5. New entries enter at high freshness, compete immediately
6. Developer prunes truly dead entries via momento prune
```

### 9.3 — Revival

A decayed entry can be revived by:
1. Being included in a restore result (happens if newer entries were pruned and the old one bubbles back up)
2. Developer running `momento log` to update its content (updates `updated_at`)
3. Future: `momento pin <id>` to manually override decay (v0.3 consideration)

---

## 10. What Decay Does NOT Do

- **Does not delete entries.** Ever. Decay is ranking, not garbage collection.
- **Does not affect search.** Search is FTS5 relevance only. No decay.
- **Does not affect inspect.** Inspect shows everything.
- **Does not change tier ordering.** Tiers are still: session_state > plan > decision > gotcha+pattern > cross-project. Decay operates WITHIN a tier, not across tiers.
- **Does not change surface/branch preference.** Surface match still beats branch match. Branch match still beats freshness.
- **Does not use retrieval_count.** Count is for analytics. Freshness uses timestamps only.
- **Does not involve an LLM.** Pure timestamp comparison.

---

## 11. Implementation Plan

### 11.1 — Files to Change

| File | Change |
|------|--------|
| `db.py` | Schema version 1→2, migration, `_SCHEMA_VERSION = 2` |
| `retrieve.py` | `_sort_entries()` freshness parameter, `_freshness()` helper, stats query, retrieval upsert update |
| `cli.py` | `cmd_inspect()` freshness display, `cmd_status()` decay distribution, `cmd_debug_restore()` freshness impact |
| `models.py` | No change (freshness is computed, not stored) |
| `store.py` | No change (stats row still initialized with `retrieval_count = 0`) |
| `mcp_server.py` | No change (calls `retrieve_context` which calls updated `retrieve.py`) |

### 11.2 — New Test File

`tests/test_decay.py` — 10+ tests covering:

| Test | Description |
|------|-------------|
| TD.1 | Freshness replaces `created_at` in sort — retrieved entry ranks above newer unretrieved entry |
| TD.2 | NULL `last_retrieved_at` defaults to `created_at` (v0.1 backward compat) |
| TD.3 | Retrieval updates `last_retrieved_at` in `knowledge_stats` |
| TD.4 | Search does NOT update `last_retrieved_at` |
| TD.5 | Inspect does NOT update `last_retrieved_at` |
| TD.6 | Freshness does not cross tiers — fresh gotcha does not outrank stale decision |
| TD.7 | Surface/branch still outrank freshness |
| TD.8 | Schema migration v1→v2 — fresh DB works, existing v1 DB migrates cleanly |
| TD.9 | Decay visibility in inspect — `⚠ decaying` indicator for freshness > 21 days |
| TD.10 | Status shows freshness distribution (active/aging/decaying counts) |

### 11.3 — Implementation Order

1. Schema migration (`db.py`) — add `last_retrieved_at` column
2. Retrieval upsert (`retrieve.py`) — write `last_retrieved_at` on restore
3. Freshness sort (`retrieve.py`) — replace `created_at` with freshness
4. CLI display updates (`cli.py`) — inspect, status, debug-restore
5. Tests (`test_decay.py`) — all TD.1–TD.10
6. Doc updates — reference.md, momento-tests.md

---

## 12. Impact on Existing Tests

### 12.1 — Tests That Change

- **T4.1 (Restore Contract):** Sort order changes from `created_at` to `freshness`. Test must use entries with known `last_retrieved_at` values, or entries with `NULL` last_retrieved_at (which preserves v0.1 behavior).
- **T4.11/T4.12 (Determinism):** Still deterministic. Same DB state = same output. But "DB state" now includes `knowledge_stats.last_retrieved_at`.
- **T4.14/T4.15 (retrieval_count):** Updated to also verify `last_retrieved_at` is written.

### 12.2 — Backward Compatibility

All existing entries have `last_retrieved_at = NULL`. The freshness function falls back to `created_at` for NULL values. This means **all existing tests pass without modification** unless they explicitly test sort order against `created_at` — those need updating to account for the freshness fallback.

---

## 13. Why v0.2, Not v0.5

The original roadmap put decay at v0.5. Moving it up because:

1. **The schema change is tiny** — one column on `knowledge_stats`. The longer we wait, the more entries accumulate without freshness data.
2. **The restore query change is one sort key** — replace `created_at` with MAX expression. Not a rewrite.
3. **Existing data degrades gracefully** — `NULL` = v0.1 behavior. No backfill.
4. **Without decay, manual pruning is the only hygiene mechanism.** The knowledge base will accumulate noise during dogfood.
5. **Decay makes every other v0.2+ feature better.** Snippets, audit, momentum — all benefit from a knowledge base that self-ranks by relevance.

---

## 14. Future (NOT v0.2)

| Feature | Version | Description |
|---------|---------|-------------|
| Decay Curve | v0.3 | Three-zone soft decay (0–7d full, 7–30d gentle, 30d+ steep). Only if pure MAX proves too binary. |
| Pinning | v0.3 | `momento pin <id>` / `momento unpin <id>`. Pinned entries sort as if `freshness = now`. |
| Auto-Prune Suggestions | v0.4 | `momento prune --suggest`. Entries decayed 90+ days with zero retrievals. Manual confirmation only. |
| Confidence Recalibration | v0.5 | Frequently retrieved entries get confidence boost. Deeply decayed entries get confidence lowered. |

---

## 15. Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Decay model | `MAX(created_at, last_retrieved_at)` | Simple. Deterministic. No tuning parameters. |
| Decay curve | Not in v0.2 | Start simple. Add complexity only with evidence. |
| What refreshes | Restore inclusion only | Prevents casual browsing from defeating decay. |
| Schema location | `knowledge_stats` table | Keeps `knowledge` table clean. No FTS trigger impact. |
| Search affected? | No | Search is relevance-based, not freshness-based. |
| Deletion? | Never | Decay is ranking, not garbage collection. |
| Existing data | `NULL = created_at` | Backward compatible. No backfill. |
| `retrieval_count` in ranking | Never | Timestamp freshness is more meaningful than count. |

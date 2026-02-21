# Momento — Deterministic State Recovery for AI Coding Agents

## Product Requirements Document

**Version:** 0.9
**Date:** February 21, 2026
**Status:** Ready for Implementation

---

## 1. The One Moment of Magic

Agent forgets. Agent remembers.

You're deep into a multi-file implementation with Claude Code. Context errors out. `/compact` fails. You `/clear`. A blank session stares back.

You type: "I just cleared, what was I working on?"

Claude Code calls `retrieve_context`. In under two seconds, it gets back compressed directives — your active task state, key decisions, known gotchas. It picks up where you left off. You didn't re-explain anything.

**That's the entire product for v0.1.**

Not pattern mining. Not CI promotion. Not cross-agent exports. Not autonomous wisdom.

Just: the agent lost its brain. Restore it.

Everything else earns its way in later.

---

## 2. Problem Statement

Modern AI coding agents accumulate valuable context during sessions — architectural decisions, implementation patterns, error resolutions, project-specific gotchas, and in-progress task state. This context is:

- **Ephemeral.** It lives in the agent's context window and is lost when the session ends, errors out, or is manually cleared. In Claude Code, `/compact` failures force `/clear`, destroying all accumulated session knowledge.
- **Siloed.** Each agent stores session history in its own proprietary format. Knowledge gained in one agent is inaccessible from another.
- **Undistilled.** Raw session logs contain the information but are too verbose for direct reuse.
- **Non-transferable.** Patterns learned in one project don't carry to the next.

Developers re-teach agents the same lessons repeatedly — across sessions, across projects, and across tools.

---

## 3. Design Philosophy

### Precision over recall

Bad memory is worse than no memory. Every design decision optimizes for:

- **Fewer entries, higher confidence.** Store what matters, not everything that happened.
- **Aggressive filtering.** When in doubt, don't store it.
- **Manual override always available.** The developer controls what goes in and what comes out.
- **Silence by default.** Momento does nothing unless called.

### Boring and reliable

Infrastructure succeeds by being predictable. Momento is:

- **Stateless.** The MCP server holds no session state. Every call is self-contained.
- **Idempotent.** Calling retrieve twice returns identical results. No side effects influence ranking.
- **Deterministic.** Ranking is hard-coded logic, not probabilistic scoring.
- **Fast.** Retrieval completes in under 500ms. If it's slower, developers abandon it.

### Developer tool, not a meta-agent

Momento does not decide what to remember. It does not inject context autonomously. It does not evolve its own knowledge. The developer is always in control. Automation earns its way in through later versions, only after the manual workflow proves indispensable.

### Independence by design

The memory layer (MCP + CLI) is fully functional without adapter compliance. Agent instruction files (CLAUDE.md, .codex_instructions.md) are an automation layer that improves cadence and ergonomics, but the system never depends on them. If an agent ignores instructions, the developer falls back to CLI. The core guarantees — deterministic restore, structured memory, cross-agent continuity — hold regardless of adapter behavior.

---

## 4. v0.1 Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        INPUTS                                │
│                                                              │
│  Developer calls log_knowledge() via MCP or CLI              │
│  Claude Code ingestion: compaction summaries + error pairs   │
│  (batch, not real-time)                                      │
└────────────────────────────┬─────────────────────────────────┘
                             ↓
┌──────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE STORE                            │
│                                                              │
│  SQLite + FTS5 (BM25 keyword search)                         │
│  One DB file: ~/.momento/knowledge.db                            │
│  No vector search in v0.1. BM25 + tag filtering is enough   │
│  to prove the core restore scenario.                         │
└──────────┬──────────────────────────────┬────────────────────┘
           ↓                              ↓
┌─────────────────────┐    ┌─────────────────────────────────┐
│     MCP SERVER      │    │           CLI                   │
│                     │    │                                 │
│  retrieve_context() │    │  momento log <content>              │
│  log_knowledge()    │    │  momento inspect                    │
│                     │    │  momento prune                      │
│  2 tools. That's it.│    │  momento ingest                     │
└─────────────────────┘    └─────────────────────────────────┘
```

---

## 5. Project Identity

A developer should never have to type a project name. Project scope is derived automatically.

### Resolution order

```
1. hash(git remote.origin.url)     — survives folder moves, works across machines
2. hash(git rev-parse --show-toplevel) — no remote? use local git root
3. hash(absolute working directory)    — not a git repo? use the path
```

**Stored alongside the hash:**
- `human_name`: `basename(git_root)` or directory name — for display in `momento inspect` and retrieval output

**Why this order:**
- `remote.origin.url` is the most stable identifier. Clone the same repo on a new machine, move the folder, rename it — project ID stays the same.
- Git root path is the fallback when there's no remote (local-only repos).
- Absolute directory hash is the fallback when there's no git repo at all.

**Implementation:**

```python
def resolve_project_id(working_dir: str) -> tuple[str, str]:
    """Returns (project_id, human_name)."""
    try:
        remote_url = run("git remote get-url origin", cwd=working_dir)
        git_root = run("git rev-parse --show-toplevel", cwd=working_dir)
        return sha256(remote_url.strip()), basename(git_root)
    except:
        pass
    try:
        # Use --git-common-dir so worktrees of the same repo share project_id
        git_common = run("git rev-parse --git-common-dir", cwd=working_dir)
        git_root = run("git rev-parse --show-toplevel", cwd=working_dir)
        return sha256(os.path.realpath(git_common).strip()), basename(git_root)
    except:
        pass
    abs_path = os.path.abspath(working_dir)
    return sha256(abs_path), basename(abs_path)

def resolve_branch(working_dir: str) -> str | None:
    """Returns current branch name, or None for detached HEAD / non-git."""
    try:
        branch = run("git branch --show-current", cwd=working_dir).strip()
        return branch if branch else None
    except:
        return None
```

**Worktree handling:** Git worktrees create separate working directories for different branches of the same repo. `--git-common-dir` finds the shared `.git` directory, ensuring all worktrees share the same `project_id`. Branch detection via `--show-current` returns the correct branch per worktree automatically.

**The MCP server resolves project_id and branch automatically.** When an agent calls `retrieve_context`, the server reads the working directory from the MCP connection context, resolves the project ID, detects the current branch, and scopes the query. The developer never sees or types a hash.

**The CLI resolves from `cwd`.** Running `momento log "..." --type gotcha` in a project directory automatically scopes to that project and tags with the current branch. An explicit `--project` flag exists as an override but should rarely be needed.

---

## 6. MCP Server

### Two tools. No more in v0.9.

- `retrieve_context`
- `log_knowledge`

No context monitoring. No session tracking. No auto-injection. No background processes.

Any additional tool in a future version must justify itself against: the agent-agnostic principle, the stateless server rule, deterministic restore ordering, and zero coupling to agent internals.

#### 6.1 `retrieve_context`

```json
{
  "name": "retrieve_context",
  "description": "Retrieve relevant knowledge for the current project. Call this after /clear, at session start, when hitting unfamiliar errors, or before implementing recurring patterns. Also callable with the shortcut: user says 'checkpoint' or 'what was I working on'.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Search query. If empty, returns active session state and top project knowledge."
      },
      "include_session_state": {
        "type": "boolean",
        "default": true,
        "description": "Include in-progress task checkpoints."
      }
    },
    "required": []
  }
}
```

**Two distinct modes of operation:**

**Restore mode** (query is empty, `include_session_state=true`):

This is not search. This is state reconstruction. Ordering is hard-coded, not BM25-ranked:

1. Most recent `session_state` entries (up to 4 surface-matching, up to 2 other)
2. Recent `plan` entries (finalized plans with rationale, up to 2)
3. High-confidence `decision` entries (up to 3, sorted by confidence then recency)
4. `gotcha` and `pattern` entries for this project (up to 4 combined)
5. Cross-project entries matching this project's tags (if any, up to 2)

**Within each tier**, entries are sorted by a 2-bit preference key:

```
ORDER BY
  (surface IN entry_tags) DESC,      -- surface match first
  (branch = current_branch) DESC,    -- branch match second
  created_at DESC,                   -- then recency
  id ASC                             -- tie-breaker: stable ordering
```

Surface outranks branch because surface reflects what you are touching right now (directory), while branch reflects why you are touching it (development mode). Directory context is more immediate.

**Two operational preference axes only. No third axis. Ever.** If something doesn't fit in surface or branch, it's semantic and belongs in tags or content. Environment, role, agent identity — none of these become sort dimensions.

**Surface-aware preference:** At restore time, the MCP server derives a surface hint from the current working directory:

| cwd contains | surface hint |
|---|---|
| `/server` or `/backend` | `server` |
| `/web` or `/frontend` | `web` |
| `/ios` | `ios` |
| `/android` | `android` |
| none of the above | `null` (no preference) |

Surface matching is a **preference, not a filter**. If no surface-matching entries exist, restore behaves exactly like it would without surface detection.

**Implementation constraints:**
- **Case-insensitive:** `/Server` and `/server` both match.
- **Directory-boundary aware:** Match on path segments, not substrings. `/observer` must not match `server`. `/webinar` must not match `web`. Check for `/server/` or path ending in `/server`.
- **Simple string matching on `cwd`** — no ML, no heuristics beyond path segment contains.

**Limitation:** Surface detection only recognizes the four patterns above. Directories like `/services/payments`, `/api`, or `/core` return `null`. This is a convenience heuristic for common monorepo layouts, not general monorepo intelligence. Projects with non-standard structures fall back to branch-only preference, which is still useful. Custom surface mappings are a v0.2 consideration.

**Branch-aware preference:** At restore time, the MCP server reads the current branch via `git branch --show-current`:

- Entries matching the current branch are preferred within each tier
- Entries from other branches are demoted but never filtered
- Detached HEAD or non-git projects: branch = null, no branch preference
- Branch renamed or deleted after entries were saved: old entries demote gracefully

Branch awareness is metadata + preference. Not isolation. Not partition. Entries from all branches remain visible. A `/server` decision from `main` outranks an `/ios` decision from your current branch because surface > branch in sort priority.

**Ordering guardrail:** Cross-project entries must never appear above project-specific durable entries, regardless of confidence score or retrieval count. The tier ordering is a hard constraint, not a suggestion. Do not boost cross-project results based on retrieval frequency — that's how determinism dies.

Hard token cap: 2000 tokens. Never truncate mid-entry.

**Restore mode always returns structure, even if empty:**

```markdown
## Active Task
No session checkpoints found for this project.

## Project Knowledge
No stored knowledge entries found.

Tip: Use log_knowledge(type="session_state") to save progress
before /compact or /clear.
```

Empty silence feels like failure. Explicit emptiness feels correct.

**Search mode** (query is provided):

- FTS5 keyword search, scoped to project + cross-project entries
- Max 10 results
- Ranked by FTS5 relevance score, filtered by project scope
- Results below relevance threshold are suppressed — returning nothing is acceptable in search mode
- Hard token cap: 2000 tokens
- **No restore ranking in search mode.** Search uses pure FTS5 relevance. No surface preference, no branch preference, no tier ordering. Search must feel like search. Restore must feel like state reconstruction. Do not leak restore semantics into search.

**Token cap enforcement:** The cap applies to the rendered markdown output, not per-entry. Implementation must:
1. Accumulate sections in priority order (per tier ordering)
2. After adding each entry, estimate token count
3. Stop before exceeding the cap
4. Never truncate an entry mid-way — either include it fully or omit it

**Token estimation:** Estimate on the rendered markdown chunk, not raw DB content. This includes section headers (`## Active Task`), metadata brackets (`[decision | server | 1d ago]`), markdown scaffolding, and blank lines. Use `len(rendered_chunk) / 4` as the approximation. This is deliberately approximate — no real tokenizer dependency needed. The 2000-token cap is a budget, not a precision target. Slight overruns are acceptable; the goal is preventing unbounded restore, not counting exact tokens.

Restore must feel intentional, not truncated. A cleanly formatted 1800-token response is better than a 2000-token response with a Historical Slice cut in half.

**Output format — the agent needs constraints, not archaeology:**

```markdown
## Active Task
[session_state | server | feature/billing-rewrite | 10m ago]
Migrating AuthService to async/await. AuthService.swift and
AuthViewModel.swift complete. ProfileService and PaymentService
remain. Hit race condition in TokenManager — resolved with actor
isolation.

## Project Knowledge

### Auth Token Refresh [gotcha | server | 3d ago]
- Always isolate TokenManager in an actor
- Race condition occurs if refresh overlaps with logout
- Validate refresh token before mutation

### API Error Handling [pattern | 1w ago]
- Centralize error mapping in NetworkClient
- Never throw raw backend errors to UI layer
- Use typed error enum, not string matching

### Keychain Storage [decision | ios | feature/billing-rewrite | 1d ago]
- Chose Keychain over UserDefaults — UserDefaults is not encrypted
- Wrapped in KeychainManager actor for thread safety

### Networking Architecture [plan | feature/billing-rewrite | 2d ago]
- Decision: Centralized NetworkClient with typed error mapping
- Rationale: Prevents inconsistent error handling across services
- Rejected: Per-service HTTP clients (duplicated retry logic)
```

Type + surface + branch + age metadata in each header helps the agent reason about relevance without Momento making that judgment. No verbose history. No narrative.

**Properties:**
- Stateless — no server-side session tracking
- Idempotent — same inputs always produce same outputs (retrieval_count is analytics-only and never influences ranking)
- Fast — under 500ms target

#### 6.2 `log_knowledge`

```json
{
  "name": "log_knowledge",
  "description": "Store a knowledge entry. Use for recording decisions, gotchas, patterns, or current task progress. When the user says 'checkpoint' or 'save progress', call this with type='session_state'.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {
        "type": "string",
        "description": "The knowledge to store. Be concise and actionable."
      },
      "type": {
        "type": "string",
        "enum": ["gotcha", "decision", "pattern", "plan", "session_state"],
        "description": "Entry type. Use session_state for task checkpoints. Use decision or plan for historical slices with rationale."
      },
      "tags": {
        "type": "array",
        "items": { "type": "string" },
        "description": "Domain tags for retrieval. E.g. ['auth', 'ios', 'keychain']."
      }
    },
    "required": ["content", "type", "tags"]
  }
}
```

**Behavior:**
- Project is auto-resolved from working directory
- Stores entry directly — no transformation, no summarization, no LLM processing
- Manual logging only: developer tells agent to log, or developer uses CLI
- `session_state` entries represent current task progress — retrievable after `/clear`

---

## 7. Retrieval Triggers

Without deterministic trigger instructions, agents won't reliably call the tools. This is where MCP lives or dies.

### Why cadence, not thresholds

The model cannot deterministically evaluate context window usage. The context meter visible in Claude Code's terminal is a UI element rendered for the human. The model itself has no reliable access to that number.

Rules like "if remaining context <= 20%, checkpoint" appear deterministic but are not enforceable. They rely on the model heuristically guessing context length. Threshold-based rules are theatrical.

Instead, Momento anchors checkpointing to observable work events:

- Completed subtask
- Significant file change (multi-file or cross-layer)
- Resolved error with concrete fix
- Finalized decision or plan
- Before manual `/compact`
- When user says "checkpoint"

The model reliably recognizes these moments. Frequent small saves are more reliable than threshold-triggered panic saves.

### Context monitoring (explicitly deferred)

Momento does not include token-based context monitoring. No `check_context()` tool.

Reading token usage from Claude's session logs would couple Momento to Claude's internal JSONL format, require model-window detection logic, risk inaccurate or stale readings, and shift Momento from memory layer to session orchestration layer. That's a different product.

If real-world usage shows cadence-based checkpointing is insufficient, context monitoring can be explored in a future version — with actual failure data, not speculation.

### Trigger instruction blocks

Each agent gets a specific instruction block defining when to call Momento's tools. These are documented in **Section 11: Agent Adapter Layer** with full instruction blocks for Claude Code (Section 11.1) and Codex 5.3 (Section 11.2).

**The "checkpoint" shortcut is critical for adoption.** If a single word reliably triggers the save, usage increases dramatically. Micro-UX matters more than architecture.

### What triggers should NOT exist in v0.1:
- Automatic retrieval on every interaction
- Background polling or monitoring
- Context window threshold detection (the model can't reliably measure this)
- Agent-initiated retrieval without developer context
- Proactive "you might want to know..." injections

---

## 8. Knowledge Store

### SQLite + FTS5. One file. Zero dependencies.

Start embarrassingly simple. Prove the restore-after-clear flow works before engineering retrieval.

**Why not vector search for v0.1:**
- BM25 keyword search is sufficient for the core restore scenario
- Error messages are lexical — exact term matching works
- Session recovery is project-scoped — tag filtering narrows the space
- High-precision entries (manual logs, compaction summaries) have predictable vocabulary
- Vector search adds an embedding model dependency, compute cost, and complexity
- Can be added later without changing the architecture

**Schema:**

```sql
CREATE TABLE knowledge (
  id TEXT PRIMARY KEY,                  -- UUIDv4. Frozen format. Do not switch to ULID or timestamp-based IDs.
  content TEXT NOT NULL,
  content_hash TEXT NOT NULL,          -- SHA256 of content, for dedup
  type TEXT NOT NULL CHECK(type IN (
    'gotcha', 'decision', 'pattern',
    'plan', 'session_state'
  )),
  tags TEXT NOT NULL,                  -- JSON array, canonicalized: sorted, deduped, lowercased. '["auth","ios"]'
  project_id TEXT,                     -- hash; null = cross-project
  project_name TEXT,                   -- human-readable display name
  branch TEXT,                         -- git branch at time of save; null if non-git or detached HEAD
  source_type TEXT NOT NULL CHECK(source_type IN (
    'manual', 'compaction', 'error_pair'
  )),
  confidence REAL NOT NULL DEFAULT 0.9,
  created_at TEXT NOT NULL,            -- ISO 8601, YYYY-MM-DDTHH:MM:SSZ, always UTC
  updated_at TEXT NOT NULL             -- ISO 8601, YYYY-MM-DDTHH:MM:SSZ, always UTC
);

-- Analytics: retrieval count in separate table to avoid FTS trigger churn
CREATE TABLE knowledge_stats (
  entry_id TEXT PRIMARY KEY REFERENCES knowledge(id) ON DELETE CASCADE,
  retrieval_count INTEGER NOT NULL DEFAULT 0
);

CREATE VIRTUAL TABLE knowledge_fts USING fts5(
  content, tags,
  content=knowledge,
  content_rowid=rowid
);

-- FTS5 sync triggers (required — content-synced FTS does not auto-update)
CREATE TRIGGER knowledge_ai AFTER INSERT ON knowledge BEGIN
  INSERT INTO knowledge_fts(rowid, content, tags)
  VALUES (new.rowid, new.content, new.tags);
END;

CREATE TRIGGER knowledge_ad AFTER DELETE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, content, tags)
  VALUES('delete', old.rowid, old.content, old.tags);
END;

CREATE TRIGGER knowledge_au AFTER UPDATE ON knowledge BEGIN
  INSERT INTO knowledge_fts(knowledge_fts, rowid, content, tags)
  VALUES('delete', old.rowid, old.content, old.tags);
  INSERT INTO knowledge_fts(rowid, content, tags)
  VALUES (new.rowid, new.content, new.tags);
END;

-- Restore mode: fast lookup of recent session state by project
CREATE INDEX idx_knowledge_project_type ON knowledge(project_id, type, created_at DESC);

-- Search mode: cross-project pattern retrieval
CREATE INDEX idx_knowledge_type_confidence ON knowledge(type, confidence DESC);

-- Dedup: exact content match prevention
-- COALESCE handles NULL project_id: SQLite treats NULLs as distinct in UNIQUE,
-- so without this, identical cross-project entries would bypass dedup.
CREATE UNIQUE INDEX idx_knowledge_content_hash ON knowledge(content_hash, COALESCE(project_id, '__global__'));

-- Schema versioning
CREATE TABLE IF NOT EXISTS momento_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT INTO momento_meta (key, value) VALUES ('schema_version', '1');
```

**Location:** `~/.momento/knowledge.db`

One file. Local. Portable. Backed up by copying one file.

**Database pragmas (set on first creation):**

```sql
PRAGMA journal_mode=WAL;        -- concurrent reads, crash-safe writes
PRAGMA synchronous=NORMAL;      -- not a bank, don't need FULL
PRAGMA busy_timeout=5000;       -- wait up to 5s if another write is in progress (set per-connection)
```

**Timestamp format:** All `created_at` and `updated_at` values use `YYYY-MM-DDTHH:MM:SSZ`. Always UTC. Always Z suffix. No local time. No timezone offsets. Consistency prevents silent sort bugs.

**Clock source:** Always generate timestamps via `datetime.utcnow()` (or equivalent) in Python at write time. Never rely on SQLite's `datetime('now')` for INSERT timestamps — clock skew between machines would corrupt cross-machine restore ordering. Use SQLite's `datetime('now')` only for decay filtering in restore queries (e.g., `created_at >= datetime('now', '-48 hours')`), where minor skew is acceptable.

**Transaction boundaries:** Every `log_knowledge()` call runs inside an explicit transaction. The sequence is: (1) check dedup, (2) INSERT into knowledge, (3) FTS trigger fires automatically, (4) INSERT into knowledge_stats. If any step fails, the entire transaction rolls back. Dedup skip returns before transaction start — no wasted work.

**Branch comparison is case-sensitive.** Branch names are exact string equality. Do not lowercase. `feature/Auth` and `feature/auth` are different branches. This matches git's behavior on case-sensitive filesystems. Surface tags are normalized (lowercased). Branch names are not. These are different rules for different things.

**Schema migrations:** Forward-only. Each migration is a single function that runs inside a transaction. If migration fails, the transaction rolls back and the server refuses to start. Better to error loudly than corrupt silently. On every MCP server startup and every CLI invocation, `momento_meta.schema_version` is checked and migrations run if needed. If `momento_meta` table or `schema_version` key is missing, treat as version 0 and run all migrations. Do not assume `momento_meta` exists — wrap creation and meta insert in a single transaction.

### Entry size limits

Agents will write bloated entries if unconstrained. Hard character limits per type, enforced at the MCP layer:

| Type          | Max characters | Rationale |
|---------------|---------------|-----------|
| session_state | 500           | Current task + next step. 3-5 sentences. |
| decision      | 800           | Decision + rationale + rejected + implications. |
| plan          | 800           | Phased plan with brief rationale. |
| gotcha        | 400           | One pitfall, one fix. |
| pattern       | 400           | One convention, one example. |

On rejection, the MCP server returns an error with the count, the limit, and a per-type hint:

```json
{
  "error": "Content too long (1247 chars). session_state limit: 500 chars.",
  "hint": "Focus on: current task, what changed, and next step."
}
```

Rejection forces the agent to compress, which produces better entries. Truncation would create entries where the "next step" gets cut off — the most important part.

**CLI bypass:** `momento log` does not enforce character limits. Manual entries are the developer's choice.

### Confidence model (static assignment, no auto-scoring)

| Source | Default Confidence | Rationale |
|---|---|---|
| Manual `log_knowledge()` | 0.9 | Developer explicitly chose to record this. Humans understand business context and long-term value. |
| Compaction summary | 0.8 | Claude Code's own judgment of what to keep under token pressure. Optimized for working memory, not global reusability. Still high-signal. |
| Error + resolution pair | 0.7 | Concrete and proven, but may be context-specific to one session. |

Human > model is a deliberate trust hierarchy. Compaction summaries optimize for "what do I need in working memory right now," not "what is globally reusable." If retrieval stats later show compaction entries outperform manual logs, adjust. But not in v0.1.

### Deduplication: exact hash only

Dedup is by `content_hash` (SHA256 of content string). If the same content is logged twice, the second insert is silently skipped via the unique index.

Near-duplicates are allowed through. FTS5 similarity thresholds are brittle — they either miss near-duplicates or suppress distinct-but-related entries. For v0.1, let near-duplicates accumulate and rely on `momento prune` for manual cleanup. Semantic deduplication is a v0.5 problem.

### Tag normalization

Tags are canonicalized on write:
1. Lowercase: `"Auth"` becomes `"auth"`
2. Trimmed: `" ios "` becomes `"ios"`
3. Deduplicated: `["auth", "auth"]` becomes `["auth"]`
4. Sorted alphabetically: `["ios", "auth"]` becomes `["auth", "ios"]`
5. JSON encoded after sorting

Canonical ordering ensures consistent `content_hash` dedup and deterministic `momento inspect` output. Without sorting, identical tag sets in different order produce different JSON strings, which would bypass exact-hash dedup for entries with identical content but differently-ordered tags.

No strict vocabulary lists. No tag policing. No auto-correction beyond the above.

### Retrieval count is analytics only

`retrieval_count` lives in the `knowledge_stats` table, not the `knowledge` table. On every retrieval hit, the stats row is upserted:

```sql
INSERT INTO knowledge_stats (entry_id, retrieval_count) VALUES (?, 1)
ON CONFLICT(entry_id) DO UPDATE SET retrieval_count = retrieval_count + 1;
```

It is **never used in ranking logic** in v0.1. This preserves the idempotency guarantee: calling retrieve twice with the same inputs always produces the same output. Retrieval count exists solely for future analysis (which entries are most valuable, candidates for promotion to CI checks).

Separate table avoids two problems: (a) `updated_at` mutation from count increments breaking recency ordering, and (b) FTS trigger churn from non-content UPDATEs to the knowledge table. The `ON DELETE CASCADE` foreign key ensures stats rows are cleaned up when entries are pruned.

---

## 9. Ingestion: Claude Code Adapter

Batch processing only. Not real-time. Runs manually or on a schedule.

```bash
momento ingest                     # ingest from current project directory
momento ingest --all               # ingest from all known Claude Code projects
```

**Source:** `~/.claude/projects/{encoded-path}/*.jsonl`

### What it extracts

| Data | How Identified | Stored As |
|---|---|---|
| Compaction summaries | Compaction boundary events in JSONL — the compressed conversation state Claude Code chose to keep | Durable knowledge, confidence 0.8 |
| Error + resolution pairs | `is_error: true` in tool results, followed by a subsequent successful approach | Durable knowledge (gotcha), confidence 0.7 |

### Compaction summary filtering

Not all compaction summaries are durable knowledge. Some are operational noise like "We updated the function signature and moved logic to ServiceLayer." That's useful in-session but not worth persisting.

**Keyword heuristic filter:** Only persist compaction summaries that contain at least one of:

```
because, decided, must, avoid, never, always, bug, race, error,
security, gotcha, pattern, chose, instead, tradeoff, constraint,
important, careful, warning
```

This is deliberately simple. It doesn't need to be smart — it just needs to avoid obvious fluff. False negatives (missing a useful summary) are acceptable. False positives (storing fluff) erode trust.

If the heuristic proves too aggressive or too loose, adjust the word list based on real usage. The filter is a single function, trivially tunable.

### Error isolation and summary

Ingestion must never crash on bad input. Each file and each line is processed independently. A malformed JSON line skips with a warning. A corrupted file skips with an error. The run continues.

On completion, print a summary:

```
Ingestion complete:
  Files processed: 12
  Files skipped: 1 (malformed)
  Lines processed: 847
  Entries stored: 23
  Lines skipped: 2 (parse error)
  Duplicates skipped: 4
```

Silent partial ingestion erodes trust. Always show what happened.

### What it does NOT extract

| Data | Why |
|---|---|
| Thinking traces | Speculative, often wrong, half-baked mid-step reasoning. Risk of preserving abandoned ideas and hallucinated rationale. Deferred to v0.5 with outcome-validation guardrails. |
| General conversation | Low signal-to-noise without LLM summarization. |
| Tool call details | Voluminous. Needs usage-informed filtering. |

---

## 10. Historical Slices — Decision Context Preservation

Momento stores outcomes and durable reasoning, not conversations. A **Historical Slice** is the structured artifact that captures this.

### What a Historical Slice is

A finalized outcome and the reasoning necessary to understand it later:
- The chosen decision or plan
- The rationale for choosing it
- Important rejected alternatives (briefly)
- Durable constraints discovered

### What a Historical Slice is not

- Full back-and-forth discussion
- Iterative brainstorming
- Temporary speculation or half-formed ideas
- Conversational history or emotional context

Raw history belongs in claude-devtools and chat logs. Momento stores conclusions.

### Recommended structure

Historical slices should follow this template when logged via `log_knowledge(type="decision")` or `log_knowledge(type="plan")`:

```
Decision: <What was chosen>

Rationale:
- <Why it was chosen>
- <Key tradeoffs>
- <Constraints discovered>

Rejected:
- <Alternative 1 and why not>
- <Alternative 2 and why not>

Implications:
- <Operational or architectural consequences>
```

Not all sections are mandatory, but structure improves retrieval quality.

### When to log a Historical Slice

Log when:
- A plan is finalized
- A decision is committed
- A constraint becomes system-defining
- A lesson is durable and reusable across sessions or projects

Do NOT log during:
- Active brainstorming
- Early exploration
- Unresolved debates
- Tentative ideas

Logging is always explicit and developer-confirmed. Momento never auto-generates Historical Slices.

### Cross-project value

Historical slices are the highest-value entries for cross-project recall. Example:

```
Decision: Used DB-backed scheduler instead of Redis queue.

Rationale:
- Redis caused eventual consistency issues under retry
- DB ensured atomic idempotent state transitions
- Simpler deployment (no Redis dependency)

Rejected:
- Redis with Lua scripting — added complexity without solving consistency
- Cron-based — insufficient granularity for job scheduling

Implications:
- All job state mutations go through single transaction
- Retry logic lives in scheduler, not in workers
```

When encountering a similar problem in a new repository, this slice provides reusable reasoning without replaying old logs.

### Guardrails

To prevent Momento from drifting toward transcript storage:

1. Raw conversation is never auto-ingested
2. Thinking traces are not stored in v0.1
3. Only compaction summaries and error-resolution pairs are ingested automatically
4. All historical slices require explicit developer confirmation
5. Retrieval suppresses low-confidence and low-relevance entries

The goal is not lossless history. The goal is **durable intent**.

---

## 11. Agent Adapter Layer

Momento's MCP surface is agent-agnostic. Behavioral integration instructions are agent-specific.

**CLAUDE.md is an enhancement layer, not a dependency.**

Momento operates in two layers:

| | Layer | Guarantee | Depends on |
|---|---|---|---|
| **1** | **Deterministic Memory Layer** | Hard | MCP + CLI only |
| **2** | **Adapter Automation** | Soft | Agent instruction compliance |

Layer 1 (the memory layer) is fully functional via `log_knowledge()`, `retrieve_context()`, and CLI commands (`momento save`, `status`, `undo`, `inspect`). It works regardless of model instruction compliance. No data corruption. No restore degradation. No cross-agent continuity loss.

Layer 2 (adapters like CLAUDE.md) improves the experience by automating checkpoint cadence, triggering restore at session start, and encouraging structured entries. If an agent ignores or partially complies with adapter instructions, the only impact is reduced automation — fewer automatic checkpoints. The developer can always fall back to manual CLI usage.

Automation improves experience. It is not a runtime dependency. The memory layer stands independently.

### The invariant core

These never change regardless of which agent connects:

- `log_knowledge()` and `retrieve_context()` — two tools, same schema
- SQLite + FTS5 storage, same DB file
- Restore mode ordering (5-tier, hard-coded)
- Search mode (FTS5 ranked, threshold-suppressed)
- Historical Slice structure
- Project identity resolution (git remote → git root → abs path)
- Confidence ordering (human > compaction > error pair)
- Hard token cap on retrieval output
- Exact-hash dedup
- Session state decay (48h restore, 7d prune, 5/24h cap)

That is the product. Everything else is integration strategy.

### What adapters control

Each agent receives a lightweight instruction block that defines:

- **Checkpoint cadence** — when to call `log_knowledge(type="session_state")`
- **Retrieval triggers** — when to call `retrieve_context()`
- **Decision logging** — when to create Historical Slices
- **Tagging conventions** — domain-relevant tag suggestions

Adapters do NOT alter retrieval ordering, ranking logic, schema, knowledge model, or confidence scores. They only alter **when** tools are called, not **how** they behave.

### Why adapters exist

Different agents have different lifecycle models:

| Agent | Lifecycle | Context loss event | Primary trigger style |
|---|---|---|---|
| Claude Code | `/clear`, `/compact`, auto-compaction | Explicit commands + system-initiated | Lifecycle-driven + cadence |
| Codex 5.3 | Session reset, context overflow, new chat | Session boundaries | Completion-driven cadence |
| Cursor | Tab close, context window fill | Implicit, no warning | Pure cadence |
| Aider | Session end, manual reset | Session boundaries | Pure cadence |

A single CLAUDE.md instruction set doesn't translate to Codex's `.codex_instructions.md` or Cursor's rules file. The triggers need to match each agent's observable events.

### The dangerous path (explicitly avoided)

If Momento starts depending on agent-specific internals, it becomes glue code:

- ❌ Parsing Claude's JSONL token counts to estimate context %
- ❌ Hooking into Codex's session resume API
- ❌ Watching Cursor's tab lifecycle events
- ❌ Running background daemons or file watchers

These create brittle coupling. When the agent changes its internals, Momento breaks.

The clean path: agents decide **when** to call. Momento decides **what** to return. Clean separation.

### 11.1 Claude Code Adapter

**Instruction file:** `CLAUDE.md` (project root)

**Lifecycle characteristics:**
- Has `/clear` (manual context reset)
- Has `/compact` (manual context compression)
- Auto-compaction fires without warning when context fills
- Writes session logs to `~/.claude/projects/{path}/*.jsonl`
- Reads `CLAUDE.md` for deterministic tool behavior

**Instruction block:**

```markdown
## Momento Context Recovery

After any significant file change, decision, or completed subtask:
  Call log_knowledge(type="session_state", tags=[<relevant domains>])
  with what was done, what was decided, and what's next.
  Keep it brief. Context can compact without warning.

At session start or after /clear:
  Call retrieve_context(include_session_state=true).
  Use the returned context to orient yourself before taking action.

When the user says "checkpoint" or "save progress":
  Call log_knowledge(type="session_state", tags=[<relevant domains>])
  with current task progress, decisions made, and remaining work.

Before /compact (when user explicitly runs it):
  Call log_knowledge(type="session_state", tags=["checkpoint"])
  with comprehensive progress summary before executing.

When encountering an unfamiliar error:
  Call retrieve_context(query="<error description>").

Before implementing a recurring pattern (auth, networking, persistence, caching):
  Call retrieve_context(query="<pattern name>").

After finalizing a significant decision or plan:
  Call log_knowledge(type="decision" or "plan", tags=[<domains>])
  with the decision, rationale, rejected alternatives, and implications.
  Use the Historical Slice structure.
```

**Claude-specific notes:**
- The "before `/compact`" rule only catches manual compaction. Auto-compaction is invisible to the model — cadence-based checkpointing is the defense.
- Claude reliably reads `CLAUDE.md` at session start. Instruction compliance is high (~90-95%) for well-worded deterministic rules.
- Batch ingestion from `~/.claude/` JSONL is a Claude-specific data source handled by `momento ingest`, not by the adapter.
- **Surface tagging:** When logging `session_state`, always include a surface tag if the working directory indicates one (e.g., `["server", "auth"]`, `["ios", "billing"]`, `["web", "ui"]`). This enables surface-aware restore in multi-session workflows.

### 11.2 Codex 5.3 Adapter

**Instruction file:** `.codex_instructions.md` (project root) or prompt injection via CLI config

**Lifecycle characteristics:**
- Large context window (~400K tokens standard, ~128K for Codex-Spark)
- No `/clear` or `/compact` equivalents
- Context loss via session reset, overflow, or new chat
- Supports `codex resume` for raw transcript continuation
- No reliable programmatic token meter exposed to model reasoning

**Instruction block:**

```markdown
## Momento Checkpointing and Context Recovery

You are paired with a local memory layer called Momento that stores
durable checkpoints, decisions, plans, and known gotchas for the
current project.

### Checkpoint Conditions

After you complete any of the following during a session:
  - A significant file change (multi-file patch or cross-layer update)
  - A resolved error with a concrete fix
  - A finalized plan or architectural decision
  - A completed subtask that meaningfully advances the main work
  - A step that would be costly to re-explain if lost

Call the MCP tool:
  log_knowledge(
    type="session_state",
    content=<concise summary of progress, decisions, remaining tasks>,
    tags=[<relevant domains>]
  )

### Save Before Risky Operations

Before any operation that might reduce internal context (large patch
application, file renames, or before leaving the session):
  log_knowledge(type="session_state", ...)

### Retrieval Triggers

At session start or after any context loss (restart, resume, new chat):
  Call retrieve_context(include_session_state=true).
  Use the returned structured directives to orient yourself before
  generating further code.

When encountering an unfamiliar error:
  Call retrieve_context(query="<error description>").

### Decision and Plan Logging

When you finalize a significant design decision or long-term plan:
  log_knowledge(
    type="decision" or "plan",
    content=<Historical Slice structure>,
    tags=[<relevant domains>]
  )

Historical Slice structure:
  Decision: <What was chosen>
  Rationale: <Why, tradeoffs, constraints>
  Rejected: <Alternatives and why not>
  Implications: <Consequences>

### Behavior Expectations

- Checkpoint on meaningful advancement only — not trivial edits
- Do not checkpoint during speculative brainstorming
- Do not rely on internal percentages or guesses about context usage
- Only checkpoint when a logical subtask completes or before known risk
```

**Codex-specific notes:**
- `codex resume` restores raw conversation history. Momento's `retrieve_context` restores distilled intent. These are complementary — use both for full recovery.
- Codex sessions tend to be longer due to the larger context window, but context loss is more abrupt when it happens (no gradual compaction).
- No equivalent of `CLAUDE.md` auto-loading — the instruction block must be injected via project config or CLI startup.
- **Surface tagging:** Same rule as Claude — include surface tags (`["ios", "auth"]`, `["server", "billing"]`) to enable surface-aware restore when switching between monorepo surfaces.

### 11.3 Future Adapters (v0.3+)

**Cursor:** Rules file integration. Pure cadence triggers (no lifecycle events). Tab close is invisible to the model — frequent checkpointing is the only defense.

**Aider:** Session-oriented. Checkpoint at session end, retrieve at session start. Aider's chat format may need a specific ingestion adapter for `momento ingest`.

**Windsurf / Continue / Other:** Same pattern — lightweight instruction block, cadence-based triggers, no dependency on internal metrics.

Each adapter is a single instruction file. No code changes to Momento's core. No schema changes. No new MCP tools. Just different words telling different agents when to call the same two tools.

### 11.4 Setup & Uninstall Contract

The `setup.sh` script is the primary installation and uninstallation interface. It handles venv creation, package installation, MCP registration, and agent adapter generation.

**Non-interactive mode:**
- `--yes` / `-y` flag auto-confirms all prompts
- When stdin is not a TTY (piped, CI, subshell), auto-defaults to yes mode
- This ensures `setup.sh` works in non-interactive environments (CI pipelines, `claude -p` subshells)

**`.momento_created` marker:**
- `setup.sh` creates `.venv/.momento_created` when it creates a new venv
- On uninstall, `.venv` is only removed if this marker exists
- Prevents accidental deletion of pre-existing virtual environments

**Uninstall behavior (`setup.sh --uninstall`):**

| Component | Removed by default | Notes |
|---|---|---|
| MCP server config | Yes | Removed from `~/.claude/settings.json` |
| CLAUDE.md adapter | Yes | `## Momento Context Recovery` section stripped |
| `.codex_instructions.md` | Yes | Deleted if present |
| pip package | Yes | `pip uninstall -y momento` |
| `.venv` directory | Only with marker | Requires `.momento_created` marker |
| `~/.momento` data dir | No | Requires explicit confirmation; `--yes` mode skips (defaults to NO) |

**Data directory protection:** The knowledge database (`~/.momento`) is never removed in `--yes` mode. This is intentional — data destruction should require explicit human confirmation, even in non-interactive contexts. Users who want to remove data must do so manually: `rm -rf ~/.momento`.

**Python utility functions:** Setup and teardown logic is implemented in `src/momento/setup_utils.py` as testable Python functions. `setup.sh` invokes these via `python3 -m momento.setup_utils <command> <path>`. This keeps the shell script thin and the logic testable.

---

## 12. CLI

```bash
# Quick status — the trust anchor
momento status
# Output:
#   Project: saas-app (from git remote)
#   Branch: feature/billing-rewrite
#   Entries: 14 (3 session_state, 5 decisions, 4 gotchas, 2 patterns)
#   Last checkpoint: 12 minutes ago
#   DB size: 48 KB
#
# If last checkpoint > 1 hour:
#   Last checkpoint: 3 hours ago ⚠

# What was the last thing saved?
momento last
# Output:
#   [session_state] 12m ago (server, feature/billing-rewrite)
#   "Refactored AuthService to use refresh rotation lock.
#    Next: add integration test."

# Quick checkpoint (defaults to session_state, tags auto-detected from cwd)
momento save "Working on auth migration. Next: test Keychain fallback."

# Log knowledge with explicit type and tags
momento log "Always use actor isolation for TokenManager" \
    --type gotcha \
    --tags auth,ios,concurrency

# Log session state checkpoint
momento log "Migrated AuthService and AuthViewModel. TokenManager race \
    condition fixed with actor isolation. ProfileService and \
    PaymentService remain." \
    --type session_state \
    --tags auth,migration

# Undo the most recent entry (project-scoped, requires confirmation)
momento undo
# Output:
#   Delete session_state from 2m ago?
#   "Refactored AuthService to use refresh rotation lock..."
#   [y/N]

momento undo --type=decision    # undo most recent decision specifically

# Inspect the knowledge base
momento inspect                              # all entries, current project
momento inspect --all                        # all entries, all projects
momento inspect --type gotcha                # filter by type
momento inspect --tags auth                  # filter by tag
momento inspect <entry-id>                   # show single entry detail

# Prune entries
momento prune <entry-id>                     # delete specific entry
momento prune --type session_state \
    --older-than 30d                         # clean old session state
momento prune --auto                         # auto-prune: delete session_state
                                             # >7d old, cap 5 per 24h per project

# Ingest from Claude Code session logs
momento ingest                               # current project
momento ingest --all                         # all projects

# Search (same engine as retrieve_context, for humans)
momento search "keychain race condition"

# Debug restore (shows tier breakdown, entries considered, budget usage)
momento debug-restore
# Output:
#   Project: saas-app (a1b2c3d4)
#   Branch: feature/billing-rewrite
#   Surface: server (from cwd /code/saas-app/server)
#
#   Tier 1 - session_state (surface+branch match):
#     [included] "Refactored AuthService..." (312 chars, ~78 tok)
#   Tier 2 - session_state (other):
#     [included] "Updated web dashboard..." (198 chars, ~50 tok)
#     [budget exceeded] "iOS billing screen..." (445 chars, ~111 tok)
#   ...
#   Total: 6 entries, ~1450 tokens (budget: 2000)
```

`momento status` is the psychological trust anchor. If a user runs it and sees entries and a recent checkpoint, they feel safe. If the last checkpoint is over an hour old, a mild warning symbol appears — not aggressive, just a signal. Trust is adoption.

`momento undo` is always project-scoped. It only deletes entries matching the current `project_id`. You don't want someone in `/ios` accidentally undoing a backend checkpoint.

`momento debug-restore` is not for users. It's for debugging restore logic — shows every entry considered, whether it was included or skipped, token estimates, and final budget usage. Makes restore fully transparent.

Project is always auto-resolved from the current working directory. Branch is always auto-detected. An explicit `--project` override flag exists but should rarely be needed.

---

## 13. The Realistic v0.1 Flow

```
1. You work in Claude Code for an hour.
   Decisions accumulate. Gotchas encountered. Architecture evolving.

2. After each significant subtask, Claude checkpoints automatically.
   "Refactored AuthService → checkpoint."
   "Fixed TokenManager race condition → checkpoint."
   These are small, frequent, and triggered by work cadence.
   Or you say "checkpoint" and Claude saves immediately.

3. Context errors out. Auto-compaction fires. Or you /clear.

4. You type: "I just cleared. What was I working on?"

5. Claude reads the CLAUDE.md instruction and calls:
   retrieve_context(include_session_state=true)

6. Momento returns structured directives:
   - Active task: what was in progress, what's done, what remains
   - Key decisions and their reasoning
   - Known gotchas for this project
   - Relevant cross-project patterns (if any)

7. Claude orients itself and continues.
   You didn't re-explain anything.
   You lost at most the work since the last checkpoint — minutes, not hours.
```

If that works consistently and feels smoother than re-explaining, v0.1 has won.

---

## 14. What Momento Is Not

- **Not a chat history viewer.** Claude-devtools does that. Momento stores distilled knowledge, not raw conversations.
- **Not a second brain.** It captures knowledge from coding sessions. It doesn't replace Obsidian or Notion.
- **Not an autonomous agent.** It doesn't decide what to remember or when to surface context.
- **Not a session orchestration layer.** It doesn't monitor context windows, parse token counts, or manage agent lifecycles. Agents decide when to call; Momento decides what to return.
- **Not a branch isolation system.** Branch-aware restore prefers entries from the current branch but never hides entries from other branches. Memory is ranked, not partitioned.
- **Not Claude-specific glue code.** The core is agent-agnostic. Claude Code is the first client, Codex is the second. Adapters are thin instruction files, not code changes.
- **Not a real-time collaboration tool.** Single developer only in v0.1.
- **Not a code search tool.** It stores reasoning *about* code, not code itself.

---

## 15. Technical Decisions

| Decision | Choice | Rationale |
|---|---|---|
| MCP surface | 2 tools | Every additional tool is a tool the agent might misuse or ignore. |
| Storage | SQLite + FTS5 | Zero-dependency, single file, battle-tested. |
| Search | BM25 only | Error messages are lexical. Session recovery is project-scoped. Vocabulary is predictable. Vectors add complexity without proving value for the core scenario. |
| Retrieval modes | Restore (hard-coded ordering with surface preference) vs Search (FTS5 ranked) | Restore is state reconstruction, not search. Session state is always surfaced first, with surface-matching entries preferred. Never buried by BM25 scoring. |
| Surface-aware restore | cwd path-matching to derive surface hint, preference not filter | Improves multi-session relevance in monorepos without session IDs or schema redesign. Falls back gracefully when no surface is detected. |
| Branch-aware restore | `git branch --show-current` captured at save time, preference not filter | Prevents cross-branch context pollution on long-lived feature branches. Surface > branch in sort priority (directory context is more immediate than development mode). Entries from all branches remain visible. Two operational axes only — no third axis ever. |
| Within-tier sort | `(surface_match DESC, branch_match DESC, created_at DESC, id ASC)` | Fully deterministic. Never reliant on row insertion order. Surface outranks branch outranks recency. |
| Entry size limits | Hard character limits per type, hard reject at MCP layer | session_state: 500, decision/plan: 800, gotcha/pattern: 400. Rejection forces agents to compress. CLI bypass for manual entries. |
| Restore budget | Per-tier quotas + 2000-token hard cap, greedy fill | Max 17 entries across all tiers. Never truncate mid-entry. Token estimate: len(content)/4. |
| Empty results | Always return structure in restore mode | Empty silence feels like failure. Explicit emptiness feels correct. |
| Distillation | None. Manual logging + filtered compaction extraction. | Clean entries first. LLM distillation adds cost, complexity, and noise. |
| Compaction filter | Keyword heuristic | Avoid storing operational fluff like "updated the function." Only persist summaries that contain decision/constraint/error language. |
| Dedup | Exact content hash | FTS5 similarity thresholds are brittle. Exact hash avoids false suppression. Near-dupes accumulate; manual prune handles it. |
| Retrieval count | Analytics only, never affects ranking | Preserves idempotency guarantee. Count exists for future promotion heuristics, not current behavior. |
| Output format | Compressed directives, hard token cap | The agent needs constraints, not history. |
| Triggers | Cadence-based agent instruction adapters + "checkpoint" shortcut | Threshold-based rules are theatrical — models can't measure context %. Cadence rules anchored to observable work events are genuinely deterministic. Same principle across all agents. |
| Context monitoring | Explicitly deferred. No `check_context()` tool. | Coupling to JSONL format, model window sizes, and flush timing shifts Momento from memory layer to session orchestration. Cadence-based checkpointing is the defense. Revisit only with real failure data. |
| Session checkpointing | Cadence-based `log_knowledge(type="session_state")` after every significant subtask | Frequent small saves beat rare panic saves. Auto-compaction can fire anytime — cadence ensures recent checkpoint always exists. |
| Session state decay | 48h restore window, 7d hard prune, max 5 per 24h per project | Session state is disposable. It survives the next `/clear`, not forever. Durable knowledge is permanent; session state decays automatically. |
| Historical slices | Structured `decision` and `plan` entries with rationale template | Captures durable reasoning without becoming a transcript store. Developer-confirmed only. |
| Project identity | Auto-derived from git remote URL hash | Developer never types a project name. Survives folder moves and machine changes. |
| Server | Stateless, idempotent, local-only | No session state. No auth. No network. One process, one DB file. |
| Agent integration | Thin instruction adapters, not code changes | Each agent gets a text instruction block defining when to call tools. No schema changes, no new tools, no coupling to agent internals. Agents decide when to call; Momento decides what to return. |
| Tag normalization | Lowercase + trim + dedup + sort on write. Canonical JSON. | Prevents tag-order variants from bypassing content hash dedup. Deterministic inspect output. |
| Token estimation | `len(rendered_chunk)/4`. Includes headers and markdown. | 2000-token cap is a budget, not a precision target. Slight overruns acceptable. |
| ID format | UUIDv4. Frozen. | Stable tie-breaker via `id ASC`. Do not switch to ULID or timestamp-based IDs — that would alter restore behavior. |
| Clock source | Python `utcnow()` for writes, SQLite `datetime('now')` for queries only | Prevents cross-machine clock skew from corrupting write ordering. |
| Branch comparison | Case-sensitive exact match | Matches git behavior. Surface tags are lowercased; branch names are not. Different rules for different things. |
| Search mode ranking | Pure FTS5 relevance, no surface/branch preference | Search is search. Restore is state reconstruction. No bleed between modes. |
| Retrieval stats | Separate `knowledge_stats` table | Avoids FTS trigger churn and `updated_at` mutation from count increments. |
| Generic metadata column | **Rejected.** No JSON blob column. | Erodes schema discipline. Encourages lazy design. Use migrations for new fields. |
| Thinking trace storage | **Rejected.** Never store model reasoning traces. | Breaks determinism, storage discipline, and log-store boundary. Momento stores distilled knowledge, not process. |
| Vector embeddings in v0.1 | **Rejected.** BM25 only. | Determinism > fuzzy recall. Vectors add embedding model dependency and non-deterministic ranking. Revisit in v0.3 when cross-project semantic recall is the bottleneck. |

---

## 16. Risks and Mitigations

### Agent doesn't reliably call retrieve_context

**Risk:** Even with CLAUDE.md instructions, the model may forget to call the tool after `/clear`.

**Mitigation:** This is a Layer 2 (adapter automation) risk, not a Layer 1 (memory layer) risk. Momento does not break if the agent forgets — no data is corrupted, restore still works deterministically, cross-agent continuity is unaffected. The only impact is a missed automatic restore. Fallback: developer manually prompts "check Momento" or runs `momento last` in the CLI. CLAUDE.md instruction is worded as a strict behavioral rule with high compliance (~90-95%), but the system is designed for the 5-10% where it doesn't fire.

### Developer doesn't checkpoint often enough

**Risk:** Context is lost because no `session_state` was logged before auto-compaction.

**Mitigation:** This is a Layer 2 risk. If adapter-driven checkpointing fails entirely, the developer still has `momento save` in the CLI. The CLAUDE.md instruction anchors checkpointing to observable work events (file changes, decisions, completed subtasks), not to context thresholds the model can't measure. The "checkpoint" one-word shortcut reduces manual friction to near-zero. Cadence-based saving means frequent small checkpoints — even if the agent misses some, the most recent one is usually only a few interactions old. Tracking is additive — partial logging degrades resolution but never corrupts state. The system degrades gracefully, never catastrophically.

### Knowledge base fills with noise

**Risk:** Compaction extraction or loose manual logging creates low-value entries.

**Mitigation:** Compaction keyword filter catches obvious fluff. Exact-hash dedup prevents identical entries. Confidence-weighted ranking in restore mode means low-confidence entries appear after high-confidence ones. `momento prune` handles manual cleanup. Growth should be slow and deliberate.

### BM25 is insufficient for semantic queries

**Risk:** Developer searches "how did we handle authentication state" and BM25 doesn't match "token refresh" or "Keychain storage."

**Mitigation:** Acceptable for v0.1. Core scenario is project-scoped restore with predictable vocabulary. Tags provide secondary matching. Vector embeddings added in v0.3 as an additive enhancement when cross-project semantic recall becomes the primary need.

### Compaction keyword filter is too aggressive or too loose

**Risk:** Good summaries are filtered out, or fluff gets through. In practice, Claude compaction summaries often say things like "Refactored AuthService to use actor isolation" — which is valuable but won't match keywords like "because" or "decided."

**Mitigation:** The word list is a single constant, trivially tunable. Start conservative (allow more through), tighten based on what `momento inspect` reveals after a week of use. Expect tuning in week 1. If compaction summaries prove to be overwhelmingly operational noise (likely 80% fluff, 15% valuable, 5% misclassified), disabling compaction ingestion entirely and relying on manual + error-pair ingestion is a valid v0.1 outcome. That would align with "precision over recall" — it's not failure, it's discipline.

### Cold start: no memory on day one

**Risk:** New user installs Momento, runs restore, gets "No checkpoints found." The tool appears broken because there's nothing in the database yet. First impression is empty.

**Mitigation:** The empty restore response is already explicit and structured (Section 6.1). `momento status` shows entry count and last checkpoint time — making the empty state visible and understandable, not mysterious. Adapter instructions encourage early checkpointing. The `momento save` shortcut makes manual first save frictionless. This is UX friction, not architectural failure — and it resolves itself within the first working session.

### Vocabulary mismatch limits BM25 search

**Risk:** Developer searches "login flow" but entries use "auth" or "authentication." BM25 can't bridge vocabulary gaps. "billing" vs "payments" is the same problem. This affects search mode, not restore mode (restore uses tier ordering, not BM25).

**Mitigation:** Acceptable for v0.1. Restore is the core scenario and doesn't use BM25. Search is a secondary feature for humans, not agents. Tag matching provides a secondary recall path. Vector embeddings in v0.3 address this directly. Do not add embeddings in v0.1 — determinism > fuzzy recall.

### Tag entropy degrades cross-project recall

**Risk:** Developers tag inconsistently — `["auth"]` sometimes, `["authentication"]` other times, `["token"]` other times. Cross-project recall depends on tag overlap, so inconsistent tagging silently breaks it.

**Mitigation:** Acceptable for v0.1. The knowledge base will be small enough that inconsistency is visible via `momento inspect`. Future versions may add tag suggestions or normalization. Not a v0.1 problem — the entropy takes time to accumulate.

### Multi-surface projects dilute restore relevance

**Risk:** In monorepos with server + iOS + Android + web, restore mode may surface session state from a different surface than the one you're currently working in. If you were last on Android token refresh and before that on backend scheduler, both appear equally.

**Mitigation:** Surface-aware tag preference. The MCP server derives a surface hint from `cwd` (e.g., path contains `/server` -> surface = "server") and prefers `session_state` entries whose tags match. Non-matching entries are demoted but not hidden. If no matching entries exist, restore behaves exactly like it would without surface detection. See Section 6.1 for the surface hint resolution table.

### Cross-branch context pollution

**Risk:** In the same repo, `main` and `feature/billing-rewrite` have radically different architectural context. Restore surfaces decisions from `main` while you're deep in a rewrite branch, creating noise or misleading context.

**Mitigation:** Branch-aware restore preference. The MCP server reads the current branch via `git branch --show-current` and prefers entries matching that branch within each restore tier. Entries from other branches are demoted but never hidden. Universal gotchas and patterns (saved on `main`) still appear when relevant, just ranked lower. This is not isolation — it's preference. Same pattern as surface awareness.

### Multi-session behavior (clarification)

Momento does not track session IDs. All sessions within the same git repository share a single `project_id`.

Multiple simultaneous agent sessions log `session_state` entries independently, share the same SQLite store, and are reconciled via surface-aware and branch-aware restore preference.

No additional schema, session tracking, or branch scoping is required. This is intentional. Momento is project memory, not session memory.

### Session state accumulates too fast under cadence-based checkpointing

**Risk:** If the agent checkpoints after every significant subtask as instructed, `session_state` entries accumulate fast. After a week of active development, there could be dozens of stale checkpoints cluttering the knowledge base. Restore mode surfaces the most recent ones, but `momento inspect` becomes noisy and pruning becomes a chore.

**Mitigation:** Automatic session state pruning. Built into the retrieval and ingestion path:

- **On retrieve:** Only surface `session_state` entries from the last 48 hours. Older session state is not deleted — just excluded from restore mode results. It remains searchable via `momento search` if needed. **This must be a SQL WHERE clause, not a Python post-filter:**

```sql
WHERE type = 'session_state'
  AND project_id = ?
  AND created_at >= datetime('now', '-48 hours')
ORDER BY created_at DESC
LIMIT 4
```

Enforce decay at query time. Keep restore deterministic in the database layer.

**Edge case: returning after 3+ days.** If no session_state entries fall within the 48h window, restore returns no session state — but durable entries (decisions, plans, gotchas, patterns) still appear. The restore isn't empty, just missing the "Active Task" section. This is technically correct and psychologically acceptable because the durable knowledge provides enough context to resume. If real usage shows 48h is too aggressive, the window is configurable via `MOMENTO_SESSION_WINDOW_HOURS` environment variable (default 48). Do not extend the default without evidence.
- **On `momento prune --auto`:** Delete `session_state` entries older than 7 days. This is a CLI command the developer runs manually or via cron, not an automatic background process.
- **On `log_knowledge(type="session_state")`:** If more than 5 `session_state` entries exist for this project within the last 24 hours, the oldest ones beyond 5 are automatically marked for cleanup on next prune.

The principle: session state is disposable by design. It exists to survive the next `/clear`, not to live forever. Durable knowledge (`decision`, `plan`, `gotcha`, `pattern`) is permanent. Session state decays.

This keeps the knowledge base clean without requiring developer discipline around pruning — the system self-manages the transient tier while the developer manages the durable tier.

---

## 17. Success Criteria

1. **After `/clear`, context recovery takes under 10 seconds** — from typing the question to Claude resuming work with full orientation.
2. **Retrieved context is relevant every time** — zero false positives. When results come back, they help. When nothing matches, the response is explicit and structured, not silent.
3. **The knowledge base stays clean** — after a month of use, `momento inspect` shows only entries the developer recognizes and values.
4. **It's faster than re-explaining** — if describing your state to the agent is quicker than Momento retrieval, the tool has failed.
5. **The developer trusts it** — no surprises, no weird injections, no "where did that come from" moments. Fully predictable.

---

## 18. Roadmap

| Phase | Prerequisite | Delivers |
|---|---|---|
| **v0.1** | — | Core loop: `log_knowledge` → `retrieve_context` → resume. SQLite + FTS5. Claude Code ingestion (filtered compaction + error pairs). CLI. Agent adapters for Claude Code + Codex 5.3. The "agent remembers" moment. |
| **v0.2** | v0.1 stable, daily use | Formal session tracking (CLI commands for explicit start/stop). CLAUDE.md export via `momento port`. Lazy watchdog (last-checkpoint-age checked on retrieve, soft reminder in output if stale, no daemon). Investigate context health signals only if cadence-based checkpointing proves insufficient with real failure data. |
| **v0.3** | Enough entries to need better search | Vector embeddings (hybrid BM25 + semantic via local model). Cursor + Aider + Windsurf adapters. Export to Cursor / Copilot / generic formats. |
| **v0.4** | Multi-agent usage, enough data | Continue integration. Promotion to CI checks (developer-approved). Retrieval analytics. |
| **v0.5** | Patterns in what gets retrieved | Thinking trace mining (with outcome validation guardrails). Auto-tracking triggers. Confidence recalibration. Semantic deduplication. Knowledge decay. |
| **v1.0** | Proven single-developer value | Team sharing. Cross-machine sync. Web UI. Plugin architecture. Code-aware embeddings. |

Each phase ships only after the previous phase is stable and trusted.

---

## 19. What Happens Next

This document is done. Further PRD iteration is procrastination disguised as rigor.

**Implementation order:**

```
1.  resolve_project_id() + resolve_branch()
    — The identity layer everything else depends on.

2.  Schema + momento_meta + migration runner
    — WAL mode, busy_timeout, synchronous=NORMAL on creation.

3.  Entry size enforcement
    — Hard reject at MCP layer, per-type limits, teaching error messages.

4.  log_knowledge() with validation
    — Tag normalization, branch capture, content hash dedup.

5.  retrieve_context() with tier quotas + token budget
    — Surface/branch preference sort, greedy fill, never truncate mid-entry.

6.  CLI trust anchors
    — status, last, save, undo, inspect, prune, debug-restore.

7.  Claude Code adapter (CLAUDE.md)
    — Cadence-based checkpoint instructions, "checkpoint" shortcut.

8.  Codex adapter (.codex_instructions.md)
    — Same principles, different instruction format.

9.  momento ingest (batch import)
    — Compaction summary extraction, error pairs, keyword filter.

10. Acceptance test:
    /clear → retrieve → verify 6 correct items, correct order, correct preference.
```

Step 10 is the product. If that works across Claude Code, Codex, two directories, and multiple sessions — ship v0.1.

If the demo feels smoother than re-explaining, this is real. If it doesn't, a week of building will teach more than another month of documents.

**Agent forgets. Agent remembers. Ship the brain.**

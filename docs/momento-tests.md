# Momento — Test Specification

> **Status:** v0.1.1 shipped. 450 tests passing, 98% coverage. Pre-push hook enforces 95% minimum.

Three parts:
1. Pre-flight gaps found and fixed before v0.1
2. v0.1 core tests (T1–T14, 84 specified)
3. v0.2 snippets tests (TS1–TS10, 62 specified)

---

## Pre-Flight Gaps

### Gap 1: FTS5 Sync Triggers Missing from Schema

The PRD defines a content-synced FTS5 table:

```sql
CREATE VIRTUAL TABLE knowledge_fts USING fts5(
  content, tags,
  content=knowledge,
  content_rowid=rowid
);
```

But content-synced FTS5 tables do NOT auto-sync. Without explicit
triggers, INSERT/UPDATE/DELETE on the `knowledge` table will not
update the FTS index. Search mode will silently return stale or
empty results.

**Required triggers (add to schema):**

```sql
-- Keep FTS index in sync with knowledge table
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
```

This is not optional. Without these, search mode is broken.

---

### Gap 2: DB Deletion / Recreation

If someone deletes `~/.momento/knowledge.db` while an agent is running,
or on a fresh machine, the next MCP call must not crash.

**Required behavior:**

On every connection open:
1. Check if DB file exists
2. If not, create it (schema + momento_meta + WAL + pragmas)
3. If yes, check schema_version, run migrations if needed
4. Set busy_timeout (per-connection)

DB creation must be idempotent. Calling `ensure_db()` twice must
not error. Use `CREATE TABLE IF NOT EXISTS` throughout.

---

### Gap 3: Ingestion Error Isolation

JSONL parsing during `momento ingest` can encounter:
- Malformed JSON lines
- Missing expected fields
- Unexpected encoding
- Corrupted files

**Required behavior:**

Each file and each line is processed independently. A bad line
skips with a warning. A bad file skips with an error. The run
continues. Never crash the entire ingest on one bad entry.

```python
for file in jsonl_files:
    try:
        for line_num, line in enumerate(file):
            try:
                entry = parse_line(line)
                process(entry)
            except Exception as e:
                warn(f"Skipped line {line_num} in {file}: {e}")
    except Exception as e:
        error(f"Skipped file {file}: {e}")
```

---

### Gap 4: `momento save` Auto-Behavior

The PRD says `momento save` is a quick checkpoint shortcut but doesn't
specify its exact behavior.

**Specification:**

```bash
momento save "Working on auth migration. Next: test Keychain fallback."
```

Behavior:
- Type: `session_state` (always, not configurable)
- Project: auto-resolved from cwd
- Branch: auto-detected from git
- Tags: auto-derived from surface detection (e.g., cwd contains
  `/server` -> tags include "server"). If no surface detected, tags
  default to `[]`.
- No required tags. Empty tags are valid for `momento save`.
- `momento log` supports explicit `--tags` for full control.
- Tag precedence: surface-derived tags are prepended, not replaced.
  If a future extension adds `--tags` to `momento save`, the result
  is `[surface_tag] + [explicit_tags]`, not one or the other.

`momento save` is the fast path. `momento log` is the precise path.

---

### Gap 5: WAL Initialization Detail

```python
def ensure_db(path: str) -> Connection:
    db_exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA busy_timeout=5000")

    if not db_exists:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        create_schema(conn)
    else:
        version = get_schema_version(conn)  # if momento_meta missing, return 0
        run_migrations(conn, version)

    return conn
```

WAL and synchronous are set once on creation (they persist in the
file). busy_timeout is set every connection (it does not persist).

If the DB file exists but is corrupted (not a valid SQLite file),
catch the exception and surface a clear error:

```
Error: ~/.momento/knowledge.db is corrupted. 
Rename or delete it to start fresh. Momento will recreate the database.
```

Do not silently overwrite a corrupted file.

---

## V1 Must-Pass Tests

Every test below must pass for v0.1 to ship. Organized by subsystem.

---

### T1: Project Identity

**T1.1 — Git remote resolution**
```
Given: cwd is inside a git repo with remote.origin.url set
When: resolve_project_id(cwd)
Then: returns hash(remote_url), basename(git_root)
```

**T1.2 — Git root fallback (no remote)**
```
Given: cwd is inside a git repo with no remote
When: resolve_project_id(cwd)
Then: returns hash(git_common_dir), basename(git_root)
```

**T1.3 — Absolute path fallback (no git)**
```
Given: cwd is not inside a git repo
When: resolve_project_id(cwd)
Then: returns hash(abs_path), basename(abs_path)
```

**T1.4 — Worktree identity unification**
```
Given: two git worktrees of the same repo at /code/app and /code/app-billing
When: resolve_project_id for each
Then: both return the same project_id
```

**T1.5 — Branch detection**
```
Given: cwd is on branch "feature/billing-rewrite"
When: resolve_branch(cwd)
Then: returns "feature/billing-rewrite"
```

**T1.6 — Detached HEAD**
```
Given: cwd is in detached HEAD state
When: resolve_branch(cwd)
Then: returns None (not empty string)
```

**T1.7 — Branch rename degradation**
```
Given: entry saved with branch "feature/x"
       branch renamed to "feature/y"
When: retrieve_context() on branch "feature/y"
Then: old entry from "feature/x" is demoted (no branch match)
      but still visible (not filtered)
      graceful degradation, not data loss
```

**T1.8 — Non-git branch**
```
Given: cwd is not inside a git repo
When: resolve_branch(cwd)
Then: returns None
```

**T1.9 — Branch comparison is case-sensitive**
```
Given: entry saved with branch "feature/Auth"
       current branch is "feature/auth"
When: retrieve_context()
Then: entry does NOT get branch-match preference
      (exact string equality, not case-insensitive)
      branch names are never lowercased
```

---

### T2: Schema + Migration

**T2.1 — Fresh DB creation**
```
Given: ~/.momento/knowledge.db does not exist
When: ensure_db() is called
Then: DB is created with all tables, indexes, triggers, momento_meta
      schema_version = 1
      journal_mode = WAL
```

**T2.2 — Idempotent creation**
```
Given: DB already exists at schema_version 1
When: ensure_db() is called again
Then: no error, no duplicate tables, version unchanged
```

**T2.3 — DB deleted mid-session**
```
Given: DB file is deleted while server is running
When: next MCP call triggers ensure_db()
Then: DB is recreated cleanly, call succeeds
```

**T2.4 — Partial schema (momento_meta missing)**
```
Given: DB exists with knowledge table but no momento_meta table
When: ensure_db()
Then: schema_version treated as 0
      migrations run cleanly
      FTS table + triggers created if missing
      momento_meta created with correct version
```

**T2.5 — Corrupted DB file**
```
Given: knowledge.db contains non-SQLite data (e.g., random bytes)
When: ensure_db()
Then: clear error message: "knowledge.db is corrupted"
      DB not silently overwritten
      process exits non-zero
```

**T2.6 — FTS5 triggers exist**
```
Given: fresh DB
When: inspect triggers
Then: knowledge_ai, knowledge_ad, knowledge_au all exist
```

---

### T3: log_knowledge (Save)

**T3.1 — Basic save**
```
Given: valid content, type="decision", tags=["auth"]
When: log_knowledge() is called
Then: entry is inserted with correct project_id, branch, timestamp (UTC Z)
      FTS index is updated (searchable immediately)
```

**T3.2 — Entry size rejection**
```
Given: content is 1200 chars, type="session_state" (limit: 500)
When: log_knowledge() is called
Then: error returned with char count, limit, and hint
      nothing is inserted
```

**T3.3 — Size limits per type**
```
Given: content at exactly the limit for each type
When: log_knowledge() for session_state(500), decision(800),
      plan(800), gotcha(400), pattern(400)
Then: all succeed (boundary test)
```

**T3.4 — Dedup by content hash**
```
Given: identical content logged twice for same project
When: second log_knowledge() is called
Then: silently skipped (no error, no duplicate)
```

**T3.5 — Tag normalization**
```
Given: tags=[" Auth ", "iOS", "  BILLING"]
When: log_knowledge() is called
Then: stored as ["auth", "billing", "ios"] (lowercased, trimmed, sorted alphabetically)
```

**T3.6 — Tag canonical ordering for dedup**
```
Given: entry A with content "X" and tags=["ios", "auth"]
       entry B with content "X" and tags=["auth", "ios"]
When: both log_knowledge() calls execute
Then: second is skipped (tags canonicalized before hash, same content_hash)
```

**T3.7 — Branch auto-capture**
```
Given: cwd is on branch "feature/x"
When: log_knowledge() is called without explicit branch
Then: entry.branch = "feature/x"
```

**T3.8 — Timestamps are UTC**
```
Given: any log_knowledge() call
When: entry is inserted
Then: created_at and updated_at match YYYY-MM-DDTHH:MM:SSZ
      (Z suffix, not +00:00, not local time)
      generated by Python utcnow(), not SQLite datetime('now')
```

**T3.9 — ID format is UUIDv4**
```
Given: any log_knowledge() call
When: entry is inserted
Then: id is valid UUIDv4 format (8-4-4-4-12 hex, version 4)
      deterministic tie-breaker via id ASC is stable
```

**T3.10 — Transaction atomicity**
```
Given: log_knowledge() call where FTS trigger would fail
       (simulated, e.g., corrupted FTS index)
When: INSERT into knowledge executes
Then: entire transaction rolls back
      knowledge table has no partial entry
      no orphaned FTS row
```

---

### T4: retrieve_context — Restore Mode (THE CORE TEST)

**T4.1 — The Restore Contract**
```
Given:
  - project_id = "abc123"
  - branch = "feature/billing"
  - cwd surface = "server"
  - DB contains:
    - 3 session_state: 2 tagged server+feature/billing, 1 tagged ios+main
    - 2 plan: 1 on feature/billing, 1 on main
    - 4 decision: 2 on feature/billing, 2 on main
    - 3 gotcha: 1 tagged server, 2 tagged ios
    - 2 pattern: no branch tag
    - 2 cross-project entries

When: retrieve_context(query=empty, include_session_state=true)

Then:
  Tier 1 (session_state): 2 server+billing entries first, then 1 ios+main
  Tier 2 (plan): billing plan first, then main plan
  Tier 3 (decision): 2 billing decisions, then main decisions (up to 3 total)
  Tier 4 (gotcha+pattern): server gotcha first, up to 4 combined
  Tier 5 (cross-project): up to 2
  Total tokens < 2000
  No entry truncated mid-content
  Within each tier: surface match > branch match > recency > id
```

**T4.2 — Empty project**
```
Given: no entries for current project
When: retrieve_context(query=empty)
Then: returns structured empty response with tip
      "No session checkpoints found for this project."
```

**T4.3 — Token budget enforcement**
```
Given: 17 entries all at max size (would exceed 2000 tokens)
When: retrieve_context()
Then: returns entries in tier order until budget exhausted
      last entry is complete (not truncated)
      lower-tier entries are omitted
      total estimated tokens <= 2100 (5% tolerance on len/4 approximation)
```

**T4.4 — Token estimation includes markdown scaffolding**
```
Given: restore output with section headers, metadata brackets, blank lines
When: token budget is calculated
Then: estimation uses len(rendered_chunk)/4, not len(raw_content)/4
      headers like "## Active Task" and metadata like
      "[decision | server | 1d ago]" are counted toward budget
```

**T4.5 — Tier 1 exhausts budget**
```
Given: Tier 1 session_state entries consume full token budget
When: retrieve_context()
Then: no Tier 2+ entries included
      greedy fill stops at budget, does not backtrack
```

**T4.6 — Session state 48h window**
```
Given: session_state entries from 1h ago, 24h ago, and 72h ago
When: retrieve_context()
Then: only 1h and 24h entries appear. 72h entry excluded.
      48h filter is SQL WHERE clause, not Python post-filter.
```

**T4.7 — Cross-project isolation**
```
Given: entries from Project A and Project B in same DB
When: retrieve_context() in Project A
Then: Project B entries only appear in Tier 5 (cross-project, tag match)
      Project B entries never appear in tiers 1-4
```

**T4.8 — Tier quota enforcement**
```
Given: 6 decisions exist for project (quota is 3)
       token budget has room for all 6
When: retrieve_context()
Then: only 3 decisions included
      quota is enforced even if budget allows more
```

**T4.9 — Surface preference over branch**
```
Given:
  - cwd surface = "server", branch = "feature/x"
  - decision A: tagged server, branch main
  - decision B: tagged ios, branch feature/x

When: retrieve_context()
Then: decision A ranks above decision B
      (surface match outranks branch match)
```

**T4.10 — Branch preference over recency**
```
Given:
  - branch = "feature/x"
  - decision A: branch feature/x, 3 days ago
  - decision B: branch main, 1 day ago
  - same surface or no surface

When: retrieve_context()
Then: decision A ranks above decision B
      (branch match outranks recency)
```

**T4.11 — Cross-project never above project entries**
```
Given: cross-project entry with high confidence, project entry with low confidence
When: retrieve_context()
Then: project entry appears first. Cross-project always in tier 5.
```

**T4.12 — Determinism (idempotency)**
```
Given: same DB state, same cwd, same branch
When: retrieve_context() called twice
Then: identical output both times
      retrieval_count increment does not affect ordering
```

**T4.13 — Determinism tie-breaker (id fallback)**
```
Given: two entries with identical created_at, identical surface match,
       identical branch match, but different id values
When: retrieve_context()
Then: entry with lower id (ASC) appears first, consistently
      no implicit rowid ordering leak
```

**T4.14 — retrieval_count does not mutate updated_at**
```
Given: entry with known updated_at
When: retrieve_context() returns that entry
Then: knowledge.updated_at is unchanged
      knowledge_stats.retrieval_count incremented
```

**T4.15 — retrieval_count in knowledge_stats, not knowledge**
```
Given: retrieval_count is incremented via knowledge_stats upsert
When: check knowledge table and FTS index
Then: no UPDATE fired on knowledge table
      no FTS delete+reinsert occurred
      knowledge_au trigger did not fire
```

---

### T5: retrieve_context — Search Mode

**T5.1 — Basic keyword search**
```
Given: entries containing "keychain", "token", "auth"
When: retrieve_context(query="keychain race condition")
Then: returns matching entries ranked by FTS5 relevance
      scoped to current project + cross-project
```

**T5.2 — FTS5 sync after insert**
```
Given: log_knowledge() just inserted an entry with "billing webhook"
When: retrieve_context(query="billing webhook")
Then: new entry appears in results (FTS trigger worked)
```

**T5.3 — FTS5 sync after delete**
```
Given: entry with "billing webhook" exists
When: entry is deleted via prune, then search for "billing webhook"
Then: deleted entry does not appear (FTS trigger worked)
```

**T5.4 — Search respects token cap**
```
Given: many matching entries
When: retrieve_context(query="auth")
Then: max 10 results, under 2000 tokens
```

**T5.5 — Search mode has no restore ranking**
```
Given: entries with surface tags and branch metadata
When: retrieve_context(query="auth") — search mode
Then: results ranked by FTS5 relevance only
      no surface preference applied
      no branch preference applied
      no tier ordering applied
      search is search, not restore
```

---

### T6: Surface Detection

**T6.1 — Basic surface matching**
```
Given: cwd = "/code/app/server/handlers"
Then: surface = "server"
```

**T6.2 — Case insensitive**
```
Given: cwd = "/code/app/Server/handlers"
Then: surface = "server"
```

**T6.3 — Directory boundary (no substring match)**
```
Given: cwd = "/code/app/observer/metrics"
Then: surface = null (not "server")
```

**T6.4 — Webinar does not match web**
```
Given: cwd = "/code/app/webinar/views"
Then: surface = null (not "web")
```

**T6.5 — No surface detected**
```
Given: cwd = "/code/app/lib/utils"
Then: surface = null
```

**T6.6 — Frontend alias**
```
Given: cwd = "/code/app/frontend/components"
Then: surface = "web"
```

**T6.7 — Nested ambiguous path**
```
Given: cwd = "/code/app/server-ios/shared"
Then: surface is deterministic (either "server" or "ios" or null,
      but always the same result for the same path)
      implementation uses first segment match in path order
```

**T6.8 — Performance at scale**
```
Given: 5,000 entries in DB for one project
When: retrieve_context()
Then: execution completes in < 500ms
      (non-strict benchmark, early detection of accidental full scans)
```

---

### T7: CLI

**T7.1 — momento status**
```
Given: project with 5 entries, last checkpoint 10m ago
When: momento status
Then: shows project name, branch, entry count by type,
      last checkpoint time, DB size
```

**T7.2 — momento status stale warning**
```
Given: last checkpoint was 3 hours ago
When: momento status
Then: shows warning indicator on last checkpoint line
```

**T7.3 — momento save**
```
Given: cwd in /code/app/server on branch main
When: momento save "Fixed webhook handler"
Then: session_state entry created with:
      project_id from git remote
      branch = "main"
      tags include "server" (from surface detection)
      content = "Fixed webhook handler"
```

**T7.4 — momento undo project-scoped**
```
Given: entries exist for project A and project B
       cwd is in project A
When: momento undo
Then: only deletes most recent entry from project A
      project B entries untouched
```

**T7.5 — momento undo confirmation**
```
Given: most recent entry exists
When: momento undo
Then: shows entry content and asks for confirmation
      does not delete without y/Y response
```

**T7.6 — momento inspect**
```
Given: project with entries of various types
When: momento inspect
Then: lists all entries for current project with type, branch,
      surface tags, age, and content preview
```

**T7.7 — momento prune --auto**
```
Given: session_state entries from 1d, 3d, 5d, and 10d ago
When: momento prune --auto
Then: 10d entry deleted. Others preserved.
      (7d threshold for auto-prune)
```

**T7.8 — momento debug-restore**
```
Given: entries across all tiers
When: momento debug-restore
Then: shows tier breakdown, entries considered per tier,
      included/skipped status, token estimates, total budget used
```

---

### T8: Concurrency

**T8.1 — WAL mode active**
```
Given: DB initialized via ensure_db()
When: PRAGMA journal_mode queried
Then: returns "wal"
```

**T8.2 — Simultaneous writes**
```
Given: two processes writing log_knowledge() at the same time
When: both INSERT
Then: both succeed (one waits via busy_timeout)
      no corruption, no lost writes
```

**T8.3 — Read during write**
```
Given: one process writing, another reading (retrieve_context)
When: simultaneous execution
Then: reader gets consistent snapshot (WAL isolation)
      no blocking, no error
```

---

### T9: Entry Size Limits

**T9.1 — MCP rejects oversized entry**
```
Given: session_state content of 501 chars
When: log_knowledge() via MCP
Then: error with count (501), limit (500), and hint
```

**T9.2 — CLI bypass**
```
Given: session_state content of 800 chars
When: momento log --type session_state "..." via CLI
Then: entry is accepted (CLI does not enforce limits)
```

**T9.3 — Rejection message includes hint**
```
Given: oversized decision entry
When: log_knowledge() via MCP
Then: error includes "Include: what was decided, why, what was rejected."
```

---

### T10: Ingestion

**T10.1 — Partial failure resilience**
```
Given: JSONL file with 10 valid entries and 2 malformed lines
When: momento ingest
Then: 10 entries stored, 2 lines skipped with warnings
      process completes successfully (does not crash)
```

**T10.2 — Summary output**
```
Given: ingestion run with mixed results
When: momento ingest completes
Then: prints summary with files processed, files skipped,
      lines processed, entries stored, lines skipped, dupes skipped
```

---

### T11: Dedup Edge Cases

**T11.1 — Cross-project dedup**
```
Given: two cross-project entries (project_id=NULL) with identical content
When: second log_knowledge() is called
Then: silently skipped (COALESCE index catches NULL dedup)
```

**T11.2 — Same content, different projects**
```
Given: identical content logged to Project A and Project B
When: both log_knowledge() calls execute
Then: both succeed (dedup is per-project, not global)
```

---

### T12: Cross-Project Tag Matching

**T12.1 — Tag intersection surfaces cross-project entry**
```
Given: Project A entry tagged ["auth","server"]
       Project B entry tagged ["auth"]
When: retrieve_context() in Project B
Then: Project A entry appears in Tier 5 (cross-project)
      only because tags intersect on "auth"
```

**T12.2 — No tag match, no cross-project**
```
Given: Project A entry tagged ["billing"]
       Project B entry tagged ["auth"]
When: retrieve_context() in Project B
Then: Project A entry does NOT appear (no tag overlap)
```

---

### T13: Cross-Agent Continuity (The Product Test)

**T13.1 — Claude saves, Codex restores**
```
Given: Claude Code calls log_knowledge() with 3 entries
When: Codex calls retrieve_context() on same project
Then: all 3 entries appear in restore. Same ordering.
      Agent identity has zero effect on results.
```

**T13.2 — Full /clear recovery cycle**
```
1. Work in Claude Code for several tasks
2. Save 2 session_state checkpoints + 1 decision + 1 gotcha
3. /clear (or simulate context loss)
4. Call retrieve_context()
5. Verify: all 4 entries returned in correct tier order
6. Verify: agent can resume work without re-explanation
```

This is the acceptance test. If this works, ship.

---

### T14: Setup & Uninstall

**T14.1 — MCP server registration creates valid claude.json** `should_pass`
```
Given: no ~/.claude.json exists
When: register_mcp_server(claude_json_path)
Then: ~/.claude.json created with valid JSON
      mcpServers.momento has absolute path to momento-mcp, empty args, PYTHONUNBUFFERED env
```

**T14.2 — MCP server unregistration preserves other servers** `should_pass`
```
Given: ~/.claude.json with momento + other_tool MCP servers
When: unregister_mcp_server(claude_json_path)
Then: momento removed, other_tool preserved
      mcpServers key still present (not empty-cleaned)
```

**T14.3 — Claude adapter idempotent add/remove** `should_pass`
```
Given: CLAUDE.md with existing content
When: add_claude_adapter() called twice, then remove_claude_adapter()
Then: adapter appears once after adds, fully removed after remove
      surrounding content preserved intact
```

**T14.4 — Uninstall cleans up all integration files** `should_pass`
```
Given: ~/.claude.json with momento, CLAUDE.md with adapter, .codex_instructions.md
When: setup.sh --uninstall --yes
Then: momento removed from ~/.claude.json
      adapter removed from CLAUDE.md
      .codex_instructions.md deleted
      pipx package uninstalled
```

**T14.5 — Venv directories untouched by pipx uninstall** `should_pass`
```
Given: .venv directory exists (with or without .momento_created marker)
When: setup.sh --uninstall --yes
Then: .venv directory is always preserved
      pipx manages its own isolated venvs, not project .venv
```

**T14.6 — --yes flag skips interactive prompts** `should_pass`
```
Given: setup.sh invoked with --yes flag
When: any confirmation prompt is reached
Then: auto-confirms without waiting for input
      does not hang or block
```

**T14.7 — Non-TTY defaults to yes** `should_pass`
```
Given: setup.sh invoked with stdin not connected to TTY (piped)
When: any confirmation prompt is reached
Then: auto-confirms without waiting for input
      same behavior as --yes flag
```

**T14.8 — Atomic JSON writes prevent corruption** `should_pass`
```
Given: valid ~/.claude.json exists
When: register_mcp_server() writes new config
Then: write uses tempfile + os.replace (atomic)
      partial writes never leave corrupted JSON
```

**T14.9 — Invalid JSON returns False without modification** `should_pass`
```
Given: ~/.claude.json contains malformed JSON (e.g., trailing comma)
When: register_mcp_server() or unregister_mcp_server() is called
Then: returns False
      file contents are unchanged (no partial overwrite)
```

---

## Test Priority

If time is tight, ship with these passing (in order):

```
MUST PASS (blocks ship):
  T2.1   Fresh DB creation
  T2.6   FTS5 triggers exist
  T3.1   Basic save
  T3.2   Entry size rejection
  T3.4   Dedup by content hash
  T3.6   Tag canonical ordering for dedup
  T4.1   The Restore Contract
  T4.2   Empty project
  T4.8   Tier quota enforcement
  T4.9   Surface > branch
  T4.12  Determinism (idempotency)
  T5.2   FTS5 sync after insert
  T6.3   Directory boundary (observer != server)
  T8.1   WAL mode active
  T13.2  Full /clear recovery cycle

SHOULD PASS (ship without, fix fast):
  T1.4   Worktree unification
  T2.4   Partial schema migration
  T2.5   Corrupted DB handling
  T3.10  Transaction atomicity
  T4.3   Token budget enforcement
  T4.5   Tier 1 exhausts budget
  T4.6   Session state 48h window
  T4.7   Cross-project isolation
  T5.5   Search mode no restore bleed
  T7.1   momento status
  T7.3   momento save
  T8.2   Simultaneous writes
  T11.1  Cross-project dedup (NULL handling)
  T14.1  MCP server registration (claude.json)
  T14.4  Uninstall cleans up integration files
  T14.5  Venv untouched by pipx uninstall
  T14.6  --yes flag skips prompts
  T14.7  Non-TTY defaults to yes
  T14.8  Atomic JSON writes
  T14.9  Invalid JSON graceful failure

NICE TO HAVE (v0.1.1):
  T1.7   Branch rename degradation
  T1.9   Branch case sensitivity
  T4.4   Token estimation includes markdown
  T4.13  Determinism tie-breaker
  T4.15  retrieval_count in knowledge_stats
  T6.7   Nested ambiguous surface
  T6.8   Performance at scale (5000 entries)
  T7.8   debug-restore
  T9.2   CLI bypass
  T10.1  Ingestion partial failure
  T12.1  Cross-project tag matching
  T14.2  Unregistration preserves other servers
  T14.3  Claude adapter idempotent add/remove
```

---

## v0.1 Summary

**Gaps found and fixed: 5 (pre-flight) + 8 (final review)**

Pre-flight:
1. FTS5 sync triggers (schema gap — search breaks without them)
2. DB deletion/recreation behavior (ensure_db idempotent)
3. Ingestion error isolation + summary logging
4. `momento save` exact auto-behavior
5. WAL initialization detail + corruption handling

Final review:
1. Transaction boundaries (explicit transaction wrapping log_knowledge)
2. Clock source (Python utcnow for writes, SQLite datetime for queries)
3. Token estimation on rendered markdown, not raw content
4. ID format frozen to UUIDv4 (stable tie-breaker)
5. Tag canonical ordering (lowercase, dedup, sort, then JSON encode)
6. Branch comparison case-sensitive (exact match, never lowercased)
7. Search mode pure FTS5 relevance (no restore ranking bleed)
8. knowledge_stats separate table (retrieval_count + COALESCE dedup)

**v0.1 spec: 84 tests across 14 subsystems** — ALL PASSING

---

# Part 2: Snippets (v0.2)

Work summary generation over existing knowledge entries. No new schema, no new entry types, no LLM. Read-only views over v0.1 data.

**57 specified tests across 10 subsystems** — ALL PASSING (implemented as 59 tests)

## Mock Data

Snippet-specific factories in `tests/mock_data.py`:

```python
def make_snippet_day() -> list[dict]:
    """A realistic day of work. Returns 14 entries."""

def make_snippet_week() -> list[dict]:
    """A realistic week. Returns 28+ entries across 5 days."""

def make_snippet_empty() -> list[dict]:
    """Entries outside today's range. Snippet should produce empty result."""

def make_snippet_session_split() -> list[dict]:
    """Designed to test accomplished/in-progress split."""

def make_snippet_durable_only() -> list[dict]:
    """Only decisions + gotchas + patterns. No session_state. No plans."""
```

---

### TS1: Time Range + Query

**TS1.1 — Today range resolution** `must_pass`
```
Given: entries at 2h ago, 5h ago, and 25h ago (yesterday)
When: generate_snippet(range="today")
Then: returns 2 entries (today only)
      25h-ago entry excluded
```

**TS1.2 — Yesterday range resolution** `must_pass`
```
Given: entries at 2h ago (today), 25h ago (yesterday), 50h ago (2 days ago)
When: generate_snippet(range="yesterday")
Then: returns 1 entry (yesterday only)
      today and 2-days-ago excluded
```

**TS1.3 — Week range resolution** `must_pass`
```
Given: entries at 1d, 3d, 6d, and 10d ago
When: generate_snippet(range="week")
Then: returns 3 entries (within 7 days)
      10d-ago entry excluded
```

**TS1.4 — Custom range** `must_pass`
```
Given: entries on Feb 18, Feb 19, Feb 20, Feb 22
When: generate_snippet(range="custom", start="2026-02-18", end="2026-02-20")
Then: returns entries from Feb 18 and Feb 19
      Feb 20 excluded (range_end is exclusive: < midnight Feb 20)
      Feb 22 excluded
```

**TS1.5 — Branch filter** `should_pass`
```
Given: 3 entries on feature/billing, 2 entries on main
When: generate_snippet(branch="feature/billing")
Then: returns 3 entries only
```

**TS1.6 — Cross-project mode** `should_pass`
```
Given: entries in project A and project B
When: generate_snippet(all_projects=True)
Then: returns entries from both projects
```

**TS1.7 — Project scoping (default)** `must_pass`
```
Given: entries in project A and project B
       cwd resolves to project A
When: generate_snippet()  # no all_projects flag
Then: returns only project A entries
```

**TS1.8 — Query ordering** `should_pass`
```
Given: multiple entries of mixed types
When: query_entries() executes
Then: results ordered by type ASC, created_at ASC
      (consistent ordering for deterministic output)
```

---

### TS2: Section Grouping

**TS2.1 — Type-to-section mapping** `must_pass`
```
Given: 1 entry of each type (session_state, decision, gotcha, pattern, plan)
When: group_entries() runs
Then: decision -> decisions section
      gotcha -> discovered section
      pattern -> patterns section
      plan -> in_progress section
      session_state -> split by recency (see TS2.2)
```

**TS2.2 — Session state split: accomplished vs in-progress** `must_pass`
```
Given: 3 session_state entries for (server, feature/billing):
       - entry A at 9:00
       - entry B at 11:00
       - entry C at 14:00 (most recent)
When: split_session_states() runs
Then: A and B -> accomplished
      C -> in_progress
      (most recent per surface+branch key = in-progress)
```

**TS2.3 — Session state split: multiple surfaces** `must_pass`
```
Given: 2 session_state for (server, main): S1 older, S2 newer
       2 session_state for (ios, main): I1 older, I2 newer
When: split_session_states() runs
Then: S1, I1 -> accomplished
      S2, I2 -> in_progress
      (independent split per surface+branch key)
```

**TS2.4 — Keyword completion override** `must_pass`
```
Given: session_state with content "Auth migration done. All handlers updated."
       This is the most recent entry for its surface+branch key.
When: split_session_states() runs
Then: entry -> accomplished (not in-progress)
      "done" keyword overrides recency
```

**TS2.5 — Keyword word boundary** `should_pass`
```
Given: session_state with content "This is unfinished work on the handler."
When: is_completed() checks the content
Then: returns False
      "unfinished" does not match "finished" (word boundary)
```

**TS2.6 — All completion keywords** `should_pass`
```
Given: 6 session_state entries, each containing one keyword:
       "done", "completed", "finished", "shipped", "merged", "resolved"
When: is_completed() checks each
Then: all 6 return True
```

**TS2.7 — Empty sections omitted** `must_pass`
```
Given: only decision entries in the time range (no session_state, gotcha, etc.)
When: group_entries() runs
Then: only decisions section has entries
      accomplished, discovered, in_progress, patterns are empty lists
      (rendering step will omit empty sections)
```

**TS2.8 — Plans always in-progress** `should_pass`
```
Given: 2 plan entries in the range
When: group_entries() runs
Then: both in in_progress section
      never in accomplished
```

---

### TS3: Markdown Rendering

**TS3.1 — Full daily markdown** `must_pass`
```
Given: the make_snippet_day() dataset (14 entries)
When: render_markdown(sections, meta)
Then: output starts with "# Momento Snippet -- <date>"
      contains "## <project_name>"
      has sections in order: Accomplished, Decisions Made, Discovered,
        Still In Progress, Conventions Established
      each entry renders as "- <content>" list item
```

**TS3.2 — Empty sections not rendered** `must_pass`
```
Given: only decisions in the range (no session_state, gotchas, etc.)
When: render_markdown() runs
Then: output contains "### Decisions Made"
      does NOT contain "### Accomplished"
      does NOT contain "### Discovered"
      does NOT contain "### Still In Progress"
      does NOT contain "### Conventions Established"
```

**TS3.3 — Empty range markdown** `must_pass`
```
Given: no entries in time range
When: render_markdown(empty sections, meta with empty=True)
Then: contains "No entries found for this time range."
      contains tip about momento save
```

**TS3.4 — Branch shown in header** `should_pass`
```
Given: branch filter applied
When: render_markdown()
Then: header includes branch name
```

**TS3.5 — Markdown is deterministic** `must_pass`
```
Given: same entries, same time range
When: render_markdown() called twice
Then: outputs are byte-identical
```

---

### TS4: Standup Rendering

**TS4.1 — Basic standup** `must_pass`
```
Given: accomplished entries + in-progress entries
When: render_standup()
Then: output has "*Yesterday:*" line with accomplished items
      output has "*Today:*" line with in-progress items
      output has "*Blockers:*" line
```

**TS4.2 — Blockers from gotchas** `should_pass`
```
Given: 2 gotcha entries in the range
When: render_standup()
Then: "*Blockers:*" line lists gotcha summaries
```

**TS4.3 — No blockers** `should_pass`
```
Given: entries but no gotchas in the range
When: render_standup()
Then: "*Blockers:* None detected."
```

**TS4.4 — Empty standup** `must_pass`
```
Given: no entries in range
When: render_standup()
Then: "*Yesterday:* No entries recorded."
      "*Today:* --"
      "*Blockers:* --"
```

**TS4.5 — Weekly standup uses "This week" / "Next week"** `should_pass`
```
Given: week range with entries
When: render_standup() with weekly meta
Then: "*This week:*" instead of "*Yesterday:*"
      "*Next week:*" instead of "*Today:*"
```

---

### TS5: Slack Rendering

**TS5.1 — Basic slack** `must_pass`
```
Given: 2 accomplished, 1 decision, 1 gotcha, 1 in-progress
When: render_slack()
Then: accomplished lines start with checkmark
      decision lines start with pin
      gotcha lines start with warning
      in-progress lines start with cycle
```

**TS5.2 — One line per item** `must_pass`
```
Given: entries with multi-line content
When: render_slack()
Then: each entry renders as exactly one line
      no embedded newlines within a slack entry line
```

**TS5.3 — Max 15 lines** `should_pass`
```
Given: 20 entries in range
When: render_slack()
Then: output has max 15 content lines (+ header)
      last line is "(+N more)" if truncated
```

**TS5.4 — Empty slack** `must_pass`
```
Given: no entries
When: render_slack()
Then: header + "(no entries for this period)"
```

**TS5.5 — Pattern emoji** `should_pass`
```
Given: 1 pattern entry
When: render_slack()
Then: line starts with pattern emoji
```

---

### TS6: JSON Rendering

**TS6.1 — JSON structure** `must_pass`
```
Given: entries across multiple types
When: render_json()
Then: output is valid JSON
      has keys: project, branch, range, sections, entry_count, empty
      sections has keys: accomplished, decisions, discovered, in_progress, patterns
```

**TS6.2 — JSON empty** `must_pass`
```
Given: no entries
When: render_json()
Then: { "empty": true, "entry_count": 0, "sections": {} }
```

**TS6.3 — JSON round-trip** `should_pass`
```
Given: entries
When: output = render_json(); parsed = json.loads(output)
Then: parsed["entry_count"] == sum of all section lengths
      parsed["empty"] == False
      parsed["range"]["start"] and ["end"] are valid ISO strings
```

---

### TS7: CLI Command

**TS7.1 — Default invocation** `must_pass`
```
Given: entries exist for today
When: `momento snippet` (no flags)
Then: prints markdown format, exit code 0
```

**TS7.2 — Format flag** `should_pass`
```
Given: entries exist
When: `momento snippet --format standup`
Then: prints standup format
```

**TS7.3 — No project detected** `should_pass`
```
Given: cwd is /tmp (no git repo)
When: `momento snippet`
Then: prints error, exit code 1
```

**TS7.4 — Empty range message** `must_pass`
```
Given: no entries for today
When: `momento snippet`
Then: prints empty-range message, exit code 0
```

**TS7.5 — Range flag parsing** `should_pass`
```
Given: entries on Feb 18 and Feb 19
When: `momento snippet --range 2026-02-18 2026-02-20`
Then: includes Feb 18 and Feb 19 entries
```

**TS7.6 — Branch flag** `should_pass`
```
Given: entries on two branches
When: `momento snippet --branch main`
Then: only main branch entries in output
```

---

### TS8: MCP Tool

**TS8.1 — generate_snippet registered** `must_pass`
```
Given: MCP server starts
When: list tools
Then: generate_snippet appears alongside log_knowledge and retrieve_context
```

**TS8.2 — Default call** `must_pass`
```
Given: entries exist for today
When: generate_snippet(range="today")
Then: returns markdown string
```

**TS8.3 — Custom range via MCP** `should_pass`
```
Given: entries in range
When: generate_snippet(range="custom", start_date="2026-02-18", end_date="2026-02-20")
Then: returns entries for Feb 18-19 only
```

**TS8.4 — Format parameter** `should_pass`
```
Given: entries exist
When: generate_snippet(format="standup")
Then: returns standup format string
```

**TS8.5 — Empty via MCP** `should_pass`
```
Given: no entries for today
When: generate_snippet(range="today")
Then: returns empty-range markdown (not error)
```

---

### TS9: Edge Cases

**TS9.1 — Only session states** `must_pass`
```
Given: 3 session_state entries, no other types
When: generate_snippet()
Then: Accomplished and Still In Progress sections render
      Decisions, Discovered, Conventions sections omitted
```

**TS9.2 — Only durable entries** `must_pass`
```
Given: 2 decisions + 1 gotcha + 1 pattern, no session_state, no plans
When: generate_snippet()
Then: Decisions, Discovered, Conventions sections render
      Accomplished and Still In Progress omitted
```

**TS9.3 — Single entry** `should_pass`
```
Given: 1 decision entry in range
When: generate_snippet()
Then: output has title + Decisions Made section only
```

**TS9.4 — Determinism across formats** `must_pass`
```
Given: same entries, same time range
When: each format rendered twice
Then: all 4 formats produce byte-identical output on repeat
```

**TS9.5 — Entries at range boundaries** `should_pass`
```
Given: entry at exactly range_start timestamp
       entry at exactly range_end timestamp
When: generate_snippet()
Then: range_start entry included (>=)
      range_end entry excluded (<)
```

**TS9.6 — Surface extraction from tags** `should_pass`
```
Given: session_state with tags ["auth", "server", "billing"]
When: split_session_states extracts surface
Then: surface = "server" (recognized keyword in tags)
```

**TS9.7 — No surface in tags** `should_pass`
```
Given: 2 session_state entries with tags ["auth", "billing"] (no surface keyword)
When: split_session_states() runs
Then: surface = None, key = (None, branch) -- still splits correctly
```

**TS9.8 — Staleness warning** `must_pass`
```
Given: Various checkpoint ages
When: generate_snippet() runs
Then:
  - Fresh checkpoint (<10 min): no staleness warning in output
  - Stale checkpoint (>=10 min): "Note: Last checkpoint was Xm ago" prepended
  - No session_state entries: no staleness warning
  - Stale + empty snippet: warning still appears
  - JSON format: staleness included as "staleness_warning" field, not text prefix
```

**TS9.9 — Gotcha deduplication** `must_pass`
```
Given: Multiple gotcha entries with identical first line but different details
When: Any format renders them
Then:
  - Identical first-line gotchas are collapsed into one entry
  - Count shown as "(×N)" suffix in text formats
  - JSON format includes "count" field when > 1
  - Unique gotchas remain separate with no count suffix
  - First-seen order preserved
```

---

### TS10: Weekly Mode

**TS10.1 — Weekly markdown has Key Moments** `must_pass`
```
Given: make_snippet_week() dataset (5 days, 28+ entries)
When: render_markdown() with weekly range
Then: output contains "### Key Moments" section
      key moments are decisions + gotchas with day labels
```

**TS10.2 — Weekly Progress section** `must_pass`
```
Given: weekly dataset with session_state entries
When: render_markdown() with weekly range
Then: "### Progress" section shows most recent session_state per surface+branch
```

**TS10.3 — Gap day handling** `should_pass`
```
Given: entries on Mon, Tue, Thu, Fri (no Wednesday)
When: render weekly snippet
Then: Wednesday does not appear in Key Moments -- just absent
```

**TS10.4 — Weekly standup** `should_pass`
```
Given: weekly dataset
When: render_standup() with weekly meta
Then: uses "This week:" / "Next week:" / "Blockers:"
```

**TS10.5 — Decisions with dates in weekly** `should_pass`
```
Given: 3 decisions across the week
When: render_markdown() weekly
Then: "### Decisions Made (3)" with date annotations
```

---

## Snippets Priority Matrix

```
MUST PASS (blocks ship) -- 29 tests:
  TS1.1-1.4, TS1.7, TS2.1-2.4, TS2.7, TS3.1-3.3, TS3.5,
  TS4.1, TS4.4, TS5.1, TS5.4, TS6.1, TS6.2, TS7.1, TS7.4,
  TS8.1, TS8.2, TS9.1, TS9.2, TS9.4, TS9.8, TS9.9, TS10.1, TS10.2

SHOULD PASS (fix within days) -- 20 tests:
  TS1.5, TS1.6, TS1.8, TS2.5, TS2.6, TS2.8, TS3.4,
  TS4.2, TS4.3, TS4.5, TS5.2, TS5.3, TS5.5, TS6.3,
  TS7.2, TS7.3, TS7.5, TS7.6, TS8.3, TS8.4

NICE TO HAVE:
  TS8.5, TS9.3, TS9.5, TS9.6, TS9.7, TS10.3, TS10.4, TS10.5
```

---

## Overall Summary

**v0.1.1: 450 tests passing, 98% coverage. Pre-push hook enforces 95% minimum.**

| Subsystem | Spec | Prefix | Status |
|-----------|------|--------|--------|
| v0.1 Core (T1–T14) | 84 tests | T | ALL PASSING |
| v0.2 Snippets (TS1–TS10) | 68 tests | TS | ALL PASSING |
| Check-stale CLI | 5 tests | — | ALL PASSING |
| Hook registration | 22 tests | — | ALL PASSING |
| Additional coverage | 264 tests | — | ALL PASSING |
| **Total** | **450 tests** | | **98% coverage** |

# Momento

**Deterministic State Recovery for AI Coding Agents**

Momento is a local memory layer that restores context when your AI coding agent forgets. After a `/clear`, session reset, or context overflow, Momento reconstructs the agent's working state in under 2 seconds — decisions made, bugs discovered, tasks in progress, and what comes next.

Zero external dependencies. SQLite-backed. Works with any AI coding agent.

---

## Quick Start

```bash
git clone <repo-url> && cd momento
./setup.sh
source .venv/bin/activate
momento status
```

---

## Installation

### Automated (Recommended)

```bash
./setup.sh            # Creates .venv, installs package + dev deps
./setup.sh --user     # Install to user site-packages (no venv)
./setup.sh --global   # Install to current Python environment (no venv)
./setup.sh --check    # Verify existing installation
```

### Manual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Requirements

- Python 3.11+
- No runtime dependencies (sqlite3 is in the standard library)
- Dev: pytest >= 8.0, pytest-xdist >= 3.5

### Verify

```bash
momento status          # Should show project info
pytest tests/ -q        # Should show 198 passed
```

---

## CLI Reference

All commands auto-detect your project, branch, and surface from the current working directory.

**Global flags:**
- `--db <path>` — Override database path (default: `~/.momento/knowledge.db`)
- `--dir <path>` — Override working directory for project detection (default: `.`)

### `momento status`

Show project health: entry counts by type, DB size, last checkpoint age.

```bash
momento status
```

### `momento save "<content>"`

Quick session checkpoint. Type is always `session_state`. Surface and branch are auto-detected.

```bash
momento save "Migrated AuthService to async. Next: update payment handlers."
momento save "Fixed race condition in TokenManager" --tags auth,concurrency
momento save "Billing checkout working" --surface server
```

| Flag | Description |
|------|-------------|
| `--tags <csv>` | Comma-separated tags (auto-includes detected surface) |
| `--surface <name>` | Override auto-detected surface |

### `momento log "<content>" --type <type>`

Log any knowledge entry with explicit type control.

```bash
momento log "Chose Stripe Checkout over Elements for PCI scope reduction" \
  --type decision --tags billing,stripe

momento log "iOS Keychain: kSecAttrAccessible must be WhenUnlocked for background refresh" \
  --type gotcha --tags ios,keychain

momento log "All API endpoints: validate -> authorize -> execute -> respond" \
  --type pattern --tags api,server
```

| Flag | Description |
|------|-------------|
| `--type <type>` | **Required.** One of: `session_state`, `decision`, `plan`, `gotcha`, `pattern` |
| `--tags <csv>` | Comma-separated tags |

### `momento undo`

Delete the most recent entry from the current project. Prompts for confirmation.

```bash
momento undo
```

### `momento inspect`

List all entries for the current project.

```bash
momento inspect
```

### `momento prune`

Auto-prune stale session state entries (older than 7 days).

```bash
momento prune --auto
```

### `momento search "<query>"`

Full-text keyword search via FTS5 (BM25 ranking). No tier ordering — pure relevance.

```bash
momento search "keychain race condition"
momento search "stripe webhook idempotency"
```

### `momento ingest <files...>`

Ingest entries from JSONL files (e.g., Claude Code session logs).

```bash
momento ingest session1.jsonl session2.jsonl
```

Partial failures don't crash the run. Summary shows files processed, skipped, entries stored, duplicates skipped.

### `momento debug-restore`

Show the restore tier breakdown for debugging. Displays which entries land in which tier, token estimates, and what gets included vs skipped.

```bash
momento debug-restore
momento debug-restore --surface server
```

---

## How Restore Works

When an agent loses context, Momento runs a **deterministic 5-tier state reconstruction**. Same inputs always produce identical output.

| Tier | Type | Quota | Window | Purpose |
|------|------|-------|--------|---------|
| 1 | `session_state` | 4 surface + 2 other | 48 hours | What was I just working on? |
| 2 | `plan` | 2 | All time | What's the roadmap? |
| 3 | `decision` | 3 | All time | What did we decide and why? |
| 4 | `gotcha` + `pattern` | 4 combined | All time | What have we learned? |
| 5 | Cross-project | 1 | All time | Solved this elsewhere? |

### Sorting within each tier

```
surface_match DESC    -- entries tagged with your current surface first
branch_match DESC     -- entries from your current branch second
created_at DESC       -- then most recent
id ASC                -- stable tie-breaker
```

### Token budget

- **2000 tokens** total (estimated as `len(rendered_text) / 4`)
- Greedy fill: add entries until budget exhausted
- Never truncates mid-entry — include fully or skip entirely
- Tiers are processed in order; budget remaining flows to next tier

### Cross-project (Tier 5)

Only includes entries from other projects when their tags overlap with your current project's tags. Respects per-type quotas globally (a cross-project decision counts against the decision quota of 3).

---

## Entry Types & Size Limits

Size limits are enforced on MCP calls to force compression. CLI bypasses limits for manual entries.

| Type | Limit | What to include |
|------|-------|-----------------|
| `session_state` | 500 chars | Current task + what changed + next step |
| `decision` | 800 chars | What was decided + why + what was rejected |
| `plan` | 800 chars | Phases + current status + key rationale |
| `gotcha` | 400 chars | One pitfall + one fix. Be specific. |
| `pattern` | 400 chars | One convention + one example. |

---

## Surface Detection

Momento auto-detects your working surface from the current directory path. Used to rank relevant entries higher in restore.

| Path segment | Surface |
|---|---|
| `server` or `backend` | `server` |
| `web` or `frontend` | `web` |
| `ios` | `ios` |
| `android` | `android` |

**Rules:**
- Case-insensitive (`/Server` = `/server`)
- Directory-boundary aware (`/observer` does NOT match `server`)
- First match wins
- No match = `null` (no surface preference applied)

---

## Project Identity

Momento derives your project ID automatically. You never type it.

| Priority | Method | Survives |
|---|---|---|
| 1 | `SHA256(git remote origin URL)` | Folder moves, re-clones, multi-machine |
| 2 | `SHA256(git common dir path)` | Worktrees share same ID |
| 3 | `SHA256(absolute path)` | Non-git directories |

Branch: `git branch --show-current` (case-sensitive, `None` for detached HEAD).

---

## Best Practices

### When to save `session_state`
- After completing a significant subtask
- Before `/clear` or `/compact`
- Before risky operations (large refactor, branch switch)
- Keep it short: current task + what's next

### When to log `decision`
- After finalizing an architectural choice
- Include what was chosen, why, and what was rejected

### When to log `gotcha`
- After resolving a tricky bug or discovering a constraint
- One pitfall + one fix, be specific

### When to log `pattern`
- After establishing a recurring convention
- One convention + one example

### Tag conventions
- **Surfaces:** `server`, `web`, `ios`, `android`
- **Domains:** `auth`, `billing`, `networking`, `persistence`
- **Infrastructure:** `database`, `docker`, `ci-cd`
- Tags are auto-normalized: lowercased, trimmed, deduplicated, sorted alphabetically

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `MOMENTO_DB` | `~/.momento/knowledge.db` | Override database path |

### Default locations
- Database: `~/.momento/knowledge.db`
- Ingestion source: `~/.claude/projects/` (Claude Code session logs)

---

## Architecture

### Why SQLite + FTS5
- Zero external dependencies — ships with Python
- Single file — portable, easy to backup
- WAL mode — concurrent reads, crash-safe writes
- FTS5 — BM25 keyword search built in
- `busy_timeout=5000` — handles concurrent agent access

### Why deterministic
- `retrieve_context()` called twice with same state = identical output
- No probabilistic scoring, no ML, no embeddings (v0.1)
- Retrieval count is analytics-only — never affects ranking
- Hard-coded tier ordering — not learned, not adaptive

### Restore vs Search
- **Restore** (`query=None`): State reconstruction. Hard-coded tiers. Surface + branch preference. For session recovery.
- **Search** (`query="..."`): Keyword search. Pure FTS5 BM25 ranking. No restore preference. For intentional queries.

### Deduplication
- SHA256 content hash per project scope
- Same content in different projects = allowed
- `COALESCE(project_id, '__global__')` handles NULL project_id in unique index

---

## Development

### Run tests

```bash
pytest tests/ -v                    # Full suite
pytest tests/ -m must_pass -v       # Ship-blocking tests only
pytest tests/ -m should_pass -v     # Fix-within-days tests
```

### Coverage

```bash
pytest tests/ --cov=momento --cov-branch --cov-report=term-missing
# Current: 100% line + branch coverage, 198 tests
```

### Project structure

```
src/momento/
  __init__.py       # Version
  cli.py            # Argparse CLI (9 commands)
  db.py             # Schema, WAL, FTS5 triggers, migrations
  identity.py       # Git-based project resolution
  ingest.py         # JSONL batch ingestion
  models.py         # Entry/RestoreResult dataclasses, SIZE_LIMITS
  retrieve.py       # 5-tier restore + FTS5 search
  store.py          # Write path with dedup + size validation
  surface.py        # Directory-boundary surface detection
  tags.py           # Tag normalization (lowercase, sort, dedup)
  tokens.py         # Token estimation (len/4)

tests/
  conftest.py       # Fixtures: db, populated_db, insert helpers
  mock_data.py      # Factory functions for test scenarios
  test_cli.py       # CLI command tests
  test_concurrency.py
  test_continuity.py
  test_cross_project.py
  test_dedup.py
  test_identity.py
  test_ingestion.py
  test_restore.py   # Core restore contract (50+ tests)
  test_schema.py
  test_search.py
  test_size_limits.py
  test_store.py
  test_surface.py
  test_tags.py
```

---

## What Momento Is NOT

- **Not a chat history viewer** — stores distilled knowledge, not transcripts
- **Not a second brain** — use Obsidian/Notion for that
- **Not autonomous** — developer controls what's logged and retrieved
- **Not a branch isolation system** — memory is ranked by branch, not partitioned
- **Not a code search tool** — stores reasoning about code, not code itself
- **Not a collaboration tool** — single developer in v0.1

---

## Troubleshooting

### Database corrupted
```bash
rm ~/.momento/knowledge.db
# Momento recreates it on next use
```

### Entries not appearing in restore
```bash
momento debug-restore    # Shows tier breakdown and skip reasons
```

### Search returns nothing
FTS5 is keyword-based. Try exact terms from entry content. For tag-based lookup, use `momento inspect --tags <tag>`.

### CLI not found after install
```bash
source .venv/bin/activate    # If using venv
# Or: export PATH="$HOME/.local/bin:$PATH"  # If using --user
```

---

## Roadmap

| Version | Focus |
|---|---|
| **v0.1** | Core restore, CLI, FTS5 search (current) |
| v0.2 | Session tracking, CLAUDE.md export, watchdog |
| v0.3 | Vector embeddings (hybrid BM25 + semantic), multi-editor adapters |
| v0.4 | CI promotion, retrieval analytics |
| v0.5 | Thinking trace mining, auto-tracking, knowledge decay |
| v1.0 | Team sharing, cross-machine sync, Web UI |

---

*Momento — When your AI forgets, memory remains.*

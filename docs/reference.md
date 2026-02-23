# Momento -- CLI & MCP Reference

Complete reference for all CLI commands, MCP tools, configuration, and operational details.

For a quick overview, see the [README](../README.md).

---

## CLI Reference

All commands auto-detect your project, branch, and surface from the current working directory.

**Global flags:**
- `--db <path>` -- Override database path (default: `~/.momento/knowledge.db`)
- `--dir <path>` -- Override working directory for project detection (default: `.`)

### `momento status`

Show project health: entry counts by type, DB size, last checkpoint age.

```bash
momento status
```

### `momento last`

Show the most recent entry for the current project.

```bash
momento last
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
momento undo                    # Most recent entry of any type
momento undo --type=decision    # Most recent decision specifically
```

### `momento inspect`

Browse the knowledge base with filters.

```bash
momento inspect                      # All entries, current project
momento inspect --all                # All entries, all projects
momento inspect --type gotcha        # Filter by entry type
momento inspect --tags auth          # Filter by tag
momento inspect <entry-id>           # Full detail of a single entry
```

### `momento prune`

Delete entries by ID, filter, or auto-prune.

```bash
momento prune <entry-id>                          # Delete specific entry
momento prune --type session_state --older-than 30d  # Filter by type + age
momento prune --auto                              # Auto-prune session_state >7d + overflow
```

### `momento search "<query>"`

Full-text keyword search via FTS5 (BM25 ranking), scoped to the current project plus global (`project_id = NULL`) entries. No tier ordering -- pure relevance.

```bash
momento search "keychain race condition"
momento search "stripe webhook idempotency"
```

### `momento ingest [files...]`

Ingest knowledge from Claude Code session logs or explicit JSONL files. Three modes:

```bash
momento ingest                          # Current project's session logs
momento ingest --all                    # All known Claude Code projects
momento ingest session1.jsonl file2.jsonl  # Explicit JSONL files
```

Session log ingestion extracts compaction summaries and error+resolution pairs. A keyword heuristic filter keeps only entries with actionable insight (e.g., contains "decided", "bug", "avoid", "pattern").

Partial failures don't crash the run. Summary shows files processed, skipped, entries stored, duplicates skipped.

### `momento snippet`

Generate a work summary from your knowledge entries. Outputs in markdown, standup, slack, or JSON formats.

```bash
momento snippet                          # Today, markdown format
momento snippet --yesterday              # Yesterday
momento snippet --week                   # Past 7 days (weekly mode)
momento snippet --range 2026-02-17 2026-02-21  # Custom date range
momento snippet --format standup         # Standup format
momento snippet --format slack           # Slack format
momento snippet --format json            # JSON format
momento snippet --branch feature/billing # Filter by branch
momento snippet --all-projects           # Include all projects
```

| Flag | Description |
|------|-------------|
| `--yesterday` | Show yesterday's entries |
| `--week` | Show past 7 days (weekly mode with Key Moments, date annotations) |
| `--range <start> <end>` | Custom date range (YYYY-MM-DD, end is exclusive) |
| `--format <fmt>` | Output format: `markdown` (default), `standup`, `slack`, `json` |
| `--branch <name>` | Filter entries by branch |
| `--all-projects` | Include entries from all projects |

**Staleness warning:** If the last `session_state` checkpoint is older than 10 minutes, a note is prepended to the output (or included as a `staleness_warning` field in JSON format) suggesting you run `momento save` first.

### `momento check-stale`

Check if the last checkpoint is older than a threshold. Used by hooks to enforce checkpoint freshness.

```bash
momento check-stale              # Default threshold: 30 min
momento check-stale --minutes 10 # Custom threshold
```

Exits with code 0 if fresh, code 1 if stale or no checkpoint exists.

### `momento debug-restore`

Show the restore tier breakdown for debugging. Displays which entries land in which tier, token estimates, and what gets included vs skipped.

```bash
momento debug-restore
momento debug-restore --surface server
```

---

## MCP Server

Momento exposes three MCP tools for AI coding agents. The server is stateless -- each call auto-resolves project, branch, and surface from the working directory.

### Setup

Register Momento as an MCP server (handled automatically by `./setup.sh`):

**Claude Code** (`~/.claude.json` -- NOT `~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "momento": {
      "command": "/Users/you/.local/bin/momento-mcp",
      "args": [],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

> **Note:** `setup.sh` automatically resolves the absolute path to `momento-mcp` and writes it to `~/.claude.json`. Using the absolute path ensures Claude Code finds the binary regardless of its shell PATH.

### Tools

#### `retrieve_context`

Retrieve relevant knowledge for the current project. Two modes:
- **Restore mode** (empty query): Deterministic 5-tier state reconstruction
- **Search mode** (query provided): FTS5 keyword search

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | `""` | Search query. Empty = restore mode. |
| `include_session_state` | boolean | `true` | Include in-progress task checkpoints. |

#### `log_knowledge`

Store a knowledge entry.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The knowledge to store. Be concise and actionable. |
| `type` | string | Yes | One of: `session_state`, `decision`, `plan`, `gotcha`, `pattern` |
| `tags` | array | Yes | Domain tags. E.g. `["auth", "ios", "keychain"]` |

#### `generate_snippet`

Generate a work summary for a date range and format.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `range` | string | `"today"` | One of: `today`, `yesterday`, `week` |
| `start_date` | string | `null` | Custom range start (YYYY-MM-DD). Overrides `range`. |
| `end_date` | string | `null` | Custom range end (YYYY-MM-DD, exclusive). |
| `format` | string | `"markdown"` | One of: `markdown`, `standup`, `slack`, `json` |

### Running Manually

```bash
momento-mcp    # Starts stdio MCP server
```

### Agent Adapters

Setup script can generate instruction files for:
- **Claude Code**: Appends checkpoint/retrieval rules to `~/.claude/CLAUDE.md`
- **Codex**: Generates `.codex_instructions.md` in your project root

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

Surface is detected from **mapped directory keywords** in the path under the git root. Only recognized keywords produce a surface -- unmapped directories return `null`.

| Directory Keyword | Surface |
|-------------------|---------|
| `server`, `backend` | `server` |
| `web`, `frontend` | `web` |
| `ios` | `ios` |
| `android` | `android` |

```
/Users/tom/myproject/server/api/routes.py    ->  surface = "server"
/Users/tom/myproject/backend/jobs/worker.py  ->  surface = "server"
/Users/tom/myproject/frontend/app/page.tsx   ->  surface = "web"
/Users/tom/myproject/ios/Sources/App.swift   ->  surface = "ios"
/Users/tom/myproject/src/main.py             ->  surface = null (unmapped)
/Users/tom/myproject/                        ->  surface = null (at root)
```

**Rules:**
- Scans all path segments under git root for mapped keywords
- Case-insensitive (`/Server` -> `server`, `/FrontEnd` -> `web`)
- Hidden directories (starting with `.`) are skipped
- At project root -> `null` (no surface preference applied)
- Surface is a preference signal for ranking, never a filter

---

## Project Identity

Momento derives your project ID automatically. You never type it.

| Priority | Method | Survives |
|----------|--------|----------|
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
- **Surfaces:** mapped directory keywords (`server`/`backend`, `web`/`frontend`, `ios`, `android`)
- **Domains:** `auth`, `billing`, `networking`, `persistence`
- **Infrastructure:** `database`, `docker`, `ci-cd`
- Tags are auto-normalized: lowercased, trimmed, deduplicated, sorted alphabetically

---

## Architecture

### Why SQLite + FTS5
- Zero external dependencies -- ships with Python
- Single file -- portable, easy to backup
- WAL mode -- concurrent reads, crash-safe writes
- FTS5 -- BM25 keyword search built in
- `busy_timeout=5000` -- handles concurrent agent access

### Why deterministic
- `retrieve_context()` called twice with same state = identical output
- No probabilistic scoring, no ML, no embeddings (v0.1)
- Retrieval count is analytics-only -- never affects ranking
- Hard-coded tier ordering -- not learned, not adaptive

### Restore vs Search
- **Restore** (`query=None`): State reconstruction. Hard-coded tiers. Surface + branch preference. For session recovery.
- **Search** (`query="..."`): Keyword search. Pure FTS5 BM25 ranking. No restore preference. For intentional queries.

### Deduplication
- SHA256 content hash per project scope
- Same content in different projects = allowed
- `COALESCE(project_id, '__global__')` handles NULL project_id in unique index

---

## What Momento Is NOT

- **Not a chat history viewer** -- stores distilled knowledge, not transcripts
- **Not a second brain** -- use Obsidian/Notion for that
- **Not autonomous** -- developer controls what's logged and retrieved
- **Not a branch isolation system** -- memory is ranked by branch, not partitioned
- **Not a code search tool** -- stores reasoning about code, not code itself
- **Not a collaboration tool** -- single developer in v0.1

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

### CLI or MCP command not found after install
```bash
export PATH="$HOME/.local/bin:$PATH"
# and restart your shell if needed
```

---

## Installation Details

### Automated (Recommended)

```bash
./setup.sh            # Standard install via pipx
./setup.sh --check    # Verify existing installation
```

### Manual

```bash
pipx install .
# for local development from repo checkout:
pipx install --force .
```

### Uninstall

```bash
./setup.sh --uninstall        # Interactive: confirms each step
./setup.sh --uninstall --yes  # Non-interactive: removes everything except data
```

Removes: pipx package, MCP config, CLAUDE.md adapter, .codex\_instructions.md.

To also remove your knowledge database:

```bash
rm -rf ~/.momento
```

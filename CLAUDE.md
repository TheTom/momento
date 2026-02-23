# Momento — Developer Guide

Deterministic state recovery for AI coding agents. Local SQLite memory layer that restores working context in <2 seconds.

**Status:** v0.1.0 shipped, dogfood phase. Snippets (v0.2) implemented.

## Quick Start

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Run must_pass only
pytest tests/ -m must_pass -v

# Run with coverage
pytest tests/ --cov=momento --cov-report=term-missing

# CLI smoke test
momento status
momento snippet
```

## Project Structure

```
src/momento/
  cli.py           # 12-command argparse CLI
  mcp_server.py    # MCP server (3 tools: retrieve_context, log_knowledge, generate_snippet)
  db.py            # SQLite schema, WAL, FTS5 triggers, migrations
  retrieve.py      # 5-tier deterministic restore + FTS5 search
  store.py         # Write path with content-hash dedup + size validation
  snippet.py       # Work summary generation (markdown, standup, slack, json)
  identity.py      # Git-based project/branch resolution
  surface.py       # Surface detection (server, web, ios, android)
  models.py        # Entry/RestoreResult dataclasses, SIZE_LIMITS, ENTRY_TYPES
  tags.py          # Tag normalization (lowercase, sort, dedup)
  tokens.py        # Token estimation (len/4), relative age formatting
  ingest.py        # JSONL batch ingestion + Claude Code session log extraction
  setup_utils.py   # MCP registration, CLAUDE.md adapter, hook management

tests/
  conftest.py      # Shared fixtures: db, populated_db, git repos, insert helpers
  mock_data.py     # Factory functions: make_entry(), make_snippet_day/week/empty/etc.
  test_restore.py  # Core 5-tier restore contract (largest test file)
  test_snippet_*.py # 10 files covering snippets (query, grouping, rendering, CLI, MCP, edge)
  ...              # 27 test files total, 410+ tests, 98% coverage
```

## Architecture

### Core Contract: 5-Tier Restore

Same inputs always produce identical output. No randomness, no LLM.

| Tier | Type | Quota | Window | Purpose |
|------|------|-------|--------|---------|
| 1 | session_state | 4 surface + 2 other | 48h | Current task |
| 2 | plan | 2 | All time | Roadmap |
| 3 | decision | 3 | All time | Why we decided |
| 4 | gotcha + pattern | 4 combined | All time | Lessons learned |
| 5 | Cross-project | 2 | All time | Reuse solutions |

Token budget: 2000 tokens. Never truncates mid-entry.

### Entry Types

`session_state`, `plan`, `decision`, `gotcha`, `pattern` — defined in `models.ENTRY_TYPES`.

### Database

SQLite at `~/.momento/knowledge.db` (override with `MOMENTO_DB` env var). FTS5 for search. WAL mode for concurrent reads.

### Entry Points

- `momento` → `momento.cli:main` (CLI)
- `momento-mcp` → `momento.mcp_server:main` (MCP server)

## Test Patterns

### Fixtures (conftest.py)

- `db` — fresh in-memory SQLite with full schema. Use for most tests.
- `populated_db` — pre-loaded with full restore scenario (T4.1).
- `insert_entries(conn, entries)` — batch insert helper. Always use this, not raw SQL.

### Mock Data (mock_data.py)

- `make_entry(content, type, tags, branch, created_at, ...)` — single entry factory
- `make_snippet_day()` — 14 entries for a realistic day
- `make_snippet_week()` — 30 entries across 5 days
- `hours_ago(n)` / `days_ago(n)` — time helpers returning ISO strings

### Markers

- `@pytest.mark.must_pass` — blocks ship
- `@pytest.mark.should_pass` — fix within days
- `@pytest.mark.nice_to_have` — future improvement

### CLI Tests

Use `SimpleNamespace` for args, call `cmd_*()` directly, capture output with `capsys`.

### MCP Tests

Use `@patch` decorators for `identity`, `surface`, `db`. Pass real test db via `mock_db.return_value = db`.

## Conventions

### License Header (required on every new file)

```python
# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0
```

Shell scripts: place after the shebang line.

### Code Style

- Python 3.11+ (use `python3`, never `python`)
- Type hints on all public functions
- Dataclasses over dicts for structured data
- No external runtime dependencies beyond `mcp>=1.0`
- Deterministic behavior — no randomness, no probabilistic scoring

### Git

- Co-author commits: `Co-Authored-By: tturney@psyguard.ai`
- Commit messages: imperative mood, concise, explain "why" not "what"

### Testing

- Tests first (red-green workflow preferred)
- 98% coverage target
- Every new module gets a corresponding test file
- Use existing factories in mock_data.py — don't write raw SQL in tests

## CLI Commands

```
momento status          # Project health, entry counts, checkpoint age
momento last            # Most recent entry
momento save "<msg>"    # Quick session checkpoint
momento log "<msg>" --type <type>  # Log with explicit type
momento undo            # Delete most recent entry
momento inspect         # Browse entries with --type/--tags/--all filters
momento prune           # Delete by ID, filter, or --auto
momento search "<q>"    # FTS5 keyword search
momento snippet         # Work summary (--yesterday, --week, --format)
momento ingest          # Import Claude Code session logs
momento check-stale     # Checkpoint freshness check (for hooks)
momento debug-restore   # Show restore tier breakdown
```

## Setup & Installation

```bash
./setup.sh              # Interactive install (pipx)
./setup.sh --check      # Verify installation
./setup.sh --uninstall  # Clean removal
```

Setup registers: MCP server in Claude Code + Codex, CLAUDE.md adapter, checkpoint hooks in `~/.claude/settings.json`.

## Key Files for Common Tasks

| Task | Start Here |
|------|-----------|
| Add new entry type | `models.py` → `store.py` → `retrieve.py` |
| Add CLI command | `cli.py` (add cmd_*, subparser, dispatch entry) |
| Add MCP tool | `mcp_server.py` (add @server.tool function) |
| Change restore behavior | `retrieve.py` (tier logic) |
| Add snippet format | `snippet.py` (add render_* function) |
| Modify DB schema | `db.py` (add migration in ensure_db) |
| Add test factories | `mock_data.py` |

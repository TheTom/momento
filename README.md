# Momento

**Deterministic State Recovery for AI Coding Agents**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests: 450 passing](https://img.shields.io/badge/tests-450_passing-brightgreen.svg)](tests/)
[![Coverage: 98%](https://img.shields.io/badge/coverage-98%25-brightgreen.svg)](tests/)

---

## Status

**v0.1.2 shipped. In dogfood.** Snippets (v0.2) landed — work summaries in markdown, standup, slack, and JSON formats with staleness warnings when checkpoints are stale. Checkpoint enforcement hooks mechanically guarantee context is saved before sessions end. Pre-push hook gates all pushes on license headers, passing tests, and 95% coverage. 454 tests, 98% coverage. Currently testing across Codex and Claude Code in daily driver workflows.

**v0.1.2 fixes:**
- **FTS5 search**: Multi-word queries now use OR semantics instead of implicit AND — entries matching *any* search term are returned, then ranked by relevance overlap. Previously, searching "rsync deploy gotchas" required ALL words present in a single entry.
- **MCP error messages**: `log_knowledge` now validates entry type upfront and returns specific constraint errors (e.g., `"Invalid type: 'knowledge'. Valid types: session_state, decision, plan, gotcha, pattern"`) instead of the opaque `"Integrity constraint violation during insert."`

---

## The Problem

AI coding agents forget. Every `/clear`, context overflow, or new session wipes the slate. You spend 5-10 minutes re-explaining architecture, decisions, constraints, and the bug you just fixed.

## The Solution

Momento is a local memory layer that restores your agent's working state in under 2 seconds. Decisions made, bugs discovered, tasks in progress, and what comes next -- all reconstructed from a single SQLite database. No cloud. No external dependencies. No magic.

---

## How It Works

After a context reset, the agent calls `retrieve_context()`. Momento returns structured directives -- not chat history, not raw logs, but distilled intent:

```
retrieve_context(include_session_state=true)
```

```markdown
## Active Task
[session_state | server | feature/billing-rewrite | 10m ago]
Migrating AuthService to async/await. AuthService.swift and
AuthViewModel.swift complete. ProfileService and PaymentService
remain. Hit race condition in TokenManager -- resolved with actor
isolation.

## Project Knowledge

### Auth Token Refresh [gotcha | server | 3d ago]
- Always isolate TokenManager in an actor
- Race condition occurs if refresh overlaps with logout
- Validate refresh token before mutation

### Keychain Storage [decision | ios | 1d ago]
- Chose Keychain over UserDefaults -- UserDefaults is not encrypted
- Wrapped in KeychainManager actor for thread safety
```

The agent picks up where it left off. You didn't re-explain anything.

---

## Key Features

- **Deterministic 5-tier restore** -- same inputs always produce identical output, no probabilistic scoring
- **SQLite + FTS5** -- zero external dependencies, single file, BM25 keyword search built in
- **MCP integration** -- three tools (`retrieve_context`, `log_knowledge`, `generate_snippet`), works with any MCP-compatible agent
- **12-command CLI** -- full control over your knowledge base from the terminal
- **Work summaries (Snippets)** -- generate daily/weekly summaries in markdown, standup, slack, or JSON
- **Checkpoint enforcement** -- hooks block session end if no checkpoint in 30+ min, auto-remind on resume
- **Cross-agent continuity** -- Claude Code saves, Codex restores (or any combination)
- **Surface-aware ranking** -- working in `/server`? Server entries rank first automatically
- **Branch-aware preference** -- entries from your current branch are preferred, never filtered
- **Session state decay** -- temporary checkpoints expire; durable knowledge persists forever

---

## Quick Start

```bash
pipx install .
momento status
```

For full setup including MCP server registration and agent adapters:

```bash
./setup.sh
```

### Requirements

- Python 3.11+
- pipx
- Runtime: `mcp>=1.0`

---

## CLI Overview

| Command | Description |
|---------|-------------|
| `momento status` | Project health: entry counts, DB size, last checkpoint age |
| `momento last` | Show the most recent entry |
| `momento save "<msg>"` | Quick session checkpoint (auto-detects project, branch, surface) |
| `momento log "<msg>" --type <type>` | Log any entry with explicit type control |
| `momento undo` | Delete the most recent entry (with confirmation) |
| `momento inspect` | Browse the knowledge base with filters |
| `momento prune` | Delete entries by ID, filter, or auto-prune |
| `momento search "<query>"` | Full-text keyword search (FTS5 BM25) |
| `momento snippet` | Work summary (daily/weekly, markdown/standup/slack/json) |
| `momento ingest` | Import from Claude Code session logs |
| `momento check-stale` | Checkpoint freshness check (used by hooks) |
| `momento debug-restore` | Show restore tier breakdown for debugging |

See [docs/reference.md](docs/reference.md) for full CLI reference with all flags and examples.

---

## MCP Integration

Momento exposes three MCP tools. The server is stateless -- each call auto-resolves project, branch, and surface from the working directory.

| Tool | Purpose |
|------|---------|
| `retrieve_context` | Restore mode (empty query) or FTS5 search mode (with query) |
| `log_knowledge` | Store a knowledge entry with type, content, and tags |
| `generate_snippet` | Work summary for a date range in any format |

Setup is handled by `./setup.sh`, which registers the MCP server, agent adapters, and checkpoint enforcement hooks.

See [docs/reference.md](docs/reference.md) for MCP setup details and tool schemas.

---

## How Restore Works

When an agent loses context, Momento runs a deterministic 5-tier state reconstruction. Same inputs always produce identical output.

| Tier | Type | Quota | Window | Purpose |
|------|------|-------|--------|---------|
| 1 | `session_state` | 4 surface + 2 other | 48 hours | What was I just working on? |
| 2 | `plan` | 2 | All time | What's the roadmap? |
| 3 | `decision` | 3 | All time | What did we decide and why? |
| 4 | `gotcha` + `pattern` | 4 combined | All time | What have we learned? |
| 5 | Cross-project | 2 | All time | Solved this elsewhere? |

Within each tier, entries are sorted by: **surface match > branch match > recency > id** (fully deterministic, no implicit ordering).

Token budget: 2000 tokens. Never truncates mid-entry -- include fully or skip entirely. Tiers are processed in order; budget flows to the next tier.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MOMENTO_DB` | `~/.momento/knowledge.db` | Override database path |

Default locations:
- Database: `~/.momento/knowledge.db`
- Ingestion source: `~/.claude/projects/` (Claude Code session logs)

---

## Documentation

| Document | Description |
|----------|-------------|
| [Reference](docs/reference.md) | Full CLI reference, MCP setup, entry types, surface detection, troubleshooting |
| [Architecture](docs/momento-architecture.html) | Interactive architecture visualization |
| [PRD](docs/prd-momento-final-v2.md) | Product requirements document (v0.1 shipped) |
| [Snippets PRD](docs/prd-momento-snippets.md) | Snippets feature PRD (v0.2) |
| [Test Spec](docs/momento-tests.md) | Consolidated test specification (v0.1 core + v0.2 snippets) |
| [User Journeys](docs/prd-momento-user-journeys.md) | Core user journey definitions |
| [FAQ](docs/momento-faq.md) | Frequently asked questions |
| [Docs Index](docs/README.md) | Full documentation index |

---

## Development

### Tests & Coverage

**443 tests passing. 98% coverage. Pre-push hook enforces 95% minimum.**

```bash
pytest tests/ -v                    # Full suite
pytest tests/ -m must_pass -v       # Ship-blocking tests only
pytest tests/ -m should_pass -v     # Fix-within-days tests
```

Coverage by module:

| Module | Coverage |
|--------|----------|
| `cli.py` | 99% |
| `db.py` | 100% |
| `identity.py` | 100% |
| `ingest.py` | 100% |
| `mcp_server.py` | 96% |
| `models.py` | 100% |
| `retrieve.py` | 100% |
| `setup_utils.py` | 92% |
| `snippet.py` | 97% |
| `store.py` | 100% |
| `surface.py` | 100% |
| `tags.py` | 100% |
| `tokens.py` | 100% |
| **Total** | **98%** |

Run coverage locally:

```bash
pytest tests/ --cov=momento --cov-branch --cov-report=term-missing
```

### Project structure

```
src/momento/
  __init__.py       # Version
  cli.py            # Argparse CLI (12 commands)
  db.py             # Schema, WAL, FTS5 triggers, migrations
  identity.py       # Git-based project resolution
  ingest.py         # JSONL batch ingestion + session log extraction
  mcp_server.py     # MCP server (retrieve_context, log_knowledge, generate_snippet)
  models.py         # Entry/RestoreResult dataclasses, SIZE_LIMITS
  retrieve.py       # 5-tier restore + FTS5 search
  setup_utils.py    # MCP registration, adapters, hook management
  snippet.py        # Work summaries (markdown, standup, slack, json)
  store.py          # Write path with dedup + size validation
  surface.py        # Surface detection (mapped keywords)
  tags.py           # Tag normalization (lowercase, sort, dedup)
  tokens.py         # Token estimation (len/4)

tests/
  conftest.py       # Fixtures: db, populated_db, insert helpers
  mock_data.py      # Factory functions for test scenarios
  test_cli.py       # CLI command tests (including check-stale)
  test_concurrency.py
  test_continuity.py
  test_cross_project.py
  test_dedup.py
  test_identity.py
  test_ingestion.py
  test_mcp_server.py
  test_restore.py   # Core restore contract (50+ tests)
  test_schema.py
  test_search.py
  test_setup_sh.py  # Integration tests for setup.sh
  test_setup_utils.py # Including hook registration tests
  test_size_limits.py
  test_snippet_*.py # 10 files covering snippets (query, grouping, rendering, CLI, MCP, edge)
  test_store.py
  test_surface.py
  test_tags.py
```

---

## Roadmap

| Version | Focus |
|---------|-------|
| **v0.1** | Core restore, CLI, FTS5 search **(shipped)** |
| **v0.1.1** | Snippets, checkpoint hooks, pre-push gate, output rules **(shipped)** |
| v0.2 | Session tracking, CLAUDE.md export, watchdog |
| v0.3 | Vector embeddings (hybrid BM25 + semantic), multi-editor adapters |
| v0.4 | CI promotion, retrieval analytics |
| v0.5 | Thinking trace mining, auto-tracking, knowledge decay |
| v1.0 | Team sharing, cross-machine sync, Web UI |

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

*Momento -- When your AI forgets, memory remains.*

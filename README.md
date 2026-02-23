# Momento

**Local Memory for AI Coding Agents**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests: 454 passing](https://img.shields.io/badge/tests-454_passing-brightgreen.svg)](tests/)
[![Coverage: 98%](https://img.shields.io/badge/coverage-98%25-brightgreen.svg)](tests/)

---

## The Problem

AI coding agents forget everything. Every `/clear`, context overflow, or new session wipes the slate. You re-explain the same architecture, the same decisions, the same bugs — over and over. And when your manager asks "what did you ship this week?" you're digging through git logs and Slack threads trying to reconstruct what happened.

## What Momento Does

**1. Context recovery** — Your agent calls `retrieve_context()` at session start. Momento returns the active task, architectural decisions, known gotchas, and what comes next. The agent picks up where it left off. You didn't re-explain anything.

**2. Work summaries** — Run `momento snippet` and get a structured summary of what was accomplished, what was decided, and what's still in progress. Daily standups, weekly reports, manager updates — generated from the same knowledge base your agent already uses.

One SQLite file. No cloud. No external dependencies. Works with Claude Code, Codex, and any MCP-compatible agent.

---

## Context Recovery in Action

After a context reset, the agent calls `retrieve_context()`. Momento runs a deterministic 5-tier restore and returns structured directives — not chat history, not raw logs, but distilled intent:

```markdown
## Active Task
[session_state | server | feature/billing-rewrite | 10m ago]
Migrating AuthService to async/await. AuthService.swift and
AuthViewModel.swift complete. ProfileService and PaymentService
remain. Hit race condition in TokenManager -- resolved with actor
isolation.

## Project Knowledge
[gotcha | server | 3d ago]
Auth token refresh: always isolate TokenManager in an actor.
Race condition occurs if refresh overlaps with logout.

[decision | ios | 1d ago]
Chose Keychain over UserDefaults -- UserDefaults is not encrypted.
Wrapped in KeychainManager actor for thread safety.
```

Same inputs always produce identical output. No randomness, no LLM, no probabilistic scoring.

---

## Work Summaries in Action

```bash
momento snippet                    # Today's work
momento snippet --yesterday        # Yesterday (standup prep)
momento snippet --week             # Weekly summary
momento snippet --format standup   # Standup format
momento snippet --format slack     # Slack-friendly markdown
momento snippet --format json      # Machine-readable
```

Example daily snippet:

```markdown
# Monday, Feb 23 2026 — momento

### Accomplished
- Snippets v0.2 implementation complete. 59 tests across 10 files,
  snippet.py core module, CLI command, MCP tool. 410 tests passing.
- Checkpoint enforcement hooks working. Stop hook blocks session end
  if no checkpoint in 30+ min. SessionStart hooks remind on resume.
- Added pre-push hook (tests + 95% coverage gate). 432 tests, 98% coverage.

### Decisions Made
- Checkpoint enforcement via hooks, not behavioral instructions.
  CLAUDE.md instructions were ignored during heavy implementation.

### Still In Progress
- Discovered/Blockers sections noisy from ingested error logs.
  May want to filter or limit in a future pass.
```

Summaries are generated from the same entries your agent saves during work — decisions, gotchas, session checkpoints. The knowledge base does double duty: context for the agent, accountability for you.

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

Setup registers: MCP server in Claude Code + Codex, `CLAUDE.md` adapter with mandatory session-start instructions, checkpoint enforcement hooks, and a pre-push gate.

### Requirements

- Python 3.11+
- pipx
- Runtime: `mcp>=1.0`

---

## Key Features

| Feature | What it does |
|---------|-------------|
| **5-tier deterministic restore** | Same inputs → identical output. Session state, plans, decisions, gotchas, cross-project knowledge. 2000 token budget, never truncates mid-entry. |
| **Work summaries (Snippets)** | Daily/weekly summaries in markdown, standup, slack, or JSON. Generated from the knowledge your agent already saves. |
| **FTS5 keyword search** | BM25-ranked full-text search with OR semantics for multi-word queries. Scoped to current project + cross-project entries. |
| **Checkpoint enforcement** | Hooks block session end if no checkpoint in 30+ min. Auto-remind after resume or context compaction. |
| **Cross-agent continuity** | Claude Code saves a checkpoint, Codex restores it (or vice versa). Any MCP agent can read/write. |
| **Surface-aware ranking** | Working in `/server`? Server entries rank first. Working in `/ios`? iOS entries rank first. Automatic. |
| **Session state decay** | Temporary checkpoints expire after 48h. Decisions, plans, gotchas, patterns persist forever. |
| **MCP integration** | Three tools: `retrieve_context`, `log_knowledge`, `generate_snippet`. Stateless — auto-resolves project/branch/surface from cwd. |

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

## How Restore Works

| Tier | Type | Quota | Window | Purpose |
|------|------|-------|--------|---------|
| 1 | `session_state` | 4 surface + 2 other | 48 hours | What was I just working on? |
| 2 | `plan` | 2 | All time | What's the roadmap? |
| 3 | `decision` | 3 | All time | What did we decide and why? |
| 4 | `gotcha` + `pattern` | 4 combined | All time | What have we learned? |
| 5 | Cross-project | 2 | All time | Solved this elsewhere? |

Within each tier: **surface match > branch match > recency > id** (fully deterministic).

Token budget: 2000 tokens. Tiers process in order; budget flows to the next tier.

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MOMENTO_DB` | `~/.momento/knowledge.db` | Override database path |

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

**454 tests passing. 98% coverage. Pre-push hook enforces 95% minimum.**

```bash
pytest tests/ -v                    # Full suite
pytest tests/ -m must_pass -v       # Ship-blocking tests only
pytest tests/ --cov=momento --cov-report=term-missing  # With coverage
```

### Project structure

```
src/momento/
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

tests/              # 30 test files, 454 tests, 98% coverage
```

---

## Roadmap

| Version | Focus |
|---------|-------|
| **v0.1** | Core restore, CLI, FTS5 search **(shipped)** |
| **v0.1.1** | Snippets, checkpoint hooks, pre-push gate **(shipped)** |
| **v0.1.2** | FTS5 search fix, MCP error messages, adapter upgrade **(shipped)** |
| v0.2 | Session tracking, CLAUDE.md export, watchdog |
| v0.3 | Vector embeddings (hybrid BM25 + semantic), multi-editor adapters |
| v0.4 | CI promotion, retrieval analytics |
| v0.5 | Thinking trace mining, auto-tracking, knowledge decay |
| v1.0 | Team sharing, cross-machine sync, Web UI |

---

## License

Apache License 2.0. See [LICENSE](LICENSE) for details.

---

*Momento — When your AI forgets, memory remains.*

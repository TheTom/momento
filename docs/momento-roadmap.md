# Momento — Feature Roadmap

**Based on:** v0.1.3 shipped (538 tests passing, 97% coverage)
**Date:** February 24, 2026

---

## Design Principle

Every feature from v0.2 onward is a **read-path view** over existing data — or a small, additive write-path enhancement. No schema rewrites. No architectural changes. The v0.1 memory layer is the foundation. Everything else is a lens on top of it.

**Four-fence test still applies to all features:**
1. Agent-agnostic — works regardless of which agent is calling
2. Stateless server — no session state on the server
3. Deterministic — same inputs = same outputs
4. Zero coupling — no agent internals needed

---

## v0.1.x — Shipped (Pulled Forward)

Features originally planned for v0.2 that shipped early during v0.1.x dogfood.

| Feature | Version | Type | Description |
|---------|---------|------|-------------|
| **Snippets** | v0.1.1 | CLI + MCP | Daily/weekly/custom work summaries. Standup, markdown, slack, JSON formats. |
| **Checkpoint Hooks** | v0.1.1 | Setup | Stop hook blocks session end if no checkpoint in 30+ min. SessionStart hooks remind on resume. |
| **Pre-push Gate** | v0.1.1 | Setup | License headers, passing tests, 95% coverage enforced on push. |
| **FTS5 Search Fix** | v0.1.2 | Core | Multi-word queries use OR (was AND). MCP error messages improved. |
| **CLAUDE.md Audit** | v0.1.3 | CLI | Compare Momento knowledge against CLAUDE.md, report gaps, optionally patch. [PRD](prd-momento-audit.md) |
| **Knowledge Decay** | v0.1.3 | Core | Freshness-based ranking demotion within tiers. `MAX(created_at, last_retrieved_at)`. Schema v1→v2. [PRD](prd-momento-decay.md) |

---

## v0.2 — Developer Views

**Trigger:** v0.1 stable, core features shipped, daily use generating entries
**Theme:** "Ask questions of your own memory"

| Feature | Type | New Schema? | Description |
|---------|------|-------------|-------------|
| **Decision Log** | CLI | No | Chronological decision history with rejected alternatives. Branch-filterable. `momento decisions` |
| **Gotcha Map** | CLI | No | Surface-scoped pitfall reference. All gotchas grouped by surface. `momento gotchas` |
| **Handoff** | CLI | No | Cross-agent briefing document. Narrative format for pasting into new sessions. `momento handoff` |
| **Export** | CLI | No | PR description, CLAUDE.md block, JSON, and markdown export. `momento export` |
| **Momentum** | CLI | No | Velocity signal: entry counts, surface coverage, checkpoint cadence, stale branches. `momento momentum` |
| Custom surface mappings | Config | No | `.momento/config.toml` for project-specific surface keywords beyond the default 4. |
| `momento port` | CLI | No | Export CLAUDE.md-compatible instruction block for the current project. |

**Ship criteria:** Developer views are read-only over existing schema. All features pass the four-fence test.

**Implementation order:**
1. Decision Log + Gotcha Map — trivial once Snippets query infrastructure exists
2. Momentum — shares same time-range query patterns
3. Handoff + Export — different templates over same data
4. Custom surface mappings + `momento port`

---

## v0.3 — Search + Adapters + Decay Enhancements

**Trigger:** Enough entries to need better search. Multiple agents in daily use. Evidence from v0.2 decay usage.
**Theme:** "Find anything. Work anywhere. Fine-tune freshness."

| Feature | Type | New Schema? | Description |
|---------|------|-------------|-------------|
| Decay Curve | Core | No | Three-zone soft decay (0–7d full, 7–30d gentle, 30d+ steep). Only if pure MAX proves too binary. |
| Pinning | CLI + Core | Minor (pin flag) | `momento pin/unpin <id>`. Pinned entries sort as `freshness = now`. |
| Vector embeddings | Core | Minor (embedding column) | Hybrid BM25 + semantic via local model. Additive. |
| Cursor adapter | Adapter | No | Rules file integration. |
| Aider adapter | Adapter | No | Session-oriented adapter. |
| Windsurf adapter | Adapter | No | Instruction block adapter. |
| **Drift Report** | CLI + MCP | No (uses `last_retrieved_at`) | "What changed since I was last here?" |
| **Burn Chart** | CLI | No | Feature branch arc visualization. |
| **Health Check** | CLI | No | Memory quality signal. |
| **Diff** | CLI | No | Knowledge delta between branches. |

---

## v0.4 — Analytics + Automation

**Trigger:** Multi-agent usage, enough data for patterns.

Retrieval analytics. Promotion to CI checks. Lazy watchdog. Formal session tracking. `momento archive`. Auto-prune suggestions (`momento prune --suggest` for entries decayed 90+ days with zero retrievals).

---

## v0.5 — Intelligence

**Trigger:** Patterns in what gets retrieved.

Thinking trace mining. Confidence recalibration. Semantic deduplication. Auto-tracking. Multi-project snippets.

---

## v1.0 — Team + Scale

Team sharing. Cross-machine sync. Web UI. Plugin architecture.

---

## Invariants (Never Change)

- `retrieve_context()` with same DB state + cwd + branch = identical output
- No background daemons. No cloud sync. No LLM in ranking.
- Local-first, single file. Developer controls what goes in and what comes out.

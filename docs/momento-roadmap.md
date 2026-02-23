# Momento — Feature Roadmap

**Based on:** v0.1.0 shipped (350 tests passing)
**Date:** February 23, 2026

---

## Design Principle

Every feature from v0.2 onward is a **read-path view** over existing data — or a small, additive write-path enhancement. No schema rewrites. No architectural changes. The v0.1 memory layer is the foundation. Everything else is a lens on top of it.

**Four-fence test still applies to all features:**
1. Agent-agnostic — works regardless of which agent is calling
2. Stateless server — no session state on the server
3. Deterministic — same inputs = same outputs
4. Zero coupling — no agent internals needed

---

## v0.2 — Snippets + Developer Views

**Trigger:** v0.1 stable, daily use generating entries
**Theme:** "Ask questions of your own memory"

| Feature | Type | New Schema? | Description |
|---------|------|-------------|-------------|
| **Snippets** | CLI + MCP | No | Daily/weekly/custom work summaries. "What did I accomplish?" Standup, markdown, slack formats. **Headline feature.** |
| **Decision Log** | CLI | No | Chronological decision history with rejected alternatives. Branch-filterable. `momento decisions` |
| **Gotcha Map** | CLI | No | Surface-scoped pitfall reference. All gotchas grouped by surface. `momento gotchas` |
| **Handoff** | CLI | No | Cross-agent briefing document. Narrative format for pasting into new sessions. `momento handoff` |
| **Export** | CLI | No | PR description, CLAUDE.md block, JSON, and markdown export. `momento export` |
| **Momentum** | CLI | No | Velocity signal: entry counts, surface coverage, checkpoint cadence, stale branches. `momento momentum` |
| Custom surface mappings | Config | No | `.momento/config.toml` for project-specific surface keywords beyond the default 4. |
| `momento port` | CLI | No | Export CLAUDE.md-compatible instruction block for the current project. |

**Ship criteria:** Snippets daily digest works reliably on real project data. All features are read-only views over existing v0.1 schema.

**Implementation order:**
1. Snippets (CLI + MCP) — highest standalone value
2. Decision Log + Gotcha Map — trivial once Snippets query infrastructure exists
3. Momentum — shares same time-range query patterns
4. Handoff + Export — different templates over same data
5. Custom surface mappings + `momento port`

---

## v0.3 — Search + Adapters

**Trigger:** Enough entries to need better search. Multiple agents in daily use.
**Theme:** "Find anything. Work anywhere."

| Feature | Type | New Schema? | Description |
|---------|------|-------------|-------------|
| Vector embeddings | Core | Minor (embedding column) | Hybrid BM25 + semantic via local model. Additive. |
| Cursor adapter | Adapter | No | Rules file integration. |
| Aider adapter | Adapter | No | Session-oriented adapter. |
| Windsurf adapter | Adapter | No | Instruction block adapter. |
| **Drift Report** | CLI + MCP | Minor (last-retrieve ts) | "What changed since I was last here?" |
| **Burn Chart** | CLI | No | Feature branch arc visualization. |
| **Health Check** | CLI | No | Memory quality signal. |
| **Diff** | CLI | No | Knowledge delta between branches. |

---

## v0.4 — Analytics + Automation

**Trigger:** Multi-agent usage, enough data for patterns.

Retrieval analytics. Promotion to CI checks. Lazy watchdog. Formal session tracking. `momento archive`.

---

## v0.5 — Intelligence

**Trigger:** Patterns in what gets retrieved.

Thinking trace mining. Confidence recalibration. Semantic deduplication. Knowledge decay. Auto-tracking. Multi-project snippets.

---

## v1.0 — Team + Scale

Team sharing. Cross-machine sync. Web UI. Plugin architecture.

---

## Invariants (Never Change)

- `retrieve_context()` with same DB state + cwd + branch = identical output
- No background daemons. No cloud sync. No LLM in ranking.
- Local-first, single file. Developer controls what goes in and what comes out.

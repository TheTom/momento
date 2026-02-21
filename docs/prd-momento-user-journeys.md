# Momento — User Journeys PRD

**Version:** 0.1
**Scope:** Restore-after-clear + cross-agent continuity
**Audience:** Engineering, Product
**Status:** v0.1.0 shipped. All core journeys implemented and verified with 350 tests.

---

## 1. Purpose

This document defines the core user journeys Momento must support in v0.1.

Momento's primary goal:

> When an AI coding agent loses context, the developer restores their working state in seconds without re-explaining anything.

All journeys below map back to that single outcome.

---

## 2. Primary Persona

**Independent Developer or Engineer**

- Uses Claude Code and/or Codex regularly
- Works in git-based repositories
- Frequently hits context limits, crashes, or switches agents
- Has experienced re-explaining session state repeatedly
- Values precision, speed, and determinism over automation magic

---

## 3. Core Journey 1 — Restore After /clear

### Scenario

The developer is deep in an implementation. Claude Code loses context due to `/compact` failure or manual `/clear`.

### Preconditions

- Momento is running locally as an MCP server.
- At least one `session_state` checkpoint has been logged.
- `CLAUDE.md` contains deterministic retrieval instructions.

### Flow

**Step 1 — Work in Session**

Developer and Claude collaborate on a multi-step task.

**Step 2 — Developer Logs Checkpoint**

Developer says:

> "checkpoint"

Claude calls:

```
log_knowledge(type="session_state", tags=[...], content="...")
```

Momento stores:
- Task progress
- Decisions made
- Remaining steps
- Project ID auto-resolved from working directory

**Step 3 — Context Loss**

Claude session is cleared.

**Step 4 — Developer Requests Recovery**

Developer types:

> "I just cleared. What was I working on?"

Claude calls:

```
retrieve_context(include_session_state=true)
```

**Step 5 — Momento Returns Structured Directives**

Response uses hard-coded restore ordering (not BM25 ranking):
1. Most recent `session_state` entry (always first)
2. Other recent `session_state` entries (up to 3)
3. High-confidence durable knowledge for this project
4. Cross-project entries matching project tags (if any)

```markdown
## Active Task
Migrating AuthService to async/await. AuthService.swift and
AuthViewModel.swift complete. ProfileService and PaymentService
remain. Hit race condition in TokenManager — resolved with actor
isolation.

## Project Knowledge

### Auth Token Refresh [gotcha]
- Always isolate TokenManager in an actor
- Race condition occurs if refresh overlaps with logout
- Validate refresh token before mutation
```

If no entries exist, Momento returns explicit structure, not silence:

```markdown
## Active Task
No session checkpoints found for this project.

## Project Knowledge
No stored knowledge entries found.

Tip: Use log_knowledge(type="session_state") to save progress
before /compact or /clear.
```

**Step 6 — Agent Resumes Work**

Claude summarizes the restored context and continues.

### Success Criteria

- Retrieval completes under 500ms.
- Context restoration takes under 10 seconds end-to-end.
- Developer does not re-explain previous reasoning.
- Retrieved context is relevant and noise-free.

---

## 4. Core Journey 2 — Cross-Agent Continuity

### Scenario

Developer switches from Claude Code to Codex (or vice versa) in the same repository.

### Preconditions

- Momento contains prior logged entries for the project.
- Codex (or other agent) is configured to call `retrieve_context` at session start, or developer manually prompts it.

### Flow

**Step 1 — Open Different Agent**

Developer opens Codex in the same repository.

**Step 2 — Agent Retrieves Context**

Either automatically (via agent config) or manually triggered:

```
retrieve_context()
```

Project is auto-resolved from the working directory. Same repo = same project ID = same knowledge.

**Step 3 — Momento Returns Project Knowledge**

Includes:
- Latest `session_state` (if exists)
- Durable gotchas, decisions, patterns

**Step 4 — Agent Operates with Constraints**

Codex continues work with preserved reasoning context.

### Success Criteria

- No manual copy/paste between agents.
- No chat history transfer required.
- Agents behave consistently within project constraints.

---

## 5. Core Journey 3 — Error Recall

### Scenario

Developer encounters a previously solved issue.

### Preconditions

- A related `gotcha` entry exists in Momento.

### Flow

**Step 1 — Error Occurs**

Example: `"database locked"` during concurrent write.

**Step 2 — Agent Queries Momento**

```
retrieve_context(query="database locked concurrent write")
```

**Step 3 — Relevant Entry Returned**

```markdown
### SQLite Write Lock [gotcha]
- Concurrent writes without WAL caused DB lock
- Enable PRAGMA journal_mode=WAL
- Wrap writes in transaction
```

**Step 4 — Agent Applies Fix**

### Success Criteria

- Exact or near-exact lexical match is sufficient (BM25).
- No irrelevant entries are returned.
- Developer avoids rediscovering the same bug.

---

## 6. Core Journey 4 — New Session Continuation

### Scenario

Developer opens a fresh session the next day.

### Preconditions

- Durable entries exist.
- Optional: `session_state` entries exist from yesterday.

### Flow

**Step 1 — New Session Starts**

Agent is blank.

**Step 2 — Agent Calls retrieve_context**

Per deterministic `CLAUDE.md` instruction:

```
retrieve_context(include_session_state=true)
```

**Step 3 — Momento Returns:**

- Latest `session_state` (if any)
- Durable project knowledge

**Step 4 — Agent Begins with Orientation**

### Success Criteria

- Agent starts from an informed baseline.
- Developer does not manually summarize prior decisions.

---

## 7. Manual CLI Flow

### Logging via CLI

```bash
momento log "Must verify job.status before retry" \
    --type gotcha \
    --tags scheduler,retry
```

Expected behavior:
- Project auto-resolved from current working directory.
- Entry stored without transformation.

### Inspecting Knowledge

```bash
momento inspect
```

Expected behavior:
- Developer sees only recognizable, high-signal entries.
- No noisy conversation fragments.

### Pruning

```bash
momento prune <entry-id>
```

Expected behavior:
- Developer retains full control over knowledge base hygiene.

### Ingesting from Claude Code Logs

```bash
momento ingest
```

Expected behavior:
- Reads `~/.claude/` JSONL files for current project.
- Extracts compaction summaries (filtered by keyword heuristic) and error pairs.
- Deduplicates by exact content hash.
- Developer runs this manually or on a schedule.

---

## 8. Non-Goals for v0.1

These journeys are explicitly out of scope:

- Automatic background memory capture
- Real-time file monitoring
- Autonomous context injection
- Team collaboration
- Cross-machine sync
- Vector-based semantic retrieval
- LLM-based summarization of raw sessions
- Thinking trace mining
- Confidence auto-scoring
- Knowledge decay logic

---

## 9. Behavioral Assumptions

Momento assumes:

- Developers will manually log checkpoints (the "checkpoint" shortcut reduces friction to one word).
- Agents will reliably call `retrieve_context` when instructed via `CLAUDE.md`.
- The knowledge base will remain intentionally small and curated.

If these assumptions fail, the restore-after-clear moment degrades gracefully — partial recovery, not total failure. The system never corrupts state regardless of logging completeness.

---

## 10. Definition of Success

Momento v0.1 succeeds if:

1. Developers instinctively say "checkpoint" before risky operations.
2. Retrieval consistently returns high-signal, structured directives.
3. Restore-after-clear feels faster than re-explaining.
4. Cross-agent switching feels frictionless.
5. The knowledge base remains small, intentional, and trusted.

---

## 11. The Core Experience

Momento is not:
- A chat archive.
- A second brain.
- A memory graph.
- An autonomous AI system.

Momento is:

> A deterministic memory layer that restores developer intent across session resets and agent switches.

If the restore moment consistently feels reliable and fast, the product has achieved its purpose.

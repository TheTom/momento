# Momento Audit — Engineering PRD

**Version:** 0.2.0
**Status:** Ready for Implementation
**Depends on:** v0.1.2 (shipped, 450 tests passing)
**Date:** February 23, 2026

---

## 1. Problem

CLAUDE.md files go stale. Developers create them during setup, then accumulate weeks of decisions, gotchas, and patterns in Momento that never make it back into the static instruction file. The agent reads CLAUDE.md every session but only calls Momento when instructed to. If CLAUDE.md is incomplete, the agent operates with partial knowledge even when Momento has the full picture.

The reverse is also true: CLAUDE.md may reference things that no Momento entry supports — stale instructions from early setup that no longer apply.

There is also the global adapter problem. If `~/.claude/CLAUDE.md` is missing the `retrieve_context` instruction, the agent has a write-only memory — it saves but never reads. This is invisible to the developer.

Nobody audits their CLAUDE.md manually. The drift is silent.

---

## 2. Solution

A CLI command that compares Momento's durable knowledge against the project's CLAUDE.md (and global `~/.claude/CLAUDE.md`), identifies gaps in both directions, and optionally patches the file.

No LLM. Keyword overlap comparison. Deterministic.

---

## 3. Core Concept

```bash
momento audit-claude-md
```

Reads the project CLAUDE.md + global CLAUDE.md. Reads all durable Momento entries for the project. Diffs them. Reports what's missing, what's stale, and what's wrong with the adapter configuration.

---

## 4. CLI Interface

```bash
momento audit-claude-md                  # audit, report only
momento audit-claude-md --fix            # append missing entries to CLAUDE.md
momento audit-claude-md --dry-run        # show what --fix would do, don't write
momento audit-claude-md --force          # skip maturity threshold
momento audit-claude-md --global-only    # audit only ~/.claude/CLAUDE.md
momento audit-claude-md --project-only   # audit only project CLAUDE.md
```

| Flag | Default | Description |
|------|---------|-------------|
| `--fix` | false | Append missing Momento entries to CLAUDE.md |
| `--dry-run` | false | Preview what `--fix` would do without writing |
| `--force` | false | Skip maturity threshold check |
| `--global-only` | false | Only audit `~/.claude/CLAUDE.md` |
| `--project-only` | false | Only audit project CLAUDE.md |

**Exit codes:**
- 0 — audit complete (with or without gaps found)
- 1 — no project detected, or CLAUDE.md not found and `--fix` not set
- 2 — below maturity threshold (without `--force`)

---

## 5. Maturity Threshold

Auditing 3 entries is noise. The audit is only useful after enough signal has accumulated.

**All four conditions must pass:**

| Signal | Minimum | Rationale |
|--------|---------|-----------|
| Total entries | 10 | Below this there's barely a knowledge base |
| Durable entries (decision + gotcha + pattern) | 4 | Session states alone aren't audit-worthy |
| Distinct types represented | 2+ | Need at least decisions AND gotchas to compare |
| Days with entries | 3+ | One intense session doesn't mean settled patterns |

If any condition fails, print the threshold report and exit 2:

```
theology_bro — not enough data to audit yet.

  Entries: 9 (need 10)
  Durable: 5 of 4 ✓
  Types: 3 of 2 ✓
  Days active: 1 (need 3)

Keep using Momento in this project. Audit works best after
a few sessions of real work. Try again in a couple days.

  (use --force to skip this check)
```

Thresholds are hardcoded. Not configurable in v0.2. Adjust from real usage data if they prove wrong.

`--force` bypasses the threshold entirely.

---

## 6. Audit Report Structure

The report has four sections, always in this order:

### 6.1 — Missing from CLAUDE.md (Momento knows, CLAUDE.md doesn't)

Durable Momento entries whose key terms don't appear anywhere in CLAUDE.md.

Grouped by type:

```
MISSING FROM CLAUDE.md — Momento knows, CLAUDE.md doesn't
────────────────────────────────────────────────────

Gotchas (4 not mentioned):

  ⚠ BM25 retrieval silently falls back to vector-only when collection
    exceeds 20k vectors. bible collection always vector-only.
    (logged 12d ago · tags: bm25, retrieval, bible)

  ⚠ client.py --top-k above 50 causes OOM on sermons collection.
    (logged 5d ago · tags: client, sermons, memory)

Decisions (2 not mentioned):

  📌 Switched from OpenAI embeddings to all-MiniLM-L6-v2.
     Rationale: free, local, no API key needed.
     (logged 11d ago · tags: embeddings, cost, architecture)

  📌 hymns collection uses chunk_size=256 not 512.
     (logged 7d ago · tags: hymns, chunking)

Patterns (1 not mentioned):

  📐 New collection workflow: sources dir → config.py → POST /index.
     (logged 9d ago · tags: collections, indexing, workflow)
```

**Ordering within each type:** oldest first (chronological). Oldest gaps are the most likely to be genuine omissions rather than recent work that hasn't settled yet.

**Entry display:**
- First line: full entry content (as stored)
- Second line: `(logged Nd ago · tags: tag1, tag2, tag3)`
- Emoji prefix by type: ⚠ gotcha, 📌 decision, 📐 pattern
- Plans are excluded from this section (plans are transient, not CLAUDE.md material)
- Session states are excluded (ephemeral by design)

### 6.2 — CLAUDE.md has, Momento doesn't (staleness risk)

Lines or sections in CLAUDE.md that reference concepts with zero corresponding Momento entries.

```
CLAUDE.md HAS, MOMENTO DOESN'T — may be stale or undocumented
────────────────────────────────────────────────────

  ? CLAUDE.md mentions "OPENAI_API_KEY — optional fallback" but no
    Momento entry references OpenAI. Is this still used?

  ? CLAUDE.md lists "local_theology_bot.py — Standalone local search"
    but no Momento entry references local_theology_bot. Still relevant?
```

**Phrased as questions, not assertions.** CLAUDE.md might be right and Momento might be missing the entry. The audit surfaces the discrepancy, not the verdict.

**Matching logic:** Extract significant terms from each CLAUDE.md line (nouns, filenames, identifiers — not stopwords). If a term appears in CLAUDE.md but in zero Momento entries, flag it as a staleness candidate.

**Filtering:** Only flag terms that look like project-specific identifiers: filenames, tool names, config keys, domain terms. Skip generic words like "the", "should", "always", common programming terms like "function", "class", "import". Use a simple heuristic: flag terms that contain dots (filenames), underscores (identifiers), ALL_CAPS (env vars), or are in the project's tag vocabulary.

### 6.3 — Global adapter issues

Checks `~/.claude/CLAUDE.md` for common adapter problems:

```
GLOBAL ~/.claude/CLAUDE.md — adapter issues
────────────────────────────────────────────────────

  ✗ Missing: retrieve_context at session start.
    Your agent saves memory but never reads it on startup.
    Add: "At the START of every session, call
    retrieve_context(include_session_state=true)"

  ✓ Has: log_knowledge after changes (write path OK)
  ✓ Has: Momento output rules (inline CLI output)
```

**Checks performed:**

| Check | Looks for | Status |
|-------|-----------|--------|
| Read path (retrieve) | `retrieve_context` in file | ✓ or ✗ |
| Write path (log) | `log_knowledge` in file | ✓ or ✗ |
| Output rules | `momento` + `output` or `inline` | ✓ or ✗ |
| Session start instruction | `session start` or `start of every session` | ✓ or ✗ |

These are substring checks. Not parsing. Not semantic. If the file contains `retrieve_context`, the check passes. Good enough.

### 6.4 — Summary

```
SUMMARY
────────────────────────────────────────────────────

  CLAUDE.md coverage: 58% of durable Momento knowledge
  Gaps: 4 gotchas, 3 decisions, 2 patterns not in CLAUDE.md
  Stale risk: 2 CLAUDE.md items not backed by Momento entries
  Global adapter: missing read path (critical)

  Run `momento audit-claude-md --fix` to append missing entries.
  Run `momento audit-claude-md --dry-run` to preview changes.
```

**Coverage percentage:** `(durable entries mentioned in CLAUDE.md) / (total durable entries) * 100`. Rounded to nearest integer.

---

## 7. Matching Algorithm

### 7.1 — "Is this Momento entry mentioned in CLAUDE.md?"

For each durable entry (decision, gotcha, pattern):

1. Extract **key terms** from the entry content:
   - Split on whitespace and punctuation
   - Remove stopwords (the, is, a, an, of, for, to, in, on, at, etc.)
   - Remove common programming stopwords (function, class, import, return, etc.)
   - Lowercase all terms
   - Keep terms ≥ 3 characters
   
2. Extract key terms from entry tags (already normalized).

3. Build a **term set** = content terms ∪ tag terms.

4. Read CLAUDE.md as a single lowercase string.

5. For each term in the term set, check if it appears in the CLAUDE.md string.

6. Compute **overlap score** = `terms found in CLAUDE.md / total terms`.

7. If overlap score < **0.3** (less than 30% of the entry's key terms appear in CLAUDE.md), the entry is flagged as "missing."

The 0.3 threshold is deliberately low. If fewer than 30% of an entry's distinctive terms appear anywhere in CLAUDE.md, the entry is almost certainly not represented. Higher thresholds would produce false positives from coincidental term overlap.

### 7.2 — "Is this CLAUDE.md item still in Momento?"

For each non-empty, non-header line in CLAUDE.md:

1. Extract significant terms (same stopword removal as above).
2. Additional filter: only flag terms that look like project identifiers:
   - Contains `.` (filenames: `client.py`, `app.py`)
   - Contains `_` (identifiers: `local_theology_bot`, `OPENAI_API_KEY`)
   - Is ALL_CAPS (env vars: `ANTHROPIC_API_KEY`)
   - Appears in the project's tag vocabulary
3. For each identifier term, check if it appears in ANY Momento entry (content or tags) for this project.
4. If an identifier term appears in CLAUDE.md but in zero Momento entries, flag it.

This is intentionally conservative. Only flags identifiers, not prose. The goal is catching stale references to specific files, tools, or configs — not evaluating whether CLAUDE.md's prose descriptions are accurate.

### 7.3 — No LLM. No embeddings. No fuzzy matching.

The matching is keyword overlap. It will miss semantic equivalences ("embedding model" in Momento vs "vector encoder" in CLAUDE.md). That's acceptable for v0.2. The audit catches the obvious gaps — the ones where CLAUDE.md simply doesn't mention a topic at all. Semantic matching is a v0.3 enhancement if keyword overlap proves insufficient.

---

## 8. Fix Mode

### 8.1 — Section Detection

When `--fix` is specified, the audit needs to know WHERE in CLAUDE.md to append entries.

**Strategy:** Look for existing section headers that match entry types:

| Entry type | Looks for header containing | Fallback header |
|------------|---------------------------|-----------------|
| gotcha | `gotcha`, `pitfall`, `known issue`, `warning`, `watch out` | `## Known Gotchas` |
| decision | `decision`, `architecture`, `chose`, `rationale` | `## Architecture Decisions` |
| pattern | `pattern`, `convention`, `standard`, `workflow` | `## Conventions` |

Case-insensitive substring match on markdown headers (`#`, `##`, `###`).

If a matching header exists, append entries below the last line in that section (before the next header of equal or higher level).

If no matching header exists, create the fallback header at the end of the file and append entries under it.

### 8.2 — Entry Formatting for CLAUDE.md

Entries are formatted as markdown list items:

```markdown
- BM25 retrieval falls back to vector-only above 20k vectors. bible collection always vector-only.
- client.py --top-k above 50 causes OOM on sermons collection. Keep ≤ 30 for sermons.
```

No metadata (tags, dates, IDs). CLAUDE.md is for the agent to read, not for humans to cross-reference with Momento. Keep it clean.

### 8.3 — Global CLAUDE.md

`--fix` never modifies `~/.claude/CLAUDE.md`. The global file affects all projects. Modifying it automatically is too risky.

Instead, print the specific instruction to add manually:

```
⚠ Global CLAUDE.md not modified. Add retrieve_context instruction manually:
  ~/.claude/CLAUDE.md

Suggested addition:

  ## Momento Session Start
  At the START of every new session, before doing any work:
    Call retrieve_context(include_session_state=true)
    Read the response. It contains your project state, decisions, and known pitfalls.
    Do not skip this. Do not assume you know the project from CLAUDE.md alone.
```

### 8.4 — Dry Run

`--dry-run` produces identical output to `--fix` but prefixed with:

```
DRY RUN — no files modified. Showing what --fix would do:
```

And does not write to disk. Exit code 0.

### 8.5 — Idempotency

Running `--fix` twice should not duplicate entries. Before appending, check if the entry's key terms already appear in the file (using the same 0.3 overlap threshold from Section 7.1). If they do, skip the entry. This handles the case where `--fix` was run previously or the developer manually added the content.

### 8.6 — Backup

Before modifying CLAUDE.md, copy the original to `CLAUDE.md.bak` in the same directory. Overwrite any existing `.bak` file. Print:

```
Backed up: CLAUDE.md → CLAUDE.md.bak
```

---

## 9. File Discovery

### 9.1 — Project CLAUDE.md

Search order:
1. `{git_root}/CLAUDE.md`
2. `{git_root}/.claude/CLAUDE.md`
3. `{cwd}/CLAUDE.md`

First found wins. If none found:
- Audit mode: print "No project CLAUDE.md found. Nothing to audit." and skip project section.
- Fix mode: create `{git_root}/CLAUDE.md` with the fallback headers and append entries.

### 9.2 — Global CLAUDE.md

Fixed path: `~/.claude/CLAUDE.md`

If not found: print "No global CLAUDE.md found at ~/.claude/CLAUDE.md" and skip global section.

---

## 10. Four-Fence Test

| Test | Pass? | Rationale |
|------|-------|-----------|
| Agent-agnostic | Yes | Reads files + queries DB. No agent dependency. |
| Stateless server | Yes | CLI command, no server state. |
| Deterministic | Yes | Same DB + same files = same output. |
| Zero coupling | Yes | No agent internals needed. |

---

## 11. Edge Cases

### 11.1 — No CLAUDE.md exists

Audit mode: print info message, skip project section, still audit global.
Fix mode: create CLAUDE.md with fallback headers and populate.

### 11.2 — CLAUDE.md is empty

Treat as "no content" — every Momento entry will be flagged as missing. `--fix` populates it.

### 11.3 — No Momento entries

Print "No Momento entries for this project. Nothing to audit." Exit 0.

### 11.4 — All entries already in CLAUDE.md

```
theology_bro — CLAUDE.md is up to date.

  CLAUDE.md coverage: 100% of durable Momento knowledge
  No gaps found.
  No stale references detected.
```

### 11.5 — Project has only session_state entries

Session states are excluded from audit (ephemeral). Threshold check uses durable entries only. Likely fails threshold → "not enough data" message.

### 11.6 — CLAUDE.md has non-standard structure

The section detection is best-effort. If CLAUDE.md has no recognizable headers, `--fix` appends all entries at the end under fallback headers. It doesn't try to restructure the file.

### 11.7 — Very large CLAUDE.md

No size limit on CLAUDE.md parsing. Read the whole file. If performance becomes an issue (unlikely — CLAUDE.md files are typically <200 lines), address in v0.3.

### 11.8 — Concurrent modification

`--fix` reads, modifies, and writes CLAUDE.md non-atomically. If another process modifies the file between read and write, changes may be lost. Acceptable for v0.2 — this is a manual CLI command, not a daemon. The `.bak` file provides recovery.

---

## 12. Implementation

### 12.1 — Module

```
src/momento/audit.py
```

### 12.2 — Core Functions

```python
def audit_claude_md(
    db: Connection,
    project_id: str,
    project_name: str,
    project_claude_md_path: str | None,
    global_claude_md_path: str | None,
    fix: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> AuditResult:
    """Run the full audit. Returns structured result for rendering."""
```

```python
def check_maturity(
    db: Connection,
    project_id: str,
) -> tuple[bool, ThresholdReport]:
    """Check if project has enough data for a meaningful audit."""
```

```python
def extract_key_terms(text: str) -> set[str]:
    """Extract significant terms from text. Remove stopwords, keep ≥3 chars."""
```

```python
def compute_overlap(entry_terms: set[str], target_text: str) -> float:
    """What fraction of entry_terms appear in target_text? Returns 0.0–1.0."""
```

```python
def find_missing_entries(
    entries: list[Entry],
    claude_md_text: str,
    threshold: float = 0.3,
) -> list[Entry]:
    """Entries with <threshold overlap against CLAUDE.md text."""
```

```python
def find_stale_references(
    claude_md_text: str,
    entries: list[Entry],
) -> list[str]:
    """CLAUDE.md identifiers not backed by any Momento entry."""
```

```python
def check_global_adapter(
    global_claude_md_text: str,
) -> list[AdapterCheck]:
    """Check global CLAUDE.md for read path, write path, output rules."""
```

```python
def find_target_section(
    claude_md_lines: list[str],
    entry_type: str,
) -> int | None:
    """Find the line number to insert entries for this type. None = append."""
```

```python
def apply_fix(
    claude_md_path: str,
    missing_entries: list[Entry],
    claude_md_lines: list[str],
    dry_run: bool = False,
) -> FixResult:
    """Append missing entries to CLAUDE.md. Backs up first."""
```

### 12.3 — Data Structures

```python
OVERLAP_THRESHOLD = 0.3

MATURITY_THRESHOLDS = {
    "total_entries": 10,
    "durable_entries": 4,
    "distinct_types": 2,
    "days_active": 3,
}

STOPWORDS = {
    "the", "is", "a", "an", "of", "for", "to", "in", "on", "at",
    "and", "or", "but", "not", "with", "from", "by", "as", "it",
    "this", "that", "be", "are", "was", "were", "been", "has",
    "have", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "must", "shall",
    "if", "then", "else", "when", "where", "how", "what", "which",
    "who", "all", "each", "every", "any", "some", "no", "more",
    "most", "other", "than", "too", "very", "also", "just", "about",
}

CODE_STOPWORDS = {
    "function", "class", "import", "return", "def", "var", "let",
    "const", "true", "false", "none", "null", "self", "str", "int",
    "list", "dict", "type", "value", "name", "data", "file",
}

SECTION_KEYWORDS = {
    "gotcha": ["gotcha", "pitfall", "known issue", "warning", "watch out", "caveat"],
    "decision": ["decision", "architecture", "chose", "rationale", "design"],
    "pattern": ["pattern", "convention", "standard", "workflow", "rule"],
}

FALLBACK_HEADERS = {
    "gotcha": "## Known Gotchas",
    "decision": "## Architecture Decisions",
    "pattern": "## Conventions",
}

ADAPTER_CHECKS = [
    {"name": "Read path (retrieve)", "terms": ["retrieve_context"], "critical": True},
    {"name": "Write path (log)", "terms": ["log_knowledge"], "critical": False},
    {"name": "Output rules", "terms": ["momento", "inline"], "critical": False},
    {"name": "Session start", "terms": ["session start", "start of every session", "start of each session"], "critical": True},
]

@dataclass
class ThresholdReport:
    total_entries: int
    durable_entries: int
    distinct_types: int
    days_active: int
    passed: bool

@dataclass
class AdapterCheck:
    name: str
    found: bool
    critical: bool

@dataclass
class AuditResult:
    project_name: str
    threshold_passed: bool
    threshold_report: ThresholdReport | None
    missing_entries: list[Entry]        # Momento has, CLAUDE.md doesn't
    stale_references: list[str]         # CLAUDE.md has, Momento doesn't
    adapter_checks: list[AdapterCheck]  # global CLAUDE.md checks
    coverage_pct: int                   # 0–100
    durable_total: int

@dataclass
class FixResult:
    entries_added: int
    entries_skipped: int     # already present (idempotency)
    sections_created: int    # new fallback headers added
    backup_path: str
    lines_before: int
    lines_after: int
```

### 12.4 — Stopword Filtering

```python
def extract_key_terms(text: str) -> set[str]:
    """Extract significant terms. Remove stopwords, keep ≥3 chars."""
    tokens = re.findall(r'[a-zA-Z0-9_./:-]+', text.lower())
    return {
        t for t in tokens
        if len(t) >= 3
        and t not in STOPWORDS
        and t not in CODE_STOPWORDS
    }
```

### 12.5 — Identifier Extraction for Staleness Check

```python
def is_project_identifier(term: str) -> bool:
    """Heuristic: is this a project-specific identifier?"""
    return (
        '.' in term           # filenames: client.py, app.py
        or '_' in term        # identifiers: local_theology_bot
        or term.isupper()     # env vars: ANTHROPIC_API_KEY
        or '/' in term        # paths: indexer/app.py
    )
```

---

## 13. CLI Registration

Add to existing Click CLI group:

```python
@cli.command("audit-claude-md")
@click.option("--fix", is_flag=True, help="Append missing entries to CLAUDE.md")
@click.option("--dry-run", is_flag=True, help="Preview --fix without writing")
@click.option("--force", is_flag=True, help="Skip maturity threshold")
@click.option("--global-only", is_flag=True, help="Audit only ~/.claude/CLAUDE.md")
@click.option("--project-only", is_flag=True, help="Audit only project CLAUDE.md")
def audit_claude_md(fix, dry_run, force, global_only, project_only):
    ...
```

`--fix` and `--dry-run` are mutually exclusive. If both specified, treat as `--dry-run`.

---

## 14. What This Is NOT

- **Not a CLAUDE.md generator.** It doesn't create CLAUDE.md from scratch (except as `--fix` fallback when no file exists). It audits an existing file against Momento.
- **Not a linter.** It doesn't check CLAUDE.md formatting, structure, or quality. Only checks coverage against Momento entries.
- **Not semantic analysis.** Keyword overlap only. Won't catch "embedding model" vs "vector encoder" equivalence. Good enough for v0.2.
- **Not an MCP tool.** CLI only. Agents shouldn't audit their own instruction files — that's a human review task.
- **Not a daemon.** Run it when you want. No scheduled checks, no warnings during sessions.

---

## 15. Interaction with Other Features

| Feature | Relationship |
|---------|-------------|
| `momento snippet` | Snippets summarize time ranges. Audit compares persistent knowledge against CLAUDE.md. Different inputs, different outputs. |
| `momento inspect` | Inspect shows raw entries. Audit shows gaps between entries and CLAUDE.md. |
| `momento export --format claude-md` | Export generates a CLAUDE.md block from Momento. Audit compares existing CLAUDE.md against Momento. Export creates; audit diffs. Complementary. |
| `retrieve_context` | Audit checks whether global CLAUDE.md has the instruction to call retrieve_context. Meta-level. |

---

## 16. Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Matching algorithm | Keyword overlap, 0.3 threshold | Simple, deterministic, no dependencies. Catches obvious gaps. |
| Semantic matching | No (v0.2) | Would require embeddings. Keyword overlap is good enough for "is this topic mentioned at all?" |
| Global CLAUDE.md modification | Never automatic | Too risky. Affects all projects. Manual edit with specific suggestion. |
| Backup before fix | Always (`.bak`) | Non-atomic write. Need recovery path. |
| Session state in audit | Excluded | Ephemeral. Not CLAUDE.md material. |
| Plans in audit | Excluded | Transient. Plans change. Not stable enough for CLAUDE.md. |
| Entry formatting in fix | Bare content, no metadata | CLAUDE.md is for agent consumption. Tags and dates are noise. |
| Threshold configurability | Hardcoded | Adjust from real usage data. Config file parsing is v0.2 scope creep. |
| MCP tool | No | Human review task. Agents shouldn't audit their own instructions. |
| Idempotent fix | Yes (overlap check before append) | Running --fix twice should not duplicate entries. |

---

## 17. What Ships

**v0.2.0 audit scope:**
1. `momento audit-claude-md` CLI command
2. Maturity threshold with `--force` bypass
3. Four-section report: missing, stale, global adapter, summary
4. `--fix` mode with section detection and fallback headers
5. `--dry-run` mode
6. `.bak` backup before any write
7. Idempotent fix (no duplication on repeat runs)
8. Global CLAUDE.md adapter check (read path, write path, session start, output rules)

**Not in v0.2.0:**
- Semantic matching (embeddings-based comparison)
- MCP tool (agents auditing themselves)
- Scheduled audits
- Custom threshold configuration
- CLAUDE.md quality scoring
- Multi-file project instructions (e.g., `.cursorrules`, `.codex_instructions.md`)
- Diffing against non-CLAUDE.md instruction files

---

## 18. Implementation Order

```
1. audit.py — extract_key_terms() + compute_overlap()
2. audit.py — check_maturity()
3. audit.py — find_missing_entries()
4. audit.py — find_stale_references()
5. audit.py — check_global_adapter()
6. audit.py — render report (all 4 sections)
7. audit.py — find_target_section() + apply_fix()
8. audit.py — idempotency check + backup
9. cli.py — audit-claude-md command registration
10. Test with real theology_bro data
```

# Momento Snippets — Acceptance Tests

**Version:** 0.2.0
**Status:** Ready for Implementation
**Depends on:** v0.1.0 test infrastructure (conftest.py, mock_data.py, fixtures)

---

## Test File Structure

```
tests/
├── test_snippet_query.py       # TS1.* — time range + SQL
├── test_snippet_grouping.py    # TS2.* — section mapping + split logic
├── test_snippet_markdown.py    # TS3.* — markdown rendering
├── test_snippet_standup.py     # TS4.* — standup rendering
├── test_snippet_slack.py       # TS5.* — slack rendering
├── test_snippet_json.py        # TS6.* — json rendering
├── test_snippet_cli.py         # TS7.* — CLI command
├── test_snippet_mcp.py         # TS8.* — MCP tool
├── test_snippet_edge.py        # TS9.* — edge cases
└── test_snippet_weekly.py      # TS10.* — weekly mode
```

All tests use `TS` prefix (Test Snippets) to avoid collision with v0.1 `T` prefix.

---

## Mock Data

Extend existing `tests/mock_data.py` with snippet-specific factories:

```python
def make_snippet_day() -> list[dict]:
    """
    A realistic day of work. Returns 14 entries:
    - 4 session_state (3 accomplished, 1 in-progress)
    - 2 decision
    - 2 gotcha
    - 1 pattern
    - 2 plan
    - 1 session_state with "done" keyword (completion override)
    - 1 cross-project entry
    All timestamps within today.
    """

def make_snippet_week() -> list[dict]:
    """
    A realistic week of work. Returns 28+ entries spread across
    5 days (Mon-Fri), multiple branches, multiple surfaces.
    Includes at least 1 day with zero entries (gap day).
    """

def make_snippet_empty() -> list[dict]:
    """Returns entries outside today's range. Snippet should produce empty result."""

def make_snippet_session_split() -> list[dict]:
    """
    Session states designed to test accomplished/in-progress split:
    - 2 session_state for (server, feature/billing): older = accomplished, newer = in-progress
    - 2 session_state for (ios, main): older = accomplished, newer = in-progress
    - 1 session_state with "completed" keyword: always accomplished despite being newest
    """

def make_snippet_durable_only() -> list[dict]:
    """Only decisions + gotchas + patterns. No session_state. No plans."""
```

---

## TS1: Time Range + Query

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

## TS2: Section Grouping

**TS2.1 — Type-to-section mapping** `must_pass`
```
Given: 1 entry of each type (session_state, decision, gotcha, pattern, plan)
When: group_entries() runs
Then: decision → decisions section
      gotcha → discovered section
      pattern → patterns section
      plan → in_progress section
      session_state → split by recency (see TS2.2)
```

**TS2.2 — Session state split: accomplished vs in-progress** `must_pass`
```
Given: 3 session_state entries for (server, feature/billing):
       - entry A at 9:00
       - entry B at 11:00
       - entry C at 14:00 (most recent)
When: split_session_states() runs
Then: A and B → accomplished
      C → in_progress
      (most recent per surface+branch key = in-progress)
```

**TS2.3 — Session state split: multiple surfaces** `must_pass`
```
Given: 2 session_state for (server, main): S1 older, S2 newer
       2 session_state for (ios, main): I1 older, I2 newer
When: split_session_states() runs
Then: S1, I1 → accomplished
      S2, I2 → in_progress
      (independent split per surface+branch key)
```

**TS2.4 — Keyword completion override** `must_pass`
```
Given: session_state with content "Auth migration done. All handlers updated."
       This is the most recent entry for its surface+branch key.
When: split_session_states() runs
Then: entry → accomplished (not in-progress)
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

## TS3: Markdown Rendering

**TS3.1 — Full daily markdown** `must_pass`
```
Given: the make_snippet_day() dataset (14 entries)
When: render_markdown(sections, meta)
Then: output starts with "# Momento Snippet — <date>"
      contains "## <project_name>"
      has sections in order: Accomplished, Decisions Made, Discovered,
        Still In Progress, Conventions Established
      each entry renders as "- <content>" list item
      decisions include the full content (rejected alternatives visible)
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
Then: header includes branch name: "## payments-platform · feature/billing-rewrite"
```

**TS3.5 — Markdown is deterministic** `must_pass`
```
Given: same entries, same time range
When: render_markdown() called twice
Then: outputs are byte-identical
```

---

## TS4: Standup Rendering

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
      (not "None detected")
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
      "*Today:* —"
      "*Blockers:* —"
```

**TS4.5 — Weekly standup uses "This week" / "Next week"** `should_pass`
```
Given: week range with entries
When: render_standup() with weekly meta
Then: "*This week:*" instead of "*Yesterday:*"
      "*Next week:*" instead of "*Today:*"
```

---

## TS5: Slack Rendering

**TS5.1 — Basic slack** `must_pass`
```
Given: 2 accomplished, 1 decision, 1 gotcha, 1 in-progress
When: render_slack()
Then: first line is "📋 *<date> snippet — <project>*"
      accomplished lines start with "✅"
      decision lines start with "📌"
      gotcha lines start with "⚠️"
      in-progress lines start with "🔄"
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
Then: line starts with "📐"
```

---

## TS6: JSON Rendering

**TS6.1 — JSON structure** `must_pass`
```
Given: entries across multiple types
When: render_json()
Then: output is valid JSON
      has keys: project, branch, range, sections, entry_count, empty
      sections has keys: accomplished, decisions, discovered, in_progress, patterns
      each section item has: content, entry_id
      session_state items also have: source_type
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

## TS7: CLI Command

**TS7.1 — Default invocation** `must_pass`
```
Given: entries exist for today
When: `momento snippet` (no flags)
Then: prints markdown format
      exit code 0
```

**TS7.2 — Format flag** `should_pass`
```
Given: entries exist
When: `momento snippet --format standup`
Then: prints standup format (has "Yesterday:" / "Today:" / "Blockers:")
```

**TS7.3 — No project detected** `should_pass`
```
Given: cwd is /tmp (no git repo, no prior entries)
When: `momento snippet`
Then: prints error message about no project
      exit code 1
```

**TS7.4 — Empty range message** `must_pass`
```
Given: no entries for today
When: `momento snippet`
Then: prints empty-range message
      exit code 0 (not an error)
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

## TS8: MCP Tool

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
      same output as CLI `momento snippet`
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

## TS9: Edge Cases

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
      no padding, no filler
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
      used as key for accomplished/in-progress split
```

**TS9.7 — No surface in tags** `should_pass`
```
Given: 2 session_state entries with tags ["auth", "billing"] (no surface keyword)
       same branch, different times
When: split_session_states() runs
Then: surface = None for both
      key = (None, branch) — still splits correctly
      older → accomplished, newer → in-progress
```

---

## TS10: Weekly Mode

**TS10.1 — Weekly markdown has Key Moments** `must_pass`
```
Given: make_snippet_week() dataset (5 days, 28+ entries)
When: render_markdown() with weekly range
Then: output contains "### Key Moments" section
      key moments are decisions + gotchas with day labels
      format: "- **Tue Feb 18:** <summary>"
```

**TS10.2 — Weekly Progress section** `must_pass`
```
Given: weekly dataset with session_state entries
When: render_markdown() with weekly range
Then: "### Progress" section shows most recent session_state per surface+branch
      (not all session states — just current in-progress items)
```

**TS10.3 — Gap day handling** `should_pass`
```
Given: entries on Mon, Tue, Thu, Fri (no Wednesday)
When: render weekly snippet
Then: Wednesday does not appear in Key Moments
      no "gap" annotation — just absent
```

**TS10.4 — Weekly standup** `should_pass`
```
Given: weekly dataset
When: render_standup() with weekly meta
Then: uses "This week:" / "Next week:" / "Blockers:"
      not "Yesterday:" / "Today:"
```

**TS10.5 — Decisions with dates in weekly** `should_pass`
```
Given: 3 decisions across the week
When: render_markdown() weekly
Then: "### Decisions Made (3)" with date annotations
      each entry shows "(Feb 18)" or similar
```

---

## Priority Matrix

```
MUST PASS (blocks ship) — 29 tests:
  TS1.1  Today range resolution
  TS1.2  Yesterday range resolution
  TS1.3  Week range resolution
  TS1.4  Custom range
  TS1.7  Project scoping
  TS2.1  Type-to-section mapping
  TS2.2  Session state split
  TS2.3  Session state split multiple surfaces
  TS2.4  Keyword completion override
  TS2.7  Empty sections omitted
  TS3.1  Full daily markdown
  TS3.2  Empty sections not rendered
  TS3.3  Empty range markdown
  TS3.5  Markdown deterministic
  TS4.1  Basic standup
  TS4.4  Empty standup
  TS5.1  Basic slack
  TS5.4  Empty slack
  TS6.1  JSON structure
  TS6.2  JSON empty
  TS7.1  Default invocation
  TS7.4  Empty range message
  TS8.1  generate_snippet registered
  TS8.2  Default MCP call
  TS9.1  Only session states
  TS9.2  Only durable entries
  TS9.4  Determinism across formats
  TS10.1 Weekly Key Moments
  TS10.2 Weekly Progress section

SHOULD PASS (fix within days) — 20 tests:
  TS1.5  Branch filter
  TS1.6  Cross-project mode
  TS1.8  Query ordering
  TS2.5  Keyword word boundary
  TS2.6  All completion keywords
  TS2.8  Plans always in-progress
  TS3.4  Branch in header
  TS4.2  Blockers from gotchas
  TS4.3  No blockers
  TS4.5  Weekly standup labels
  TS5.2  One line per item
  TS5.3  Max 15 lines
  TS5.5  Pattern emoji
  TS6.3  JSON round-trip
  TS7.2  Format flag
  TS7.3  No project detected
  TS7.5  Range flag parsing
  TS7.6  Branch flag
  TS8.3  Custom range MCP
  TS8.4  Format parameter MCP

NICE TO HAVE (v0.2.1):
  TS8.5  Empty via MCP
  TS9.3  Single entry
  TS9.5  Entries at range boundaries
  TS9.6  Surface extraction from tags
  TS9.7  No surface in tags
  TS10.3 Gap day handling
  TS10.4 Weekly standup
  TS10.5 Decisions with dates
```

---

## Summary

**Total tests: 57 across 10 subsystems**
- 29 must-pass (blocks ship)
- 20 should-pass (fix within days)
- 8 nice-to-have (v0.2.1)

**New mock data factories:** 5 (snippet_day, snippet_week, snippet_empty, snippet_session_split, snippet_durable_only)

**New source files:**
- `src/momento/snippet.py` — core logic
- `tests/test_snippet_*.py` — 10 test files

**No schema changes. No new entry types. No LLM. Read-only views over v0.1 data.**

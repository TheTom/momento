Note: Last checkpoint was 13m ago. Recent work may not be reflected. Run `momento save` or call log_knowledge() to capture latest progress.

*Yesterday:*
- Snippets v0.2 implementation complete. All 3 phases done: 59 tests across 10 files (all green), snippet.py core module, CLI command (momento snippet), MCP tool (generate_snippet). 410 total tests passing, 98% coverage. No commit yet.
- Checkpoint enforcement hooks fully working. Stop hook just fired and blocked — forced this checkpoint. Implementation: check-stale CLI command, Stop hook (30 min threshold), SessionStart hooks (compact/resume). Setup/teardown wired in setup_utils.py + setup.sh. All 410 tests passing. Next: consider adding tests for check-stale and hook registration functions.
- Added pre-push hook (tests + 95% coverage gate), fixed _is_momento_hook case bug, added 22 tests for check-stale and hook registration. Updated CLAUDE.md dev guide, .gitignore. 6 commits, 432 tests, 98% coverage, clean tree.
- Completed UX fix: Added "Momento Output Rules" section to CLAUDE_ADAPTER_BLOCK and CODEX_ADAPTER_CONTENT in setup_utils.py. Updated remove_claude_adapter() to handle both new and legacy headers. Updated test_setup_sh.py to match new adapter format. All 432 tests pass, 98.38% coverage. Committed as 2ec870b.
- Completed snippet staleness warning feature. _check_staleness() warns when last checkpoint >10min old. Text formats prepend note, JSON includes staleness_warning field. 5 new tests added (437 total, 98% coverage). Updated docs: reference.md (added snippet CLI, check-stale CLI, generate_snippet MCP tool), momento-tests.md (TS9.8 spec, counts), README badges. Committed as 9dd0a47. All pushed to main.
*Today:*
- Fixed standup snippet format: changed render_standup() from space-joining items into one blob to bullet-point list per section. Regenerated all 4 snippet examples in docs/snippets/. Also added docs sync convention to CLAUDE.md. 437 tests, 98% coverage. Committed fd1c403, pushed to main. Next: the Discovered/Blockers sections are noisy from ingested error logs — may want to filter or limit those in a future pass.
*Blockers:*
- Error: Exit code 1. (×8)
- Error: <tool_use_error>File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.</tool_use_error>.
- Error: <tool_use_error>No task found with ID: a26fa7c26074deb37</tool_use_error>.
- Error: <tool_use_error>Sibling tool call errored</tool_use_error>.
- Error: Exit code 128.
- This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.
- Error: Exit code 2.
- Error: <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>.

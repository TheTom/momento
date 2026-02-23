# Momento Snippet — Monday, Feb 23 2026
## momento

### Accomplished
- Snippets v0.2 implementation complete. All 3 phases done: 59 tests across 10 files (all green), snippet.py core module, CLI command (momento snippet), MCP tool (generate_snippet). 410 total tests passing, 98% coverage. No commit yet.
- Checkpoint enforcement hooks fully working. Stop hook just fired and blocked — forced this checkpoint. Implementation: check-stale CLI command, Stop hook (30 min threshold), SessionStart hooks (compact/resume). Setup/teardown wired in setup_utils.py + setup.sh. All 410 tests passing. Next: consider adding tests for check-stale and hook registration functions.
- Added pre-push hook (tests + 95% coverage gate), fixed _is_momento_hook case bug, added 22 tests for check-stale and hook registration. Updated CLAUDE.md dev guide, .gitignore. 6 commits, 432 tests, 98% coverage, clean tree.
- Completed UX fix: Added "Momento Output Rules" section to CLAUDE_ADAPTER_BLOCK and CODEX_ADAPTER_CONTENT in setup_utils.py. Updated remove_claude_adapter() to handle both new and legacy headers. Updated test_setup_sh.py to match new adapter format. All 432 tests pass, 98.38% coverage. Committed as 2ec870b.
- Completed snippet staleness warning feature. _check_staleness() warns when last checkpoint >10min old. Text formats prepend note, JSON includes staleness_warning field. 5 new tests added (437 total, 98% coverage). Updated docs: reference.md (added snippet CLI, check-stale CLI, generate_snippet MCP tool), momento-tests.md (TS9.8 spec, counts), README badges. Committed as 9dd0a47. All pushed to main.

### Decisions Made
- Implemented checkpoint enforcement hooks for Momento. Root cause: behavioral CLAUDE.md instructions were ignored during heavy implementation sessions, causing zero checkpoints. Fix: (1) Added `momento check-stale` CLI command (exits 0=fresh, 1=stale), (2) Stop hook blocks Claude from stopping if no checkpoint in 30+ min, (3) SessionStart hooks inject retrieve_context reminder after compact/resume. Setup/teardown updated: register_hooks() and unregister_hooks() in setup_utils.py, wired into setup.sh install and uninstall flows. Inline commands (no separate script files). All 410 tests passing.

### Discovered
- Error: Exit code 1
error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try brew install
    xyz, where xyz is the package you are tryin
Resolution: Homebrew-managed Python. Let me force-uninstall it and also check if it was installed via pipx.
- Error: Exit code 1

[0;36m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[0m
[0;36m  Momento — Deterministic State Recovery for AI Coding Agents[0m
[0;36m━━━━━━━━━━━━━━━━━
Resolution: The install succeeded (311 tests passing, venv created, CLI working) but the interactive MCP prompts failed because there's no TTY for `read -rp` in this shell. The `read` commands need stdin.

Let me
- Error: <tool_use_error>File has been modified since read, either by the user or by a linter. Read it again before attempting to write it.</tool_use_error>
Resolution: README done. Now the reference doc -- extracting the detailed content from the old README.
- Error: <tool_use_error>No task found with ID: a26fa7c26074deb37</tool_use_error>
Resolution: Let me verify the agents' work by checking the files directly.
- Error: <tool_use_error>Sibling tool call errored</tool_use_error>
Resolution: Let me verify the agents' work by checking the files directly.
- Error: Exit code 1
---
---

---
---
Resolution: Let me verify the agents' work by checking the files directly.
- Error: Exit code 1
tail: /private/tmp/claude-501/-Users-tom-dev-momento/tasks/bddb536.output: No such file or directory

tail: /private/tmp/claude-501/-Users-tom-dev-momento/tasks/bddb536.output: No such fil
Resolution: Let me verify the agents' work by checking the files directly.
- Error: Exit code 128
fatal: No configured push destination.
Either specify the URL from the command-line or configure a remote repository using

    git remote add <name> <url>

and then push using the remot
Resolution: No remote configured yet. Need to create the repo on GitHub first.
- This session is being continued from a previous conversation that ran out of context. The summary below covers the earlier portion of the conversation.

Analysis:
Let me go through the conversation chronologically to capture all important details.

1. **Initial Plan**: User provided a detailed plan for setup/uninstall script + tests + doc updates for Momento project. The plan covered:
   - New module: `src/momento/setup_utils.py`
   - Modify `setup.sh` with --yes, --uninstall, confirm(), marker, arg parsing
   - New test files: `tests/test_setup_utils.py` and `tests/test_setup_sh.py`
   - Update README.md, prd-momento-final-v2.md, momento-v1-tests.md

2. **Implementation Phase 1**: I read existing files (setup.sh, README.md, PRD, test plan, conftest.py, test_cli.py) to understand current patterns.

3. **Created `src/momento/setup_utils.py`**: Pure Python module with functions for register/unregister MCP, add/remove Claude adapter, generate/remove Codex adapter, plus CLI entrypoint.

4. **Rewrote `setup.sh`**: Added --yes/-y flag, TTY auto-detection, confirm() helper, --uninstall mode, .momento_created marker, while/case arg parsing, self-healing venv detection.

5. **Delegated work**: Used Task agents (NOT TeamCreate teammates). User got angry: "next time when i fuciing tell you to spin up teammates i expect you to do so."

6. **Test files created**: test_setup_utils.py (29 unit tests) and test_setup_sh.py (8 integration tests).

7. **Bug: Integration tests timing out**: --check mode runs full test suite in subprocess. Fixed by switching to --uninstall mode for flag-parsing tests.

8. **Bug: Integration tests nuking real .venv**: setup.sh does `cd "$(dirname "$0")"` so uninstall tests operated on real project root. Fixed by copying setup.sh to a temp directory for full sandbox isolation.

9. **Bug: Self-healing venv**: .venv had broken symlinks from Python upgrade. Added detection in setup_venv() to check if python3 binary exists and is executable.

10. **First commit**: `eb2ed86` - Add setup_utils module, --yes/--uninstall flags, and 37 new tests
11. **Second commit**: `9a0487c` - Fix self-healing venv and fully sandbox shell integration tests

12. **Setup attempt**: Running `./setup.sh --yes` worked for install but MCP integration failed because venv python3 didn't exist (broken symlinks). Had to manually create venv and register.

13. **MCP server not visible**: User ran /mcp and couldn't see the server. The config used bare `python3` which resolved to system Python (no momento installed). Fixed by using `sys.executable` (absolute venv path).

14. **Convention question**: User asked about industry standard for MCP servers. I explained official servers use `npx`/`uvx`. User pushed back on using `python3 -m momento.mcp_server` as the canonical pattern.

15. **Standardization to `momento-mcp`**: 
    - Added `momento-mcp` console script entry point in pyproject.toml
    - Added `main()` function in mcp_server.py
    - Changed MCP config to `{"command": "momento-mcp", "args": []}`
    - Updated README docs

16. **User's pipx standardization**: User made additional changes themselves:
    - setup.sh now uses `pipx install --force .` instead of venv + pip
    - Added `ensure_pipx()` function
    - Removed venv-related install functions (setup_venv, install_package, etc.)
    - Kept self-healing venv check for --check mode
    - Uninstall now uses `pipx uninstall momento`
    - Updated README to show pipx as standard, --user/--global as legacy aliases
    - Updated test_setup_sh.py: venv tests now assert venv is untouched (pipx doesn't manage venvs)
    - Removed "Zero external dependencies" from README (now requires pipx)

17. **User asked for summary**: "when done don't commit just tell me you're done" - then the current summary request.

Key files in their final state:

- `setup.sh`: pipx-based install, --yes/--uninstall, confirm(), TTY detection
- `src/momento/setup_utils.py`: register/unregister MCP (using "momento-mcp" command), add/remove Claude adapter, generate/remove Codex adapter
- `src/momento/mcp_server.py`: added main() function for console script entry point
- `pyproject.toml`: added `momento-mcp = "momento.mcp_server:main"` entry point
- `tests/test_setup_utils.py`: 29 unit tests
- `tests/test_setup_sh.py`: 8 integration tests (updated for pipx behavior)
- `README.md`: pipx install, momento-mcp docs
- `prd-momento-final-v2.md`: section 11.4 Setup & Uninstall Contract
- `momento-v1-tests.md`: T14 section with 7 tests

The user's most recent changes (which I haven't committed yet) include the pipx standardization of setup.sh, README, and test updates.

Summary:
1. Primary Request and Intent:
   The user asked me to implement a detailed plan for Momento's setup/uninstall infrastructure. The plan had 7 files to modify/create, covering: extracting inline Python from setup.sh into a testable module (`setup_utils.py`), adding `--yes`/`--uninstall` flags to setup.sh, writing unit and integration tests, and updating docs (README, PRD, test plan). Later, the user pushed for industry-standard MCP server conventions, ultimately standardizing on `pipx` as the install method and `momento-mcp` as the first-class executable name.

2. Key Technical Concepts:
   - **pipx** as the standard Python CLI tool installer (replaces venv + pip install -e)
   - **MCP server convention**: `"command": "momento-mcp"` with `"args": []` — not `python3 -m ...`
   - **Console script entry points** in pyproject.toml for `momento` and `momento-mcp`
   - **TTY auto-detection** in bash: `[[ ! -t 0 ]]` to default to yes mode in non-interactive environments
   - **Self-healing venvs**: detect broken Python symlinks from Homebrew upgrades
   - **`.momento_created` marker**: tracks whether momento created the venv (for safe uninstall)
   - **Sandbox isolation for shell tests**: copy setup.sh to temp dir so `cd "$(dirname "$0")"` can't affect real project
   - **FastMCP server** with `main()` entry point function

3. Files and Code Sections:

   - **`src/momento/setup_utils.py`** (CREATED)
     - Testable Python functions extracted from setup.sh heredocs
     - Used by setup.sh via `python3 -m momento.setup_utils <command> <path>`
     - Key functions: `register_mcp_server()`, `unregister_mcp_server()`, `add_claude_adapter()`, `remove_claude_adapter()`, `generate_codex_adapter()`, `remove_codex_adapter()`
     - MCP config uses `{"command": "momento-mcp", "args": [], "env": {"PYTHONUNBUFFERED": "1"}}`
     - `main()` dispatches CLI commands from shell
     - SPDX header: `# Copyright (c) 2026 Tom Turney` / `# SPDX-License-Identifier: Apache-2.0`

   - **`setup.sh`** (MODIFIED — user made final pipx changes)
     - Now uses `pipx install --force .` as standard install method
     - `ensure_pipx()` auto-installs pipx if missing
     - `--user`/`--global` are legacy aliases that route to pipx
     - `--yes`/`-y` flag + TTY auto-detection via `confirm()` helper
     - `--uninstall` mode: removes MCP config, CLAUDE.md adapter, .codex_instructions.md, pipx package; data dir defaults to NO
     - `--check` mode: still references venv for backward compat
     - `verify()` checks both `momento` and `momento-mcp` entry points
     - No more venv creation in install path — pipx handles isolation

   - **`src/momento/mcp_server.py`** (MODIFIED)
     - Added `main()` function for console script entry point:
       ```python
       def main():  # pragma: no cover
           """Entry point for the momento-mcp console script."""
           server.run()
       ```

   - **`pyproject.toml`** (MODIFIED)
     - Added entry point: `momento-mcp = "momento.mcp_server:main"`
     ```toml
     [project.scripts]
     momento = "momento.cli:main"
     momento-mcp = "momento.mcp_server:main"
     ```

   - **`tests/test_setup_utils.py`** (CREATED)
     - 29 unit tests across 7 test classes
     - Classes: TestRegisterMcpServer (4), TestUnregisterMcpServer (4), TestAddClaudeAdapter (3), TestRemoveClaudeAdapter (5), TestGenerateCodexAdapter (2), TestRemoveCodexAdapter (2), TestSetupUtilsMain (9)
     - All marked `@pytest.mark.should_pass`
     - Uses `tmp_path` for all file operations

   - **`tests/test_setup_sh.py`** (CREATED, user modified for pipx)
     - 8 integration tests in TestSetupShFlags class
     - Full sandbox: copies setup.sh to temp dir, sandboxed HOME
     - Tests: yes flag, no-TTY auto-yes, unknown flag, combined flags, uninstall cleans integration files, preserves data dir, venv tests now assert venvs are untouched (pipx doesn't manage venvs)
     - Key helper: `_make_sandbox()` creates tmp_home + tmp_project with setup.sh copy
     - MCP config in tests updated to `"command": "momento-mcp"`

   - **`README.md`** (MODIFIED — user made final pipx changes)
     - Install via `./setup.sh` or `pipx install .`
     - `--user`/`--global` documented as legacy aliases
     - Uninstall section uses `./setup.sh --uninstall`
     - MCP config example uses `momento-mcp`
     - Requirements now lists pipx
     - "Zero external dependencies" removed
     - CLI not found fix: `export PATH="$HOME/.local/bin:$PATH"`

   - **`prd-momento-final-v2.md`** (MODIFIED)
     - Added section 11.4 "Setup & Uninstall Contract"
     - Documents non-interactive mode, .momento_created marker, uninstall behavior table, data directory protection, Python utility functions

   - **`momento-v1-tests.md`** (MODIFIED)
     - Added T14 section: Setup & Uninstall (7 tests: T14.1-T14.7)
     - Updated priority lists: T14.1/T14.4-T14.7 as should_pass, T14.2/T14.3 as nice_to_have
     - Updated totals: 82 tests across 14 subsystems

   - **`~/.claude/settings.json`** (MODIFIED at runtime)
     - MCP server registered: `{"command": "momento-mcp", "args": [], "env": {"PYTHONUNBUFFERED": "1"}}`

4. Errors and Fixes:
   - **Integration tests timing out (30s)**: `--check` mode runs full test suite in subprocess. Fixed by switching flag-parsing tests to use `--uninstall` mode instead.
   - **Integration tests nuking real .venv**: `setup.sh` does `cd "$(dirname "$0")"` so uninstall ran in real project root. Fixed by copying setup.sh to a temp directory in `_make_sandbox()`.
   - **Broken venv symlinks**: `.venv/bin/python3` was a dead symlink from Homebrew Python upgrade. Added self-healing detection: `[[ ! -x "$VENV_DIR/bin/python3" ]] || ! "$VENV_DIR/bin/python3" -c "import sys"`.
   - **MCP server not visible in /mcp**: Config used bare `python3` which resolved to system Python without momento. Initially fixed with absolute venv path, then properly fixed with `momento-mcp` console script entry point.
   - **User feedback on teammates**: I used Task agents (subprocesses) instead of TeamCreate teammates. User explicitly said: "next time when i fuciing tell you to spin up teammates i expect you to do so." Must use TeamCreate for future team requests.
   - **Convention deviation**: I was using `python3 -m momento.mcp_server` as the MCP command. User pushed for industry standard: first-class executable `momento-mcp` as the interface contract, with `pipx`/`uvx` as distribution strategy underneath.

5. Problem Solving:
   - Solved non-TTY hanging by auto-detecting `[[ ! -t 0 ]]` and defaulting to yes mode
   - Solved test isolation by fully sandboxing both HOME and project directory
   - Solved MCP discovery by standardizing on `momento-mcp` console script
   - Solved install reliability by moving from venv to pipx (user's change)
   - Full roundtrip verified: uninstall --yes → install --yes → 348 tests pass

6. All User Messages:
   - "Implement the following plan: [detailed plan for setup/uninstall script + tests + doc updates]"
   - "next time when i fuciing tell you to spin up teammates i expect you to do so."
   - "when we reregister the mcp on updates we keep the knowledge db right?"
   - "ok commit"
   - "i did /mcp and i don't see the server there"
   - "what do official mcp servers do?"
   - "hrm are we going down the right path then with not following convention?"
   - "sigh yeah You're right. Standardization should be: [detailed explanation of momento-mcp as first-class command, pipx as distribution, standard MCP config]"
   - "when done don't commit just tell me you're done"
   - "Implemented. Standard MCP-server install flow is now pipx-first. [summary of user's own changes to setup.sh, README, tests]. No commit was made. i made changes take a look"

7. Pending Tasks:
   - **Commit needed**: All changes (both mine and user's pipx standardization) are uncommitted. User said "when done don't commit just tell me you're done" and then asked me to review their changes. No explicit commit request yet.
   - **Restart Claude Code**: MCP server config changed — need to restart for `momento-mcp` to appear in `/mcp`
   - **Run full test suite** with user's latest changes to confirm everything still passes

8. Current Work:
   The user made their own changes to standardize on pipx (modifying setup.sh, README.md, test_setup_sh.py) and asked me to "take a look" at what they changed. I read all three modified files. Then the user requested this summary. No explicit next task was given beyond reviewing the changes.

9. Optional Next Step:
   Run the full test suite to verify the user's pipx changes pass: `PYTHONPATH=src python3 -m pytest tests/ -v`. The user said "take a look" at their changes — I've read them but haven't yet confirmed they pass tests or provided feedback. However, the user also indicated "Validation - tests passed" in their message, so this may not be needed. Wait for user direction.

If you need specific details from before compaction (like exact code snippets, error messages, or content you generated), read the full transcript at: /Users/tom/.claude/projects/-Users-tom-dev-momento/b789524c-2cc0-4466-a562-1b2b6fc5ed9b.jsonl
Please continue the conversation from where we left off without asking the user any further questions. Continue with the last task that you were asked to work on.
- Error: Exit code 2
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-8.4.1, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.13/bin/python3.1
Resolution: Need to install the package first.
- Error: Exit code 1
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-8.4.1, pluggy-1.6.0 -- /opt/homebrew/opt/python@3.13/bin/python3.1
Resolution: The `--check` mode runs the full test suite inside a subprocess, causing timeouts. Let me fix the integration tests and address your teammate question — I was using Task agents (subprocesses), not ful
- Error: Exit code 1
(eval):1: no matches found: .venv/bin/python*

(eval):1: no matches found: .venv/bin/python*
Resolution: The .venv is gone — likely had broken symlinks from a Python upgrade. Let me create a fresh one.
- Error: Exit code 1
ls: .venv/: No such file or directory

ls: .venv/: No such file or directory
Resolution: The .venv is gone — likely had broken symlinks from a Python upgrade. Let me create a fresh one.
- Error: Exit code 1
(eval):1: no matches found: .venv/bin/python*

(eval):1: no matches found: .venv/bin/python*
Resolution: Found the bug. The integration test `test_uninstall_yes_cleans_integration_files` runs `setup.sh --uninstall --yes` which CDs to the real project root and nukes the real `.venv` because our `setup_ven
- Error: <tool_use_error>File has not been read yet. Read it first before writing to it.</tool_use_error>
Resolution: Now clean the stale entry from `settings.json` and run tests:

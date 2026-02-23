# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Setup and teardown utilities for Momento installation.

Extracted from inline heredocs in setup.sh into testable Python functions.
Used by setup.sh for --install and --uninstall operations.

Usage from shell:
    python3 -m momento.setup_utils register_mcp <claude_json_path>
    python3 -m momento.setup_utils unregister_mcp <claude_json_path>
    python3 -m momento.setup_utils add_claude_adapter <claude_md_path>
    python3 -m momento.setup_utils remove_claude_adapter <claude_md_path>
    python3 -m momento.setup_utils generate_codex_adapter <codex_path>
    python3 -m momento.setup_utils remove_codex_adapter <codex_path>
"""

import json
import os
import re
import sys
import tempfile

# ---------------------------------------------------------------------------
# MCP Server Registration
# ---------------------------------------------------------------------------

def _mcp_server_config():
    """Return MCP config using the absolute path to momento-mcp."""
    import shutil

    cmd = shutil.which("momento-mcp") or "momento-mcp"
    return {
        "command": cmd,
        "args": [],
        "env": {"PYTHONUNBUFFERED": "1"},
    }


def _ensure_parent_dir(path: str) -> None:
    """Create parent directory for path if one is present."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _write_json_atomic(path: str, data: dict) -> None:
    """Write JSON atomically to avoid partial/corrupted files."""
    _ensure_parent_dir(path)
    parent = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=parent, delete=False
    ) as tmp:
        json.dump(data, tmp, indent=2)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def register_mcp_server(settings_path: str) -> bool:
    """Add momento to mcpServers in ~/.claude.json.

    Creates the file and parent dirs if they don't exist.
    Idempotent — re-registering overwrites with latest config.

    Returns True on success, False on error.
    """
    try:
        data = {}
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                data = json.load(f)

        if "mcpServers" not in data:
            data["mcpServers"] = {}

        data["mcpServers"]["momento"] = _mcp_server_config()

        _write_json_atomic(settings_path, data)

        return True
    except Exception:
        return False


def unregister_mcp_server(settings_path: str) -> bool:
    """Remove momento from mcpServers in ~/.claude.json.

    Cleans up empty mcpServers key if no other servers remain.
    Noop if file doesn't exist or momento not registered.

    Returns True on success (including noop), False on error.
    """
    try:
        if not os.path.exists(settings_path):
            return True

        with open(settings_path) as f:
            data = json.load(f)

        mcp = data.get("mcpServers", {})
        if "momento" not in mcp:
            return True

        del mcp["momento"]

        # Clean up empty mcpServers key
        if not mcp:
            del data["mcpServers"]

        _write_json_atomic(settings_path, data)

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Claude Adapter (CLAUDE.md)
# ---------------------------------------------------------------------------

CLAUDE_ADAPTER_HEADER = "## Momento Context Recovery"

CLAUDE_ADAPTER_BLOCK = """
## Momento Context Recovery

After any significant file change, decision, or completed subtask:
  Call log_knowledge(type="session_state", tags=[<relevant domains>])
  with what was done, what was decided, and what's next.
  Keep it brief. Context can compact without warning.

At session start or after /clear:
  Call retrieve_context(include_session_state=true).
  Use the returned context to orient yourself before taking action.

When the user says "checkpoint" or "save progress":
  Call log_knowledge(type="session_state", tags=[<relevant domains>])
  with current task progress, decisions made, and remaining work.

Before /compact (when user explicitly runs it):
  Call log_knowledge(type="session_state", tags=["checkpoint"])
  with comprehensive progress summary before executing.

When encountering an unfamiliar error:
  Call retrieve_context(query="<error description>").

Before implementing a recurring pattern (auth, networking, persistence, caching):
  Call retrieve_context(query="<pattern name>").

After finalizing a significant decision or plan:
  Call log_knowledge(type="decision" or "plan", tags=[<domains>])
  with the decision, rationale, rejected alternatives, and implications.
  Use the Historical Slice structure.
"""

# End marker: last line of the adapter block
_ADAPTER_END_MARKER = "Use the Historical Slice structure."


def add_claude_adapter(claude_md_path: str) -> bool:
    """Append the Momento adapter section to CLAUDE.md.

    Creates the file and parent dirs if they don't exist.
    Idempotent — skips if adapter header already present.

    Returns True on success, False on error.
    """
    try:
        content = ""
        if os.path.exists(claude_md_path):
            with open(claude_md_path) as f:
                content = f.read()

        # Idempotent check
        if CLAUDE_ADAPTER_HEADER in content:
            return True

        os.makedirs(os.path.dirname(claude_md_path), exist_ok=True)
        with open(claude_md_path, "a") as f:
            f.write(CLAUDE_ADAPTER_BLOCK)

        return True
    except Exception:
        return False


def remove_claude_adapter(claude_md_path: str) -> bool:
    """Remove the Momento adapter section from CLAUDE.md.

    Strips from '## Momento Context Recovery' through the end marker line.
    Preserves surrounding content. Noop if not present or file missing.

    Returns True on success (including noop), False on error.
    """
    try:
        if not os.path.exists(claude_md_path):
            return True

        with open(claude_md_path) as f:
            content = f.read()

        if CLAUDE_ADAPTER_HEADER not in content:
            return True

        # Match from the adapter header through the end marker line,
        # including any leading blank lines before the header
        pattern = (
            r"\n*## Momento Context Recovery\n"
            r".*?"
            + re.escape(_ADAPTER_END_MARKER)
            + r"\n?"
        )
        cleaned = re.sub(pattern, "", content, flags=re.DOTALL)

        # Remove trailing whitespace but keep a final newline if content exists
        cleaned = cleaned.rstrip()
        if cleaned:
            cleaned += "\n"

        with open(claude_md_path, "w") as f:
            f.write(cleaned)

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Claude Code Hooks (checkpoint guard + context recovery)
# ---------------------------------------------------------------------------

# Inline commands — no separate scripts needed, uses `momento` CLI on PATH.
_STOP_HOOK_CMD = (
    'momento check-stale --threshold 30 >/dev/null 2>&1 || '
    '(echo \'CHECKPOINT REQUIRED: No Momento checkpoint in 30+ minutes. '
    'Call log_knowledge(type="session_state", tags=[<relevant domains>]) '
    'with what was done, decisions made, and what is next.\' >&2; exit 2)'
)

_SESSION_RESTORE_COMPACT_CMD = (
    "echo 'CONTEXT RECOVERY: Session restored after compaction. "
    "Call retrieve_context(include_session_state=true) to restore "
    "Momento context before taking action.'"
)

_SESSION_RESTORE_RESUME_CMD = (
    "echo 'CONTEXT RECOVERY: Session resumed from previous conversation. "
    "Call retrieve_context(include_session_state=true) to restore "
    "Momento context before taking action.'"
)


def _is_momento_hook(hook_config: dict) -> bool:
    """Check if a hook config entry belongs to Momento."""
    for h in hook_config.get("hooks", []):
        cmd = h.get("command", "")
        if "momento" in cmd and "claude_terminal" not in cmd:
            return True
    return False


def register_hooks(settings_path: str) -> bool:
    """Register Momento hooks in ~/.claude/settings.json.

    Adds:
    - Stop hook: checkpoint staleness guard (blocks if no checkpoint in 30+ min)
    - SessionStart hooks: context recovery reminders after compact/resume

    Idempotent — removes existing Momento hooks before adding fresh ones.

    Returns True on success, False on error.
    """
    try:
        data = {}
        if os.path.exists(settings_path):
            with open(settings_path) as f:
                data = json.load(f)

        if "hooks" not in data:
            data["hooks"] = {}

        hooks = data["hooks"]

        # Remove any existing Momento hooks first (idempotent)
        for event in ("Stop", "SessionStart"):
            if event in hooks:
                hooks[event] = [h for h in hooks[event] if not _is_momento_hook(h)]

        # Add Stop checkpoint guard
        hooks.setdefault("Stop", []).append({
            "hooks": [{"type": "command", "command": _STOP_HOOK_CMD}],
        })

        # Add SessionStart recovery (compact + resume)
        hooks.setdefault("SessionStart", []).append({
            "matcher": "compact",
            "hooks": [{"type": "command", "command": _SESSION_RESTORE_COMPACT_CMD}],
        })
        hooks.setdefault("SessionStart", []).append({
            "matcher": "resume",
            "hooks": [{"type": "command", "command": _SESSION_RESTORE_RESUME_CMD}],
        })

        _write_json_atomic(settings_path, data)
        return True
    except Exception:
        return False


def unregister_hooks(settings_path: str) -> bool:
    """Remove Momento hooks from ~/.claude/settings.json.

    Removes any hook config whose command contains 'momento'
    (but not 'claude_terminal'). Preserves all other hooks.

    Returns True on success (including noop), False on error.
    """
    try:
        if not os.path.exists(settings_path):
            return True

        with open(settings_path) as f:
            data = json.load(f)

        hooks = data.get("hooks", {})
        changed = False

        for event in ("Stop", "SessionStart"):
            if event in hooks:
                before = len(hooks[event])
                hooks[event] = [h for h in hooks[event] if not _is_momento_hook(h)]
                if len(hooks[event]) != before:
                    changed = True
                # Clean up empty arrays
                if not hooks[event]:
                    del hooks[event]

        if changed:
            _write_json_atomic(settings_path, data)

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Codex Adapter (.codex_instructions.md)
# ---------------------------------------------------------------------------

CODEX_ADAPTER_CONTENT = """\
## Momento Checkpointing and Context Recovery

You are paired with a local memory layer called Momento that stores
durable checkpoints, decisions, plans, and known gotchas for the
current project.

### Checkpoint Conditions

After you complete any of the following during a session:
  - A significant file change (multi-file patch or cross-layer update)
  - A resolved error with a concrete fix
  - A finalized plan or architectural decision
  - A completed subtask that meaningfully advances the main work
  - A step that would be costly to re-explain if lost

Call the MCP tool:
  log_knowledge(
    type="session_state",
    content=<concise summary of progress, decisions, remaining tasks>,
    tags=[<relevant domains>]
  )

### Save Before Risky Operations

Before any operation that might reduce internal context (large patch
application, file renames, or before leaving the session):
  log_knowledge(type="session_state", ...)

### Retrieval Triggers

At session start or after any context loss (restart, resume, new chat):
  Call retrieve_context(include_session_state=true).
  Use the returned structured directives to orient yourself before
  generating further code.

When encountering an unfamiliar error:
  Call retrieve_context(query="<error description>").

### Decision and Plan Logging

When you finalize a significant design decision or long-term plan:
  log_knowledge(
    type="decision" or "plan",
    content=<Historical Slice structure>,
    tags=[<relevant domains>]
  )

Historical Slice structure:
  Decision: <What was chosen>
  Rationale: <Why, tradeoffs, constraints>
  Rejected: <Alternatives and why not>
  Implications: <Consequences>

### Behavior Expectations

- Checkpoint on meaningful advancement only — not trivial edits
- Do not checkpoint during speculative brainstorming
- Do not rely on internal percentages or guesses about context usage
- Only checkpoint when a logical subtask completes or before known risk
"""


def generate_codex_adapter(codex_path: str) -> bool:
    """Write .codex_instructions.md with Momento integration instructions.

    Overwrites if file already exists.

    Returns True on success, False on error.
    """
    try:
        os.makedirs(os.path.dirname(codex_path) or ".", exist_ok=True)
        with open(codex_path, "w") as f:
            f.write(CODEX_ADAPTER_CONTENT)
        return True
    except Exception:
        return False


def remove_codex_adapter(codex_path: str) -> bool:
    """Delete .codex_instructions.md if it exists.

    Noop if file doesn't exist.

    Returns True on success (including noop), False on error.
    """
    try:
        if os.path.exists(codex_path):
            os.remove(codex_path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# CLI entrypoint for use from setup.sh
# ---------------------------------------------------------------------------

def main():
    """Dispatch setup_utils commands from shell.

    Usage:
        python3 -m momento.setup_utils <command> <path>
    """
    if len(sys.argv) < 3:
        print("Usage: python3 -m momento.setup_utils <command> <path>",
              file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    path = sys.argv[2]

    dispatch = {
        "register_mcp": register_mcp_server,
        "unregister_mcp": unregister_mcp_server,
        "add_claude_adapter": add_claude_adapter,
        "remove_claude_adapter": remove_claude_adapter,
        "register_hooks": register_hooks,
        "unregister_hooks": unregister_hooks,
        "generate_codex_adapter": generate_codex_adapter,
        "remove_codex_adapter": remove_codex_adapter,
    }

    func = dispatch.get(command)
    if func is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)

    ok = func(path)
    if ok:
        print("done")
    else:
        print(f"failed: {command} {path}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

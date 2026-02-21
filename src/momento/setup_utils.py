# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Setup and teardown utilities for Momento installation.

Extracted from inline heredocs in setup.sh into testable Python functions.
Used by setup.sh for --install and --uninstall operations.

Usage from shell:
    python3 -m momento.setup_utils register_mcp <settings_path>
    python3 -m momento.setup_utils unregister_mcp <settings_path>
    python3 -m momento.setup_utils add_claude_adapter <claude_md_path>
    python3 -m momento.setup_utils remove_claude_adapter <claude_md_path>
    python3 -m momento.setup_utils generate_codex_adapter <codex_path>
    python3 -m momento.setup_utils remove_codex_adapter <codex_path>
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# MCP Server Registration
# ---------------------------------------------------------------------------

_MCP_SERVER_CONFIG = {
    "command": "momento-mcp",
    "args": [],
    "env": {"PYTHONUNBUFFERED": "1"},
}


def register_mcp_server(settings_path: str) -> bool:
    """Add momento to mcpServers in Claude Code settings.json.

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

        data["mcpServers"]["momento"] = _MCP_SERVER_CONFIG

        os.makedirs(os.path.dirname(settings_path), exist_ok=True)
        with open(settings_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

        return True
    except Exception:
        return False


def unregister_mcp_server(settings_path: str) -> bool:
    """Remove momento from mcpServers in Claude Code settings.json.

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

        with open(settings_path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

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

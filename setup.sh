#!/usr/bin/env bash
# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0
# Momento — setup & install script
# Usage:
#   ./setup.sh          # Interactive install (creates venv, installs package + dev deps)
#   ./setup.sh --user   # Install to user site-packages (no venv)
#   ./setup.sh --global # Install to current interpreter environment (no venv)
#   ./setup.sh --check  # Verify existing installation
set -euo pipefail

MOMENTO_DIR="$HOME/.momento"
DB_PATH="$MOMENTO_DIR/knowledge.db"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
VENV_DIR=".venv"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { echo -e "${CYAN}[info]${NC}  $*"; }
ok()    { echo -e "${GREEN}[ok]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
fail()  { echo -e "${RED}[fail]${NC}  $*"; exit 1; }

# --- Python version check ---
check_python() {
    local py=""
    for candidate in python3 python; do
        if command -v "$candidate" &>/dev/null; then
            py="$candidate"
            break
        fi
    done
    [[ -z "$py" ]] && fail "Python not found. Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+."

    local version
    version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    local major minor
    major=$(echo "$version" | cut -d. -f1)
    minor=$(echo "$version" | cut -d. -f2)

    if (( major < MIN_PYTHON_MAJOR )) || { (( major == MIN_PYTHON_MAJOR )) && (( minor < MIN_PYTHON_MINOR )); }; then
        fail "Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ required (found $version)."
    fi
    ok "Python $version ($py)"
    PYTHON="$py"
}

# --- Create ~/.momento directory ---
ensure_data_dir() {
    if [[ -d "$MOMENTO_DIR" ]]; then
        ok "Data directory exists: $MOMENTO_DIR"
    else
        mkdir -p "$MOMENTO_DIR"
        ok "Created data directory: $MOMENTO_DIR"
    fi
}

# --- Venv setup ---
setup_venv() {
    if [[ -d "$VENV_DIR" ]]; then
        info "Existing venv found at $VENV_DIR"
    else
        info "Creating virtual environment at $VENV_DIR ..."
        "$PYTHON" -m venv "$VENV_DIR"
        ok "Virtual environment created"
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHON="python3"
    ok "Activated venv: $VENV_DIR"
}

# --- Install package ---
install_package() {
    local mode="${1:-dev}"
    info "Installing momento (${mode} mode) ..."
    if [[ "$mode" == "dev" ]]; then
        "$PYTHON" -m pip install -e ".[dev]" --quiet
    else
        "$PYTHON" -m pip install . --quiet
    fi
    ok "Package installed"
}

# --- Install global (no venv) ---
install_global() {
    info "Installing momento to current interpreter environment ..."
    "$PYTHON" -m pip install -e ".[dev]" --quiet --break-system-packages 2>/dev/null \
        || "$PYTHON" -m pip install -e ".[dev]" --quiet
    ok "Package installed (global)"
}

# --- Install to user site-packages (no venv) ---
install_user() {
    info "Installing momento to user site-packages ..."
    "$PYTHON" -m pip install --user -e ".[dev]" --quiet
    ok "Package installed (user)"
}

# --- Verify installation ---
verify() {
    info "Verifying installation ..."

    # Check import
    if "$PYTHON" -c "import momento; print(f'momento {momento.__version__}')" &>/dev/null; then
        local ver
        ver=$("$PYTHON" -c "import momento; print(momento.__version__)")
        ok "Import works: momento $ver"
    else
        fail "Cannot import momento"
    fi

    # Check CLI entry point
    if command -v momento &>/dev/null; then
        ok "CLI entry point: $(command -v momento)"
    else
        warn "CLI 'momento' not on PATH (may need to activate venv or restart shell)"
    fi

    # Check DB can be created
    DB_PATH="$DB_PATH" "$PYTHON" -c "
import os
from momento.db import ensure_db
conn = ensure_db(os.environ['DB_PATH'])
conn.close()
" && ok "Database OK: $DB_PATH" || fail "Database creation failed"

    # Check test suite (dev mode only)
    if "$PYTHON" -m pytest --version &>/dev/null; then
        info "Running tests ..."
        if "$PYTHON" -m pytest tests/ -q --tb=line 2>&1; then
            ok "All tests passing"
        else
            warn "Some tests failed (see above)"
        fi
    fi
}

# --- MCP & Agent Integration (interactive) ---
register_mcp_server() {
    local settings_file="$HOME/.claude/settings.json"
    mkdir -p "$(dirname "$settings_file")"

    "$PYTHON" -c "
import json, os
path = '$settings_file'
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
if 'mcpServers' not in data:
    data['mcpServers'] = {}
data['mcpServers']['momento'] = {
    'command': 'python3',
    'args': ['-m', 'momento.mcp_server'],
    'env': {'PYTHONUNBUFFERED': '1'}
}
with open(path, 'w') as f:
    json.dump(data, f, indent=2)
print('done')
" && ok "Registered MCP server in $settings_file" \
  || warn "Could not update $settings_file"
}

add_claude_adapter() {
    local claude_md="$HOME/.claude/CLAUDE.md"
    mkdir -p "$(dirname "$claude_md")"

    if [[ -f "$claude_md" ]] && grep -q "Momento Context Recovery" "$claude_md"; then
        ok "Momento adapter already present in $claude_md"
        return 0
    fi

    cat >> "$claude_md" << 'ADAPTER'

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
ADAPTER
    ok "Appended Momento adapter to $claude_md"
}

generate_codex_adapter() {
    local codex_file="./.codex_instructions.md"

    cat > "$codex_file" << 'CODEX'
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
CODEX
    ok "Generated $codex_file"
}

setup_mcp_integration() {
    echo ""
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "  MCP & Agent Integration"
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # --- Register MCP server in Claude Code ---
    read -rp "Register Momento as an MCP server in Claude Code? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
        register_mcp_server
    fi

    # --- Add adapter instructions to CLAUDE.md ---
    read -rp "Add Momento instructions to your global CLAUDE.md? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
        add_claude_adapter
    fi

    # --- Generate .codex_instructions.md ---
    read -rp "Generate .codex_instructions.md in this project? [Y/n] " ans
    if [[ "${ans:-Y}" =~ ^[Yy]$ ]]; then
        generate_codex_adapter
    fi
}

# --- Check-only mode ---
check_only() {
    echo ""
    info "Checking existing Momento installation ..."
    echo ""
    check_python

    # Try venv first
    if [[ -f "$VENV_DIR/bin/activate" ]]; then
        # shellcheck disable=SC1091
        source "$VENV_DIR/bin/activate"
        PYTHON="python3"
    fi

    ensure_data_dir
    verify
    echo ""
    ok "Momento is installed and working."
}

# --- Main ---
main() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Momento — Deterministic State Recovery for AI Coding Agents${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    local mode="${1:-}"

    if [[ "$mode" == "--check" ]]; then
        check_only
        return 0
    fi

    if [[ -n "$mode" ]] && [[ "$mode" != "--global" ]] && [[ "$mode" != "--user" ]]; then
        fail "Unknown option: $mode (expected: --global, --user, --check)"
    fi

    # Step 1: Python
    check_python

    # Step 2: Data directory
    ensure_data_dir

    # Step 3: Install
    if [[ "$mode" == "--global" ]]; then
        install_global
    elif [[ "$mode" == "--user" ]]; then
        install_user
    else
        setup_venv
        install_package "dev"
    fi

    # Step 4: Verify
    verify

    # Step 5: MCP & Agent Integration
    setup_mcp_integration

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    ok "Momento installed successfully!"
    echo ""
    if [[ "$mode" == "" ]]; then
        info "Activate the venv:  source ${VENV_DIR}/bin/activate"
    fi
    info "Run the CLI:        momento status"
    info "Run tests:          pytest tests/ -v"
    info "Check coverage:     pytest tests/ --cov=momento --cov-branch"
    echo ""
}

cd "$(dirname "$0")"
main "$@"

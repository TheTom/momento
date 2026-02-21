#!/usr/bin/env bash
# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0
# Momento — setup & install script
# Usage:
#   ./setup.sh              # Interactive install (standard pipx install)
#   ./setup.sh --user       # Legacy alias (uses standard pipx install)
#   ./setup.sh --global     # Legacy alias (uses standard pipx install)
#   ./setup.sh --check      # Verify existing installation
#   ./setup.sh --uninstall  # Interactive uninstall
#   ./setup.sh --yes        # Non-interactive (auto-confirm all prompts)
#   ./setup.sh -y           # Short form of --yes
set -euo pipefail

MOMENTO_DIR="$HOME/.momento"
DB_PATH="$MOMENTO_DIR/knowledge.db"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=11
VENV_DIR=".venv"
YES_MODE=false

# Auto-default to yes when no TTY (piped, CI, subshell)
if [[ ! -t 0 ]]; then YES_MODE=true; fi

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

# --- Confirm helper (respects --yes and TTY detection) ---
confirm() {
    local prompt="$1"
    if [[ "$YES_MODE" == "true" ]]; then
        info "$prompt [auto-yes]"
        return 0
    fi
    read -rp "$prompt " ans
    [[ "${ans:-Y}" =~ ^[Yy]$ ]]
}

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

ensure_pipx() {
    if command -v pipx &>/dev/null; then
        PIPX="pipx"
        ok "pipx found: $(command -v pipx)"
        return 0
    fi

    warn "pipx not found on PATH. Installing pipx with user pip ..."
    "$PYTHON" -m pip install --user pipx --quiet || fail "Failed to install pipx"

    if "$PYTHON" -m pipx --version &>/dev/null; then
        PIPX="$PYTHON -m pipx"
        ok "pipx installed (python module mode)"
    else
        fail "pipx installation failed"
    fi
}

install_standard() {
    info "Installing momento via pipx (standard MCP server install) ..."
    # Use module mode if needed, otherwise normal executable.
    if [[ "$PIPX" == "pipx" ]]; then
        pipx install --force . || fail "pipx install failed"
    else
        $PIPX install --force . || fail "pipx install failed"
    fi
    ok "Package installed via pipx"

    # Resolve the Python inside pipx's venv for setup_utils calls
    local pipx_venvs
    pipx_venvs="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || echo "$HOME/.local/pipx/venvs")"
    if [[ -x "$pipx_venvs/momento/bin/python3" ]]; then
        PIPX_PYTHON="$pipx_venvs/momento/bin/python3"
    else
        PIPX_PYTHON="$PYTHON"
        warn "Could not locate pipx venv Python — setup_utils may fail"
    fi
}

# --- Verify installation ---
verify() {
    info "Verifying installation ..."

    # Check CLI entry points
    if command -v momento &>/dev/null; then
        ok "CLI entry point: $(command -v momento)"
    else
        fail "CLI 'momento' not on PATH"
    fi
    if command -v momento-mcp &>/dev/null; then
        ok "MCP entry point: $(command -v momento-mcp)"
    else
        fail "MCP server 'momento-mcp' not on PATH"
    fi

    # Check DB can be created
    MOMENTO_DB="$DB_PATH" momento status >/dev/null 2>&1 \
        && ok "Database OK: $DB_PATH" \
        || fail "Database creation failed"
}

# --- MCP & Agent Integration ---
register_mcp_server() {
    local settings_file="$HOME/.claude.json"
    local py="${PIPX_PYTHON:-$PYTHON}"

    "$py" -m momento.setup_utils register_mcp "$settings_file" \
        && ok "Registered MCP server in $settings_file" \
        || warn "Could not update $settings_file"
}

add_claude_adapter() {
    local claude_md="$HOME/.claude/CLAUDE.md"
    local py="${PIPX_PYTHON:-$PYTHON}"

    "$py" -m momento.setup_utils add_claude_adapter "$claude_md" \
        && ok "Momento adapter present in $claude_md" \
        || warn "Could not update $claude_md"
}

generate_codex_adapter() {
    local codex_file="./.codex_instructions.md"
    local py="${PIPX_PYTHON:-$PYTHON}"

    "$py" -m momento.setup_utils generate_codex_adapter "$codex_file" \
        && ok "Generated $codex_file" \
        || warn "Could not generate $codex_file"
}

setup_mcp_integration() {
    echo ""
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "  MCP & Agent Integration"
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # --- Register MCP server in Claude Code ---
    if confirm "Register Momento as an MCP server in Claude Code? [Y/n]"; then
        register_mcp_server
    fi

    # --- Add adapter instructions to CLAUDE.md ---
    if confirm "Add Momento instructions to your global CLAUDE.md? [Y/n]"; then
        add_claude_adapter
    fi

    # --- Generate .codex_instructions.md ---
    if confirm "Generate .codex_instructions.md in this project? [Y/n]"; then
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

# --- Uninstall ---
do_uninstall() {
    echo ""
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "  Momento — Uninstall"
    info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Find a working python — prefer pipx venv, fall back to system
    local py=""
    local pipx_venvs
    pipx_venvs="$(pipx environment --value PIPX_LOCAL_VENVS 2>/dev/null || echo "$HOME/.local/pipx/venvs")"
    if [[ -x "$pipx_venvs/momento/bin/python3" ]]; then
        py="$pipx_venvs/momento/bin/python3"
    else
        for candidate in python3 python; do
            if command -v "$candidate" &>/dev/null; then
                py="$candidate"
                break
            fi
        done
    fi

    if [[ -z "$py" ]]; then
        warn "Python not found — skipping Python-based cleanup"
    else
        # Remove MCP server registration
        local settings_file="$HOME/.claude.json"
        if [[ -f "$settings_file" ]]; then
            if confirm "Remove Momento MCP server from $settings_file? [Y/n]"; then
                "$py" -m momento.setup_utils unregister_mcp "$settings_file" 2>/dev/null \
                    && ok "Removed MCP server from $settings_file" \
                    || warn "Could not update $settings_file"
            fi
        fi

        # Remove CLAUDE.md adapter
        local claude_md="$HOME/.claude/CLAUDE.md"
        if [[ -f "$claude_md" ]] && grep -q "Momento Context Recovery" "$claude_md" 2>/dev/null; then
            if confirm "Remove Momento adapter from $claude_md? [Y/n]"; then
                "$py" -m momento.setup_utils remove_claude_adapter "$claude_md" 2>/dev/null \
                    && ok "Removed Momento adapter from $claude_md" \
                    || warn "Could not update $claude_md"
            fi
        fi

        # Remove .codex_instructions.md
        if [[ -f "./.codex_instructions.md" ]]; then
            if confirm "Remove .codex_instructions.md? [Y/n]"; then
                "$py" -m momento.setup_utils remove_codex_adapter "./.codex_instructions.md" 2>/dev/null \
                    && ok "Removed .codex_instructions.md" \
                    || warn "Could not remove .codex_instructions.md"
            fi
        fi

        # Uninstall pipx package
        if confirm "Uninstall momento pipx package? [Y/n]"; then
            if command -v pipx &>/dev/null; then
                pipx uninstall momento >/dev/null 2>&1 \
                    && ok "Uninstalled momento pipx package" \
                    || warn "Could not uninstall momento via pipx (may not be installed)"
            else
                "$py" -m pipx uninstall momento >/dev/null 2>&1 \
                    && ok "Uninstalled momento pipx package" \
                    || warn "Could not uninstall momento via pipx (may not be installed)"
            fi
        fi
    fi

    # Data directory — defaults to NO, requires explicit yes
    if [[ -d "$MOMENTO_DIR" ]]; then
        echo ""
        warn "Data directory: $MOMENTO_DIR"
        warn "This contains your knowledge database. Removal is permanent."
        if [[ "$YES_MODE" == "true" ]]; then
            info "Remove $MOMENTO_DIR? [auto-NO — use explicit confirmation to remove data]"
        else
            read -rp "Remove $MOMENTO_DIR? [y/N] " ans
            if [[ "${ans:-N}" =~ ^[Yy]$ ]]; then
                rm -rf "$MOMENTO_DIR"
                ok "Removed $MOMENTO_DIR"
            else
                info "Kept $MOMENTO_DIR"
            fi
        fi
    fi

    echo ""
    ok "Uninstall complete."
}

# --- Main ---
main() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Momento — Deterministic State Recovery for AI Coding Agents${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    # Parse arguments
    local mode=""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --yes|-y)
                YES_MODE=true
                shift
                ;;
            --check)
                mode="check"
                shift
                ;;
            --uninstall)
                mode="uninstall"
                shift
                ;;
            --global)
                mode="global"
                shift
                ;;
            --user)
                mode="user"
                shift
                ;;
            *)
                fail "Unknown option: $1 (expected: --global, --user, --check, --uninstall, --yes)"
                ;;
        esac
    done

    if [[ "$mode" == "check" ]]; then
        check_only
        return 0
    fi

    if [[ "$mode" == "uninstall" ]]; then
        do_uninstall
        return 0
    fi

    # Step 1: Python
    check_python

    # Step 2: Data directory
    ensure_data_dir

    # Step 3: Install (standardized)
    if [[ "$mode" == "global" || "$mode" == "user" ]]; then
        warn "--$mode is now a legacy alias. Using standard pipx installation."
    fi
    ensure_pipx
    install_standard

    # Step 4: Verify
    verify

    # Step 5: MCP & Agent Integration
    setup_mcp_integration

    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    ok "Momento installed successfully!"
    echo ""
    info "Run the CLI:        momento status"
    info "Run MCP server:     momento-mcp"
    echo ""
}

cd "$(dirname "$0")"
main "$@"

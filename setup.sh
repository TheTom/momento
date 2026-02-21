#!/usr/bin/env bash
# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0
# Momento — setup & install script
# Usage:
#   ./setup.sh              # Interactive install (creates venv, installs package + dev deps)
#   ./setup.sh --user       # Install to user site-packages (no venv)
#   ./setup.sh --global     # Install to current interpreter environment (no venv)
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

# --- Venv setup ---
setup_venv() {
    if [[ -d "$VENV_DIR" ]]; then
        info "Existing venv found at $VENV_DIR"
    else
        info "Creating virtual environment at $VENV_DIR ..."
        "$PYTHON" -m venv "$VENV_DIR"
        ok "Virtual environment created"
    fi
    # Mark that momento created this venv
    touch "$VENV_DIR/.momento_created"
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

# --- MCP & Agent Integration ---
register_mcp_server() {
    local settings_file="$HOME/.claude/settings.json"
    local py="${1:-$PYTHON}"

    "$py" -m momento.setup_utils register_mcp "$settings_file" \
        && ok "Registered MCP server in $settings_file" \
        || warn "Could not update $settings_file"
}

add_claude_adapter() {
    local claude_md="$HOME/.claude/CLAUDE.md"
    local py="${1:-$PYTHON}"

    "$py" -m momento.setup_utils add_claude_adapter "$claude_md" \
        && ok "Momento adapter present in $claude_md" \
        || warn "Could not update $claude_md"
}

generate_codex_adapter() {
    local codex_file="./.codex_instructions.md"
    local py="${1:-$PYTHON}"

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

    # Find a working python — prefer venv, fall back to system
    local py=""
    if [[ -f "$VENV_DIR/bin/python3" ]]; then
        py="$VENV_DIR/bin/python3"
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
        local settings_file="$HOME/.claude/settings.json"
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

        # Uninstall pip package
        if confirm "Uninstall momento pip package? [Y/n]"; then
            "$py" -m pip uninstall -y momento --quiet 2>/dev/null \
                && ok "Uninstalled momento pip package" \
                || warn "Could not uninstall momento (may not be installed)"
        fi
    fi

    # Remove venv only if .momento_created marker exists
    if [[ -d "$VENV_DIR" ]]; then
        if [[ -f "$VENV_DIR/.momento_created" ]]; then
            if confirm "Remove virtual environment at $VENV_DIR? [Y/n]"; then
                rm -rf "$VENV_DIR"
                ok "Removed $VENV_DIR"
            fi
        else
            info "Skipping $VENV_DIR — not created by Momento (no .momento_created marker)"
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

    # Step 3: Install
    if [[ "$mode" == "global" ]]; then
        install_global
    elif [[ "$mode" == "user" ]]; then
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

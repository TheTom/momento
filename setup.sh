#!/usr/bin/env bash
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

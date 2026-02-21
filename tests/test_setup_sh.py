# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Shell integration tests for setup.sh.

Tests exercise the setup.sh script via subprocess.run with FULLY sandboxed
environments — both HOME and the script's working directory are temp dirs.
This prevents uninstall tests from nuking the real .venv.

Key isolation strategy: copy setup.sh to a temp "project" directory so that
`cd "$(dirname "$0")"` (the last line of setup.sh) operates on the sandbox,
not the real project root.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

# Real paths for reference
PROJECT_ROOT = Path(__file__).parent.parent
SETUP_SH = PROJECT_ROOT / "setup.sh"
SRC_DIR = str(PROJECT_ROOT / "src")


def _make_sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fully sandboxed environment for setup.sh tests.

    Returns (tmp_home, tmp_project) where:
    - tmp_home: sandboxed HOME directory
    - tmp_project: directory containing a copy of setup.sh
    """
    tmp_home = tmp_path / "home"
    tmp_home.mkdir()

    tmp_project = tmp_path / "project"
    tmp_project.mkdir()

    # Copy setup.sh so cd "$(dirname "$0")" stays in the sandbox
    shutil.copy2(SETUP_SH, tmp_project / "setup.sh")

    return tmp_home, tmp_project


def _run_setup(
    args: list[str],
    tmp_home: Path,
    tmp_project: Path,
    *,
    stdin=None,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run sandboxed setup.sh with isolated HOME and project directory."""
    env = {
        **os.environ,
        "HOME": str(tmp_home),
        "PYTHONPATH": SRC_DIR + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }

    return subprocess.run(
        ["bash", str(tmp_project / "setup.sh"), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=stdin,
        env=env,
    )


# ---------------------------------------------------------------------------
# TestSetupShFlags
# ---------------------------------------------------------------------------


class TestSetupShFlags:
    """Tests for setup.sh flag parsing and mode interactions."""

    @pytest.mark.should_pass
    def test_yes_flag_skips_prompts(self, tmp_path):
        """--yes --uninstall completes without hanging for input."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        result = _run_setup(["--yes", "--uninstall"], tmp_home, tmp_project)

        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined
        assert "auto-yes" in combined or "Uninstall complete" in combined

    @pytest.mark.should_pass
    def test_no_tty_auto_defaults_yes(self, tmp_path):
        """Non-TTY stdin auto-defaults to yes mode (no hanging)."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        result = _run_setup(
            ["--uninstall"],
            tmp_home,
            tmp_project,
            stdin=subprocess.DEVNULL,
        )

        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined

    @pytest.mark.should_pass
    def test_unknown_flag_fails(self, tmp_path):
        """--bogus should fail with non-zero exit and 'Unknown option' message."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        result = _run_setup(["--bogus"], tmp_home, tmp_project)

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "Unknown option" in combined

    @pytest.mark.should_pass
    def test_yes_and_uninstall_combined(self, tmp_path):
        """--yes and --uninstall flags work together without conflict."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        result = _run_setup(["--yes", "--uninstall"], tmp_home, tmp_project)

        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined
        assert "Uninstall complete" in combined

    @pytest.mark.should_pass
    def test_uninstall_yes_cleans_integration_files(self, tmp_path):
        """--uninstall --yes removes MCP config, CLAUDE.md adapter, and codex file."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        # Create ~/.claude/settings.json with momento MCP server
        claude_dir = tmp_home / ".claude"
        claude_dir.mkdir()

        settings_data = {
            "mcpServers": {
                "momento": {
                    "command": "python3",
                    "args": ["-m", "momento.mcp_server"],
                    "env": {"PYTHONUNBUFFERED": "1"},
                },
                "other_server": {"command": "node", "args": ["server.js"]},
            }
        }
        settings_file = claude_dir / "settings.json"
        settings_file.write_text(json.dumps(settings_data, indent=2))

        # Create ~/.claude/CLAUDE.md with Momento adapter section
        claude_md = claude_dir / "CLAUDE.md"
        claude_md.write_text(
            "# My Config\n\nSome existing content.\n"
            "\n## Momento Context Recovery\n\n"
            "After any significant file change, decision, or completed subtask:\n"
            '  Call log_knowledge(type="session_state", tags=[<relevant domains>])\n'
            "  with what was done, what was decided, and what's next.\n"
            "  Keep it brief. Context can compact without warning.\n\n"
            "At session start or after /clear:\n"
            "  Call retrieve_context(include_session_state=true).\n"
            "  Use the returned context to orient yourself before taking action.\n\n"
            'When the user says "checkpoint" or "save progress":\n'
            '  Call log_knowledge(type="session_state", tags=[<relevant domains>])\n'
            "  with current task progress, decisions made, and remaining work.\n\n"
            "Before /compact (when user explicitly runs it):\n"
            '  Call log_knowledge(type="session_state", tags=["checkpoint"])\n'
            "  with comprehensive progress summary before executing.\n\n"
            "When encountering an unfamiliar error:\n"
            '  Call retrieve_context(query="<error description>").\n\n'
            "Before implementing a recurring pattern (auth, networking, persistence, caching):\n"
            '  Call retrieve_context(query="<pattern name>").\n\n'
            "After finalizing a significant decision or plan:\n"
            '  Call log_knowledge(type="decision" or "plan", tags=[<domains>])\n'
            "  with the decision, rationale, rejected alternatives, and implications.\n"
            "  Use the Historical Slice structure.\n"
        )

        # Create .codex_instructions.md in the sandboxed project dir
        codex_file = tmp_project / ".codex_instructions.md"
        codex_file.write_text("## Momento Checkpointing and Context Recovery\n")

        result = _run_setup(["--uninstall", "--yes"], tmp_home, tmp_project)

        # Verify settings.json no longer has the momento key
        updated_settings = json.loads(settings_file.read_text())
        assert "momento" not in updated_settings.get("mcpServers", {})
        assert "other_server" in updated_settings.get("mcpServers", {})

        # Verify CLAUDE.md no longer has the Momento adapter
        updated_claude = claude_md.read_text()
        assert "Momento Context Recovery" not in updated_claude
        assert "My Config" in updated_claude

        # Verify .codex_instructions.md was removed
        assert not codex_file.exists()

    @pytest.mark.should_pass
    def test_uninstall_preserves_data_dir_in_yes_mode(self, tmp_path):
        """--uninstall --yes does NOT remove ~/.momento (auto-NO for data dir)."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        momento_dir = tmp_home / ".momento"
        momento_dir.mkdir()
        (momento_dir / "knowledge.db").write_text("fake db")

        _run_setup(["--uninstall", "--yes"], tmp_home, tmp_project)

        assert momento_dir.exists()
        assert (momento_dir / "knowledge.db").exists()

    @pytest.mark.should_pass
    def test_uninstall_skips_venv_without_marker(self, tmp_path):
        """.venv without .momento_created marker is left untouched."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        # Create .venv in sandboxed project dir (no marker)
        venv_dir = tmp_project / ".venv"
        venv_dir.mkdir()

        _run_setup(["--uninstall", "--yes"], tmp_home, tmp_project)

        assert venv_dir.exists()

    @pytest.mark.should_pass
    def test_uninstall_removes_venv_with_marker(self, tmp_path):
        """.venv WITH .momento_created marker is removed by --uninstall --yes."""
        tmp_home, tmp_project = _make_sandbox(tmp_path)

        # Create .venv with the momento marker in sandboxed project dir
        venv_dir = tmp_project / ".venv"
        venv_dir.mkdir()
        (venv_dir / ".momento_created").touch()

        _run_setup(["--uninstall", "--yes"], tmp_home, tmp_project)

        assert not venv_dir.exists()

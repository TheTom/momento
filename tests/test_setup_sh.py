# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Shell integration tests for setup.sh.

Tests exercise the setup.sh script via subprocess.run with sandboxed HOME
directories to avoid touching real user config. Each test uses tmp_path
for isolation.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

# setup.sh lives at the project root, one level above tests/
SETUP_SH = str(Path(__file__).parent.parent / "setup.sh")

# src/ directory for PYTHONPATH so momento.setup_utils is importable
SRC_DIR = str(Path(__file__).parent.parent / "src")


def _run_setup(
    args: list[str],
    tmp_home: Path,
    *,
    cwd: str | None = None,
    stdin=None,
    timeout: int = 30,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run setup.sh with a sandboxed HOME and inherited PATH/PYTHONPATH."""
    env = {
        **os.environ,
        "HOME": str(tmp_home),
        # Ensure momento package is importable for setup_utils calls
        "PYTHONPATH": SRC_DIR + os.pathsep + os.environ.get("PYTHONPATH", ""),
    }
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        ["bash", SETUP_SH, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
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
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        # Use --uninstall (fast) instead of --check (runs full test suite)
        result = _run_setup(["--yes", "--uninstall"], tmp_home, timeout=30)

        # Should complete without blocking on any prompt
        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined
        assert "auto-yes" in combined or "Uninstall complete" in combined

    @pytest.mark.should_pass
    def test_no_tty_auto_defaults_yes(self, tmp_path):
        """Non-TTY stdin auto-defaults to yes mode (no hanging)."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        # Use --uninstall (fast) with piped stdin (non-TTY)
        result = _run_setup(
            ["--uninstall"],
            tmp_home,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )

        # Should not hang — non-TTY triggers YES_MODE=true
        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined

    @pytest.mark.should_pass
    def test_unknown_flag_fails(self, tmp_path):
        """--bogus should fail with non-zero exit and 'Unknown option' message."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        result = _run_setup(["--bogus"], tmp_home, timeout=30)

        assert result.returncode != 0
        combined = result.stdout + result.stderr
        assert "Unknown option" in combined

    @pytest.mark.should_pass
    def test_yes_and_uninstall_combined(self, tmp_path):
        """--yes and --uninstall flags work together without conflict."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        result = _run_setup(["--yes", "--uninstall"], tmp_home, timeout=30)

        # Should not error on flag parsing
        combined = result.stdout + result.stderr
        assert "Unknown option" not in combined
        assert "Uninstall complete" in combined

    @pytest.mark.should_pass
    def test_uninstall_yes_cleans_integration_files(self, tmp_path):
        """--uninstall --yes removes MCP config, CLAUDE.md adapter, and codex file.

        Sets up a sandboxed HOME with:
        - ~/.claude/settings.json containing momento MCP server config
        - ~/.claude/CLAUDE.md with the Momento adapter section
        And a .codex_instructions.md in the project root (where setup.sh cds to).

        After --uninstall --yes, all three should be cleaned up.
        """
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

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

        # setup.sh does `cd "$(dirname "$0")"` so .codex_instructions.md
        # is checked relative to the script's own directory (project root).
        # We create it there in a way the sandboxed uninstall can find it.
        project_root = Path(__file__).parent.parent
        codex_file = project_root / ".codex_instructions.md"
        codex_file.write_text("## Momento Checkpointing and Context Recovery\n")

        try:
            result = _run_setup(["--uninstall", "--yes"], tmp_home, timeout=30)

            # Verify settings.json no longer has the momento key
            updated_settings = json.loads(settings_file.read_text())
            assert "momento" not in updated_settings.get("mcpServers", {})
            # other_server should still be there
            assert "other_server" in updated_settings.get("mcpServers", {})

            # Verify CLAUDE.md no longer has the Momento adapter
            updated_claude = claude_md.read_text()
            assert "Momento Context Recovery" not in updated_claude
            # Existing content should be preserved
            assert "My Config" in updated_claude

            # Verify .codex_instructions.md was removed
            assert not codex_file.exists()
        finally:
            # Clean up the codex file in case the test fails partway through
            if codex_file.exists():
                codex_file.unlink()

    @pytest.mark.should_pass
    def test_uninstall_preserves_data_dir_in_yes_mode(self, tmp_path):
        """--uninstall --yes does NOT remove ~/.momento (auto-NO for data dir)."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        # Create the data directory
        momento_dir = tmp_home / ".momento"
        momento_dir.mkdir()
        (momento_dir / "knowledge.db").write_text("fake db")

        result = _run_setup(["--uninstall", "--yes"], tmp_home, timeout=30)

        # Data dir should still exist — --yes defaults to NO for data removal
        assert momento_dir.exists()
        assert (momento_dir / "knowledge.db").exists()

    @pytest.mark.should_pass
    def test_uninstall_skips_venv_without_marker(self, tmp_path):
        """.venv without .momento_created marker is left untouched."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        # setup.sh does cd to its own dir, so .venv is relative to project root.
        # We can't create a .venv in the real project root safely, so we
        # create a temporary project-like directory and symlink/copy setup.sh.
        # However, setup.sh hardcodes `cd "$(dirname "$0")"`, so the venv
        # check happens in the script's directory.
        #
        # For this test, we create .venv in the project root temporarily.
        project_root = Path(__file__).parent.parent
        venv_dir = project_root / ".venv"
        marker = venv_dir / ".momento_created"

        # Only run if .venv doesn't already exist (don't clobber real venvs)
        if venv_dir.exists():
            # If a real .venv exists, verify the marker status and skip
            # the creation step — just ensure the test logic is valid
            had_marker = marker.exists()
            if had_marker:
                # Temporarily remove the marker to test
                marker.unlink()
            try:
                result = _run_setup(
                    ["--uninstall", "--yes"], tmp_home, timeout=30
                )
                # .venv should still exist since there's no marker
                assert venv_dir.exists()
            finally:
                if had_marker:
                    marker.touch()
        else:
            # Create a fake .venv WITHOUT the marker
            venv_dir.mkdir()
            try:
                result = _run_setup(
                    ["--uninstall", "--yes"], tmp_home, timeout=30
                )
                assert venv_dir.exists()
            finally:
                venv_dir.rmdir()

    @pytest.mark.should_pass
    def test_uninstall_removes_venv_with_marker(self, tmp_path):
        """.venv WITH .momento_created marker is removed by --uninstall --yes."""
        tmp_home = tmp_path / "home"
        tmp_home.mkdir()

        # setup.sh cds to its own dir, so .venv lives at the project root
        project_root = Path(__file__).parent.parent
        venv_dir = project_root / ".venv"

        # Guard: don't clobber a real .venv
        if venv_dir.exists():
            pytest.skip(
                ".venv already exists in project root; "
                "skipping destructive test to avoid clobbering real venv"
            )

        # Create a fake .venv with the momento marker
        venv_dir.mkdir()
        (venv_dir / ".momento_created").touch()

        try:
            result = _run_setup(["--uninstall", "--yes"], tmp_home, timeout=30)

            # .venv should have been removed
            assert not venv_dir.exists()
        finally:
            # Safety net: clean up if the test didn't remove it
            if venv_dir.exists():
                import shutil
                shutil.rmtree(venv_dir)

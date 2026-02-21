# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for setup_utils — MCP registration, Claude/Codex adapter management.

All file operations use tmp_path — never touches the real filesystem.
"""

import json
import sys
from unittest.mock import patch

import pytest

from momento.setup_utils import (
    register_mcp_server,
    unregister_mcp_server,
    add_claude_adapter,
    remove_claude_adapter,
    generate_codex_adapter,
    remove_codex_adapter,
    main,
    _MCP_SERVER_CONFIG,
    CLAUDE_ADAPTER_HEADER,
    CLAUDE_ADAPTER_BLOCK,
    CODEX_ADAPTER_CONTENT,
)


# ---------------------------------------------------------------------------
# TestRegisterMcpServer
# ---------------------------------------------------------------------------

class TestRegisterMcpServer:
    """Tests for register_mcp_server()."""

    @pytest.mark.should_pass
    def test_creates_new_settings_file(self, tmp_path):
        """Creates settings.json from scratch when file doesn't exist."""
        settings = tmp_path / "subdir" / "settings.json"
        result = register_mcp_server(str(settings))

        assert result is True
        assert settings.exists()

        data = json.loads(settings.read_text())
        assert data["mcpServers"]["momento"] == _MCP_SERVER_CONFIG

    @pytest.mark.should_pass
    def test_preserves_existing_keys(self, tmp_path):
        """Adds mcpServers without clobbering other top-level keys."""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["read"]}}))

        result = register_mcp_server(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        assert data["permissions"] == {"allow": ["read"]}
        assert data["mcpServers"]["momento"] == _MCP_SERVER_CONFIG

    @pytest.mark.should_pass
    def test_preserves_other_mcp_servers(self, tmp_path):
        """Existing MCP servers in mcpServers are not removed."""
        settings = tmp_path / "settings.json"
        existing = {
            "mcpServers": {
                "other_tool": {"command": "other", "args": ["--flag"]},
            }
        }
        settings.write_text(json.dumps(existing))

        result = register_mcp_server(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        assert data["mcpServers"]["other_tool"] == {"command": "other", "args": ["--flag"]}
        assert data["mcpServers"]["momento"] == _MCP_SERVER_CONFIG

    @pytest.mark.should_pass
    def test_idempotent_overwrite(self, tmp_path):
        """Re-registering overwrites with latest config, no duplicates."""
        settings = tmp_path / "settings.json"

        register_mcp_server(str(settings))
        # Register again — should overwrite cleanly
        result = register_mcp_server(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        # Only one momento key
        assert list(data["mcpServers"].keys()).count("momento") == 1
        assert data["mcpServers"]["momento"] == _MCP_SERVER_CONFIG


# ---------------------------------------------------------------------------
# TestUnregisterMcpServer
# ---------------------------------------------------------------------------

class TestUnregisterMcpServer:
    """Tests for unregister_mcp_server()."""

    @pytest.mark.should_pass
    def test_removes_momento_preserves_others(self, tmp_path):
        """Removes momento key but keeps other servers intact."""
        settings = tmp_path / "settings.json"
        data = {
            "mcpServers": {
                "momento": _MCP_SERVER_CONFIG,
                "other_server": {"command": "other"},
            }
        }
        settings.write_text(json.dumps(data))

        result = unregister_mcp_server(str(settings))

        assert result is True
        out = json.loads(settings.read_text())
        assert "momento" not in out["mcpServers"]
        assert out["mcpServers"]["other_server"] == {"command": "other"}

    @pytest.mark.should_pass
    def test_removes_empty_mcp_servers_key(self, tmp_path):
        """Cleans up mcpServers key entirely when no servers remain."""
        settings = tmp_path / "settings.json"
        data = {"mcpServers": {"momento": _MCP_SERVER_CONFIG}, "other": 42}
        settings.write_text(json.dumps(data))

        result = unregister_mcp_server(str(settings))

        assert result is True
        out = json.loads(settings.read_text())
        assert "mcpServers" not in out
        assert out["other"] == 42

    @pytest.mark.should_pass
    def test_noop_when_not_registered(self, tmp_path):
        """Returns True (noop) when momento isn't in mcpServers."""
        settings = tmp_path / "settings.json"
        data = {"mcpServers": {"something_else": {"command": "x"}}}
        settings.write_text(json.dumps(data))

        result = unregister_mcp_server(str(settings))

        assert result is True
        # File unchanged — something_else still there
        out = json.loads(settings.read_text())
        assert "something_else" in out["mcpServers"]

    @pytest.mark.should_pass
    def test_noop_when_file_missing(self, tmp_path):
        """Returns True when settings file doesn't exist at all."""
        settings = tmp_path / "nonexistent" / "settings.json"

        result = unregister_mcp_server(str(settings))

        assert result is True


# ---------------------------------------------------------------------------
# TestAddClaudeAdapter
# ---------------------------------------------------------------------------

class TestAddClaudeAdapter:
    """Tests for add_claude_adapter()."""

    @pytest.mark.should_pass
    def test_creates_new_file(self, tmp_path):
        """Creates CLAUDE.md from scratch with adapter block."""
        claude_md = tmp_path / "subdir" / "CLAUDE.md"

        result = add_claude_adapter(str(claude_md))

        assert result is True
        assert claude_md.exists()
        content = claude_md.read_text()
        assert CLAUDE_ADAPTER_HEADER in content

    @pytest.mark.should_pass
    def test_appends_to_existing_content(self, tmp_path):
        """Appends adapter block without overwriting existing content."""
        claude_md = tmp_path / "CLAUDE.md"
        original = "# My Project\n\nExisting instructions here.\n"
        claude_md.write_text(original)

        result = add_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert content.startswith(original)
        assert CLAUDE_ADAPTER_HEADER in content

    @pytest.mark.should_pass
    def test_idempotent_no_duplicate(self, tmp_path):
        """Calling twice doesn't duplicate the adapter block."""
        claude_md = tmp_path / "CLAUDE.md"

        add_claude_adapter(str(claude_md))
        result = add_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert content.count(CLAUDE_ADAPTER_HEADER) == 1


# ---------------------------------------------------------------------------
# TestRemoveClaudeAdapter
# ---------------------------------------------------------------------------

class TestRemoveClaudeAdapter:
    """Tests for remove_claude_adapter()."""

    @pytest.mark.should_pass
    def test_strips_adapter_preserves_surrounding(self, tmp_path):
        """Removes adapter section, keeps content before and after."""
        claude_md = tmp_path / "CLAUDE.md"
        before = "# Project\n\nSome instructions.\n"
        after = "\n## Other Section\n\nMore stuff.\n"
        full = before + CLAUDE_ADAPTER_BLOCK + after
        claude_md.write_text(full)

        result = remove_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert CLAUDE_ADAPTER_HEADER not in content
        assert "Some instructions." in content
        assert "Other Section" in content

    @pytest.mark.should_pass
    def test_adapter_at_end_of_file(self, tmp_path):
        """Works when adapter is the last section in the file."""
        claude_md = tmp_path / "CLAUDE.md"
        before = "# Project\n\nSome notes.\n"
        full = before + CLAUDE_ADAPTER_BLOCK
        claude_md.write_text(full)

        result = remove_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert CLAUDE_ADAPTER_HEADER not in content
        assert "Some notes." in content

    @pytest.mark.should_pass
    def test_adapter_between_sections(self, tmp_path):
        """Works when adapter sits between two other markdown sections."""
        claude_md = tmp_path / "CLAUDE.md"
        section_a = "## Section A\n\nContent A.\n"
        section_b = "\n## Section B\n\nContent B.\n"
        full = section_a + CLAUDE_ADAPTER_BLOCK + section_b
        claude_md.write_text(full)

        result = remove_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert CLAUDE_ADAPTER_HEADER not in content
        assert "Content A." in content
        assert "Content B." in content

    @pytest.mark.should_pass
    def test_noop_when_not_present(self, tmp_path):
        """Returns True when adapter isn't in the file."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Just a normal file\n")

        result = remove_claude_adapter(str(claude_md))

        assert result is True

    @pytest.mark.should_pass
    def test_noop_when_file_missing(self, tmp_path):
        """Returns True when CLAUDE.md doesn't exist."""
        claude_md = tmp_path / "nonexistent" / "CLAUDE.md"

        result = remove_claude_adapter(str(claude_md))

        assert result is True


# ---------------------------------------------------------------------------
# TestGenerateCodexAdapter
# ---------------------------------------------------------------------------

class TestGenerateCodexAdapter:
    """Tests for generate_codex_adapter()."""

    @pytest.mark.should_pass
    def test_creates_file_with_correct_content(self, tmp_path):
        """Creates .codex_instructions.md with the full adapter content."""
        codex_path = tmp_path / ".codex_instructions.md"

        result = generate_codex_adapter(str(codex_path))

        assert result is True
        assert codex_path.exists()
        content = codex_path.read_text()
        assert content == CODEX_ADAPTER_CONTENT

    @pytest.mark.should_pass
    def test_overwrites_existing_file(self, tmp_path):
        """Overwrites an existing file with fresh content."""
        codex_path = tmp_path / ".codex_instructions.md"
        codex_path.write_text("old junk content\n")

        result = generate_codex_adapter(str(codex_path))

        assert result is True
        content = codex_path.read_text()
        assert content == CODEX_ADAPTER_CONTENT
        assert "old junk" not in content


# ---------------------------------------------------------------------------
# TestRemoveCodexAdapter
# ---------------------------------------------------------------------------

class TestRemoveCodexAdapter:
    """Tests for remove_codex_adapter()."""

    @pytest.mark.should_pass
    def test_deletes_existing_file(self, tmp_path):
        """Deletes the file when it exists."""
        codex_path = tmp_path / ".codex_instructions.md"
        codex_path.write_text(CODEX_ADAPTER_CONTENT)

        result = remove_codex_adapter(str(codex_path))

        assert result is True
        assert not codex_path.exists()

    @pytest.mark.should_pass
    def test_noop_when_file_missing(self, tmp_path):
        """Returns True when the file doesn't exist."""
        codex_path = tmp_path / ".codex_instructions.md"

        result = remove_codex_adapter(str(codex_path))

        assert result is True


# ---------------------------------------------------------------------------
# TestSetupUtilsMain
# ---------------------------------------------------------------------------

class TestSetupUtilsMain:
    """Tests for the main() CLI dispatch entrypoint."""

    @pytest.mark.should_pass
    def test_register_mcp_dispatch(self, tmp_path):
        """main() dispatches register_mcp and creates settings file."""
        settings = tmp_path / "settings.json"

        with patch.object(sys, "argv", ["setup_utils", "register_mcp", str(settings)]):
            main()

        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "momento" in data["mcpServers"]

    @pytest.mark.should_pass
    def test_unregister_mcp_dispatch(self, tmp_path):
        """main() dispatches unregister_mcp correctly."""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"mcpServers": {"momento": _MCP_SERVER_CONFIG}}))

        with patch.object(sys, "argv", ["setup_utils", "unregister_mcp", str(settings)]):
            main()

        data = json.loads(settings.read_text())
        assert "mcpServers" not in data

    @pytest.mark.should_pass
    def test_add_claude_adapter_dispatch(self, tmp_path):
        """main() dispatches add_claude_adapter correctly."""
        claude_md = tmp_path / "CLAUDE.md"

        with patch.object(sys, "argv", ["setup_utils", "add_claude_adapter", str(claude_md)]):
            main()

        assert claude_md.exists()
        assert CLAUDE_ADAPTER_HEADER in claude_md.read_text()

    @pytest.mark.should_pass
    def test_remove_claude_adapter_dispatch(self, tmp_path):
        """main() dispatches remove_claude_adapter correctly."""
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# Stuff\n" + CLAUDE_ADAPTER_BLOCK)

        with patch.object(sys, "argv", ["setup_utils", "remove_claude_adapter", str(claude_md)]):
            main()

        assert CLAUDE_ADAPTER_HEADER not in claude_md.read_text()

    @pytest.mark.should_pass
    def test_generate_codex_adapter_dispatch(self, tmp_path):
        """main() dispatches generate_codex_adapter correctly."""
        codex_path = tmp_path / ".codex_instructions.md"

        with patch.object(sys, "argv", ["setup_utils", "generate_codex_adapter", str(codex_path)]):
            main()

        assert codex_path.read_text() == CODEX_ADAPTER_CONTENT

    @pytest.mark.should_pass
    def test_remove_codex_adapter_dispatch(self, tmp_path):
        """main() dispatches remove_codex_adapter correctly."""
        codex_path = tmp_path / ".codex_instructions.md"
        codex_path.write_text(CODEX_ADAPTER_CONTENT)

        with patch.object(sys, "argv", ["setup_utils", "remove_codex_adapter", str(codex_path)]):
            main()

        assert not codex_path.exists()

    @pytest.mark.should_pass
    def test_unknown_command_exits_with_error(self, tmp_path):
        """Unknown command causes sys.exit(1)."""
        with patch.object(sys, "argv", ["setup_utils", "bogus_command", "/tmp/x"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @pytest.mark.should_pass
    def test_missing_args_exits_with_error(self):
        """Too few args causes sys.exit(1)."""
        with patch.object(sys, "argv", ["setup_utils"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    @pytest.mark.should_pass
    def test_missing_path_arg_exits_with_error(self):
        """Command without path arg causes sys.exit(1)."""
        with patch.object(sys, "argv", ["setup_utils", "register_mcp"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

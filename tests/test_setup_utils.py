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
    register_hooks,
    unregister_hooks,
    generate_codex_adapter,
    remove_codex_adapter,
    main,
    _mcp_server_config,
    _is_momento_hook,
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
        assert data["mcpServers"]["momento"] == _mcp_server_config()

    @pytest.mark.should_pass
    def test_preserves_existing_keys(self, tmp_path):
        """Adds mcpServers without clobbering other top-level keys."""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"permissions": {"allow": ["read"]}}))

        result = register_mcp_server(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        assert data["permissions"] == {"allow": ["read"]}
        assert data["mcpServers"]["momento"] == _mcp_server_config()

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
        assert data["mcpServers"]["momento"] == _mcp_server_config()

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
        assert data["mcpServers"]["momento"] == _mcp_server_config()

    @pytest.mark.should_pass
    def test_returns_false_when_existing_json_is_invalid(self, tmp_path):
        """Invalid existing JSON returns False and is left untouched."""
        settings = tmp_path / "settings.json"
        bad_json = '{"mcpServers": {"broken": true},}'
        settings.write_text(bad_json)

        result = register_mcp_server(str(settings))

        assert result is False
        assert settings.read_text() == bad_json


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
                "momento": _mcp_server_config(),
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
        data = {"mcpServers": {"momento": _mcp_server_config()}, "other": 42}
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

    @pytest.mark.should_pass
    def test_returns_false_when_existing_json_is_invalid(self, tmp_path):
        """Invalid existing JSON returns False and is left untouched."""
        settings = tmp_path / "settings.json"
        bad_json = '{"mcpServers": {"broken": true},}'
        settings.write_text(bad_json)

        result = unregister_mcp_server(str(settings))

        assert result is False
        assert settings.read_text() == bad_json


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

    @pytest.mark.should_pass
    def test_removes_legacy_output_rules_header(self, tmp_path):
        """Removes adapter even when it starts with legacy '## Momento Output Rules'."""
        claude_md = tmp_path / "CLAUDE.md"
        legacy_block = (
            "# My Project\n\n"
            "## Momento Output Rules\n\n"
            "Some old output rules.\n\n"
            "## Momento Context Recovery\n\n"
            "Old recovery instructions.\n\n"
            "Use the Historical Slice structure.\n"
        )
        claude_md.write_text(legacy_block)

        result = remove_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        assert "Momento Output Rules" not in content
        assert "My Project" in content


# ---------------------------------------------------------------------------
# TestUpgradeClaudeAdapter
# ---------------------------------------------------------------------------

class TestUpgradeClaudeAdapter:
    """Tests for upgrading legacy adapter → current version."""

    @pytest.mark.must_pass
    def test_upgrade_replaces_legacy_with_current(self, tmp_path):
        """add_claude_adapter upgrades old '## Momento Output Rules' to new format."""
        claude_md = tmp_path / "CLAUDE.md"
        legacy_block = (
            "# My Project\n\n"
            "Existing instructions.\n"
            "\n## Momento Output Rules\n\n"
            "Old output rules.\n\n"
            "## Momento Context Recovery\n\n"
            "Old recovery stuff.\n\n"
            "Use the Historical Slice structure.\n"
        )
        claude_md.write_text(legacy_block)

        result = add_claude_adapter(str(claude_md))

        assert result is True
        content = claude_md.read_text()
        # New header present
        assert "## Momento — MANDATORY Session Start" in content
        # Old-style-only header gone (Output Rules still exists but under new block)
        assert "BEFORE doing ANY work" in content
        # Existing content preserved
        assert "Existing instructions." in content
        # Only one adapter block
        assert content.count("Use the Historical Slice structure.") == 1

    @pytest.mark.must_pass
    def test_upgrade_is_idempotent(self, tmp_path):
        """Running add_claude_adapter twice after upgrade doesn't duplicate."""
        claude_md = tmp_path / "CLAUDE.md"
        legacy_block = (
            "# Project\n"
            "\n## Momento Output Rules\n\n"
            "Old stuff.\n\n"
            "Use the Historical Slice structure.\n"
        )
        claude_md.write_text(legacy_block)

        add_claude_adapter(str(claude_md))
        add_claude_adapter(str(claude_md))

        content = claude_md.read_text()
        assert content.count("## Momento — MANDATORY Session Start") == 1

    @pytest.mark.must_pass
    def test_fresh_install_has_mandatory_header(self, tmp_path):
        """New installs get the MANDATORY Session Start section."""
        claude_md = tmp_path / "CLAUDE.md"

        add_claude_adapter(str(claude_md))

        content = claude_md.read_text()
        assert "## Momento — MANDATORY Session Start" in content
        assert "BEFORE doing ANY work" in content
        assert "retrieve_context" in content


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
        settings.write_text(json.dumps({"mcpServers": {"momento": _mcp_server_config()}}))

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

    @pytest.mark.should_pass
    def test_register_hooks_dispatch(self, tmp_path):
        """main() dispatches register_hooks correctly."""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {}}))

        with patch.object(sys, "argv", ["setup_utils", "register_hooks", str(settings)]):
            main()

        data = json.loads(settings.read_text())
        assert "Stop" not in data["hooks"]
        assert "SessionStart" in data["hooks"]

    @pytest.mark.should_pass
    def test_unregister_hooks_dispatch(self, tmp_path):
        """main() dispatches unregister_hooks correctly."""
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {}}))

        # Register then unregister
        register_hooks(str(settings))
        with patch.object(sys, "argv", ["setup_utils", "unregister_hooks", str(settings)]):
            main()

        data = json.loads(settings.read_text())
        assert "Stop" not in data.get("hooks", {})
        assert "SessionStart" not in data.get("hooks", {})


# ---------------------------------------------------------------------------
# TestRegisterHooks
# ---------------------------------------------------------------------------

class TestRegisterHooks:
    """Tests for register_hooks()."""

    @pytest.mark.should_pass
    def test_creates_hooks_in_new_file(self, tmp_path):
        """Creates settings.json with hooks and permissions from scratch."""
        settings = tmp_path / "settings.json"

        result = register_hooks(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        assert "Stop" not in data["hooks"]  # No stop hook (removed — caused junk entries)
        assert len(data["hooks"]["SessionStart"]) == 2  # compact + resume
        assert "mcp__momento" in data["permissions"]["allow"]

    @pytest.mark.should_pass
    def test_preserves_existing_hooks(self, tmp_path):
        """Adds Momento hooks without clobbering existing ones."""
        settings = tmp_path / "settings.json"
        existing = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}],
                "PreToolUse": [{"hooks": [{"type": "command", "command": "echo pre"}]}],
            }
        }
        settings.write_text(json.dumps(existing))

        result = register_hooks(str(settings))

        assert result is True
        data = json.loads(settings.read_text())
        # Existing Stop hook preserved, no Momento stop hook added
        assert len(data["hooks"]["Stop"]) == 1
        assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo other"
        # PreToolUse untouched
        assert len(data["hooks"]["PreToolUse"]) == 1
        # SessionStart added fresh
        assert len(data["hooks"]["SessionStart"]) == 2

    @pytest.mark.should_pass
    def test_idempotent(self, tmp_path):
        """Calling twice doesn't duplicate Momento hooks or permissions."""
        settings = tmp_path / "settings.json"

        register_hooks(str(settings))
        register_hooks(str(settings))

        data = json.loads(settings.read_text())
        # Should still be exactly 2 SessionStart hooks, no Stop hook
        assert "Stop" not in data["hooks"]
        assert len(data["hooks"]["SessionStart"]) == 2
        # Permission should appear exactly once
        assert data["permissions"]["allow"].count("mcp__momento") == 1

    @pytest.mark.should_pass
    def test_no_stop_hook_registered(self, tmp_path):
        """No stop hook — removed to prevent junk checkpoint entries."""
        settings = tmp_path / "settings.json"
        register_hooks(str(settings))

        data = json.loads(settings.read_text())
        assert "Stop" not in data["hooks"]

    @pytest.mark.should_pass
    def test_session_start_hooks_have_matchers(self, tmp_path):
        """SessionStart hooks have compact and resume matchers."""
        settings = tmp_path / "settings.json"
        register_hooks(str(settings))

        data = json.loads(settings.read_text())
        matchers = {h["matcher"] for h in data["hooks"]["SessionStart"]}
        assert matchers == {"compact", "resume"}

    @pytest.mark.should_pass
    def test_returns_false_on_invalid_json(self, tmp_path):
        """Returns False when existing file has invalid JSON."""
        settings = tmp_path / "settings.json"
        settings.write_text("{bad json}")

        result = register_hooks(str(settings))

        assert result is False


# ---------------------------------------------------------------------------
# TestUnregisterHooks
# ---------------------------------------------------------------------------

class TestUnregisterHooks:
    """Tests for unregister_hooks()."""

    @pytest.mark.should_pass
    def test_removes_momento_hooks_and_permission_only(self, tmp_path):
        """Removes Momento hooks and permission, keeps everything else intact."""
        settings = tmp_path / "settings.json"
        data = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "echo other"}]},
                    {"hooks": [{"type": "command", "command": "momento check-stale || exit 2"}]},
                ],
                "SessionStart": [
                    {"matcher": "", "hooks": [{"type": "command", "command": "echo start"}]},
                    {"matcher": "compact", "hooks": [{"type": "command", "command": "echo 'momento recovery'"}]},
                ],
            },
            "permissions": {"allow": ["mcp__pencil", "mcp__momento"]},
        }
        settings.write_text(json.dumps(data))

        result = unregister_hooks(str(settings))

        assert result is True
        out = json.loads(settings.read_text())
        assert len(out["hooks"]["Stop"]) == 1
        assert "other" in out["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert len(out["hooks"]["SessionStart"]) == 1
        assert out["hooks"]["SessionStart"][0]["hooks"][0]["command"] == "echo start"
        # mcp__momento removed, mcp__pencil preserved
        assert "mcp__momento" not in out["permissions"]["allow"]
        assert "mcp__pencil" in out["permissions"]["allow"]

    @pytest.mark.should_pass
    def test_cleans_up_empty_arrays_and_permissions(self, tmp_path):
        """Removes empty hook arrays and mcp__momento permission after unregistering."""
        settings = tmp_path / "settings.json"
        register_hooks(str(settings))

        result = unregister_hooks(str(settings))

        assert result is True
        out = json.loads(settings.read_text())
        assert "Stop" not in out.get("hooks", {})
        assert "SessionStart" not in out.get("hooks", {})
        # Permission should be removed, empty permissions cleaned up
        assert "permissions" not in out

    @pytest.mark.should_pass
    def test_noop_when_file_missing(self, tmp_path):
        """Returns True when settings file doesn't exist."""
        settings = tmp_path / "nonexistent.json"

        result = unregister_hooks(str(settings))

        assert result is True

    @pytest.mark.should_pass
    def test_noop_when_no_momento_hooks(self, tmp_path):
        """Returns True when no Momento hooks are present."""
        settings = tmp_path / "settings.json"
        data = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo other"}]}]}}
        settings.write_text(json.dumps(data))

        result = unregister_hooks(str(settings))

        assert result is True
        out = json.loads(settings.read_text())
        assert len(out["hooks"]["Stop"]) == 1

    @pytest.mark.should_pass
    def test_does_not_touch_claude_terminal_hooks(self, tmp_path):
        """Hooks with 'claude_terminal' in command are never removed."""
        settings = tmp_path / "settings.json"
        data = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "command": "node claude_terminal/hook.js Stop"}]},
                    {"hooks": [{"type": "command", "command": "momento check-stale"}]},
                ],
            }
        }
        settings.write_text(json.dumps(data))

        unregister_hooks(str(settings))

        out = json.loads(settings.read_text())
        assert len(out["hooks"]["Stop"]) == 1
        assert "claude_terminal" in out["hooks"]["Stop"][0]["hooks"][0]["command"]


# ---------------------------------------------------------------------------
# TestIsMomentoHook
# ---------------------------------------------------------------------------

class TestIsMomentoHook:
    """Tests for _is_momento_hook() helper."""

    @pytest.mark.should_pass
    def test_detects_momento_hook(self):
        hook = {"hooks": [{"type": "command", "command": "momento check-stale --threshold 30"}]}
        assert _is_momento_hook(hook) is True

    @pytest.mark.should_pass
    def test_ignores_claude_terminal_hook(self):
        hook = {"hooks": [{"type": "command", "command": "node claude_terminal/hook.js"}]}
        assert _is_momento_hook(hook) is False

    @pytest.mark.should_pass
    def test_ignores_unrelated_hook(self):
        hook = {"hooks": [{"type": "command", "command": "echo hello"}]}
        assert _is_momento_hook(hook) is False

    @pytest.mark.should_pass
    def test_empty_hooks_list(self):
        hook = {"hooks": []}
        assert _is_momento_hook(hook) is False

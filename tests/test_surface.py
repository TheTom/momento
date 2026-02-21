# Copyright (c) 2026 Tom Turney
# SPDX-License-Identifier: Apache-2.0

"""Tests for momento.surface — PRD-mapped surface detection.

Surface mapping is fixed:
- server/backend -> server
- web/frontend -> web
- ios -> ios
- android -> android
"""

from unittest.mock import patch

from momento.surface import derive_surface, detect_surface, _resolve_git_root


class TestDeriveSurface:
    def test_server_mapping(self):
        assert derive_surface("/project/server/handlers", "/project") == "server"
        assert derive_surface("/project/backend/jobs", "/project") == "server"

    def test_web_mapping(self):
        assert derive_surface("/project/web/src", "/project") == "web"
        assert derive_surface("/project/frontend/ui", "/project") == "web"

    def test_mobile_mapping(self):
        assert derive_surface("/project/ios/auth", "/project") == "ios"
        assert derive_surface("/project/android/app", "/project") == "android"

    def test_case_insensitive(self):
        assert derive_surface("/project/Server/api", "/project") == "server"
        assert derive_surface("/project/FrontEnd/ui", "/project") == "web"

    def test_unmapped_segments_return_none(self):
        assert derive_surface("/project/services/payments", "/project") is None
        assert derive_surface("/project/api/auth", "/project") is None

    def test_root_and_hidden(self):
        assert derive_surface("/project", "/project") is None
        assert derive_surface("/project/.github/workflows", "/project") is None

    def test_not_inside_project(self):
        assert derive_surface("/other/path", "/project") is None


class TestDetectSurface:
    @patch("momento.surface._resolve_git_root", return_value="/project")
    def test_detects_mapped_surface(self, _mock_root):
        assert detect_surface("/project/backend/worker") == "server"
        assert detect_surface("/project/frontend/app") == "web"

    @patch("momento.surface._resolve_git_root", return_value="/project")
    def test_unmapped_returns_none(self, _mock_root):
        assert detect_surface("/project/packages/ui") is None

    @patch("momento.surface._resolve_git_root", return_value=None)
    def test_non_git_returns_none(self, _mock_root):
        assert detect_surface("/tmp/no-git") is None

    def test_empty_cwd_returns_none(self):
        """Empty string or root path returns None early (covers surface.py:74)."""
        assert detect_surface("") is None
        assert detect_surface("/") is None


class TestResolveGitRoot:
    def test_real_git_repo(self, mock_git_repo):
        assert _resolve_git_root(str(mock_git_repo)) == str(mock_git_repo)

    def test_non_git_dir(self, mock_non_git_dir):
        assert _resolve_git_root(str(mock_non_git_dir)) is None
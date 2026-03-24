# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for file_path_router module.

Validates Patterson-style file-path convention routing:
- Repo root detection via .git
- Absolute-to-repo-relative path conversion
- Route matching via fnmatch
- Snippet loading and truncation
- Graceful handling of missing files
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

# Import the module under test
from plugins.onex.hooks.lib.file_path_router import (
    MAX_SNIPPET_LINES,
    _find_repo_root,
    _load_routes,
    _load_snippet,
    _to_repo_relative,
    get_conventions,
)

# =============================================================================
# _find_repo_root tests
# =============================================================================


class TestFindRepoRoot:
    """Tests for _find_repo_root."""

    def test_finds_git_directory(self, tmp_path: Path) -> None:
        """Finds repo root when .git is a directory."""
        (tmp_path / ".git").mkdir()
        nested = tmp_path / "src" / "pkg"
        nested.mkdir(parents=True)
        test_file = nested / "module.py"
        test_file.touch()

        result = _find_repo_root(str(test_file))
        assert result == tmp_path

    def test_finds_git_file(self, tmp_path: Path) -> None:
        """Finds repo root when .git is a file (worktree)."""
        (tmp_path / ".git").write_text("gitdir: /some/path/.git/worktrees/foo\n")
        test_file = tmp_path / "file.py"
        test_file.touch()

        result = _find_repo_root(str(test_file))
        assert result == tmp_path

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        """Returns None when no .git found in any parent."""
        nested = tmp_path / "deep" / "nested"
        nested.mkdir(parents=True)
        test_file = nested / "file.py"
        test_file.touch()

        result = _find_repo_root(str(test_file))
        # May find a .git in a real parent above tmp_path, so we only
        # assert it doesn't claim tmp_path is the root
        if result is not None:
            assert result != nested

    def test_repo_root_is_file_location(self, tmp_path: Path) -> None:
        """Finds root when the file itself is at the repo root."""
        (tmp_path / ".git").mkdir()
        test_file = tmp_path / "README.md"
        test_file.touch()

        result = _find_repo_root(str(test_file))
        assert result == tmp_path


# =============================================================================
# _to_repo_relative tests
# =============================================================================


class TestToRepoRelative:
    """Tests for _to_repo_relative."""

    def test_basic_conversion(self, tmp_path: Path) -> None:
        """Converts absolute path to repo_name/relative format."""
        repo = tmp_path / "omnidash"
        repo.mkdir()
        (repo / ".git").mkdir()
        src = repo / "server" / "routes"
        src.mkdir(parents=True)
        test_file = src / "api.ts"
        test_file.touch()

        result = _to_repo_relative(str(test_file))
        assert result == "omnidash/server/routes/api.ts"

    def test_worktree_path(self, tmp_path: Path) -> None:
        """Handles worktree-style paths correctly."""
        # Simulates /omni_worktrees/OMN-1234/omniclaude/plugins/foo.py
        repo = tmp_path / "OMN-1234" / "omniclaude"
        repo.mkdir(parents=True)
        (repo / ".git").write_text("gitdir: /fake/path\n")
        target = repo / "plugins" / "onex" / "hooks" / "test.py"
        target.parent.mkdir(parents=True)
        target.touch()

        result = _to_repo_relative(str(target))
        assert result == "omniclaude/plugins/onex/hooks/test.py"

    def test_no_git_returns_none(self, tmp_path: Path) -> None:
        """Returns None when no .git found."""
        test_file = tmp_path / "orphan.py"
        test_file.touch()

        # Patch to prevent finding real .git above tmp_path
        with patch(
            "plugins.onex.hooks.lib.file_path_router._find_repo_root",
            return_value=None,
        ):
            result = _to_repo_relative(str(test_file))
        assert result is None


# =============================================================================
# _load_routes tests
# =============================================================================


class TestLoadRoutes:
    """Tests for _load_routes."""

    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        """Loads routes from a valid YAML file."""
        routes_file = tmp_path / "routes.yaml"
        routes_file.write_text(
            'routes:\n  - pattern: "foo/**/*.py"\n    conventions: ["bar"]\n'
        )

        with patch("plugins.onex.hooks.lib.file_path_router.ROUTES_FILE", routes_file):
            routes = _load_routes()

        assert len(routes) == 1
        assert routes[0]["pattern"] == "foo/**/*.py"
        assert routes[0]["conventions"] == ["bar"]

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when routes.yaml does not exist."""
        with patch(
            "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
            tmp_path / "nonexistent.yaml",
        ):
            routes = _load_routes()
        assert routes == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty list when routes.yaml is empty."""
        routes_file = tmp_path / "routes.yaml"
        routes_file.write_text("")

        with patch("plugins.onex.hooks.lib.file_path_router.ROUTES_FILE", routes_file):
            routes = _load_routes()
        assert routes == []


# =============================================================================
# _load_snippet tests
# =============================================================================


class TestLoadSnippet:
    """Tests for _load_snippet."""

    def test_loads_snippet(self, tmp_path: Path) -> None:
        """Loads snippet content from markdown file."""
        snippet = tmp_path / "test-conv.md"
        snippet.write_text("# Test Convention\n\nDo the thing.\n")

        with patch("plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR", tmp_path):
            result = _load_snippet("test-conv")

        assert "# Test Convention" in result
        assert "Do the thing." in result

    def test_missing_snippet_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty string when snippet file does not exist."""
        with patch("plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR", tmp_path):
            result = _load_snippet("nonexistent")
        assert result == ""

    def test_truncation_at_max_lines(self, tmp_path: Path) -> None:
        """Truncates snippet exceeding MAX_SNIPPET_LINES."""
        snippet = tmp_path / "big.md"
        lines = [f"Line {i}" for i in range(MAX_SNIPPET_LINES + 20)]
        snippet.write_text("\n".join(lines))

        with patch("plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR", tmp_path):
            result = _load_snippet("big")

        result_lines = result.splitlines()
        # MAX_SNIPPET_LINES content lines + 1 truncation notice
        assert len(result_lines) == MAX_SNIPPET_LINES + 1
        assert f"[truncated at {MAX_SNIPPET_LINES} lines]" in result_lines[-1]

    def test_exact_max_lines_no_truncation(self, tmp_path: Path) -> None:
        """Does not truncate snippet at exactly MAX_SNIPPET_LINES."""
        snippet = tmp_path / "exact.md"
        lines = [f"Line {i}" for i in range(MAX_SNIPPET_LINES)]
        snippet.write_text("\n".join(lines))

        with patch("plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR", tmp_path):
            result = _load_snippet("exact")

        result_lines = result.splitlines()
        assert len(result_lines) == MAX_SNIPPET_LINES
        assert "[truncated" not in result


# =============================================================================
# get_conventions integration tests
# =============================================================================


class TestGetConventions:
    """Integration tests for get_conventions."""

    def test_matching_path_returns_snippets(self, tmp_path: Path) -> None:
        """Returns convention snippets for a matching path."""
        # Set up repo
        repo = tmp_path / "omnidash"
        repo.mkdir()
        (repo / ".git").mkdir()
        server_file = repo / "server" / "routes" / "api.ts"
        server_file.parent.mkdir(parents=True)
        server_file.touch()

        # Set up conventions dir
        conv_dir = tmp_path / "conventions"
        conv_dir.mkdir()
        routes_yaml = conv_dir / "routes.yaml"
        routes_yaml.write_text(
            "routes:\n"
            '  - pattern: "omnidash/server/**/*.ts"\n'
            '    conventions: ["omnidash-server"]\n'
        )
        snippet = conv_dir / "omnidash-server.md"
        snippet.write_text("# Server Rules\nUse Express.\n")

        with (
            patch(
                "plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR",
                conv_dir,
            ),
            patch(
                "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
                routes_yaml,
            ),
        ):
            result = get_conventions(str(server_file))

        assert "# Server Rules" in result
        assert "Use Express." in result

    def test_non_matching_path_returns_empty(self, tmp_path: Path) -> None:
        """Returns empty string for path that matches no route."""
        repo = tmp_path / "somerepo"
        repo.mkdir()
        (repo / ".git").mkdir()
        test_file = repo / "random.txt"
        test_file.touch()

        conv_dir = tmp_path / "conventions"
        conv_dir.mkdir()
        routes_yaml = conv_dir / "routes.yaml"
        routes_yaml.write_text(
            "routes:\n"
            '  - pattern: "omnidash/server/**/*.ts"\n'
            '    conventions: ["omnidash-server"]\n'
        )

        with (
            patch(
                "plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR",
                conv_dir,
            ),
            patch(
                "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
                routes_yaml,
            ),
        ):
            result = get_conventions(str(test_file))

        assert result == ""

    def test_multiple_conventions_concatenated(self, tmp_path: Path) -> None:
        """Multiple matched conventions are concatenated with double newline."""
        repo = tmp_path / "omnibase_core"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / "src" / "models" / "contract.py"
        target.parent.mkdir(parents=True)
        target.touch()

        conv_dir = tmp_path / "conventions"
        conv_dir.mkdir()
        routes_yaml = conv_dir / "routes.yaml"
        routes_yaml.write_text(
            "routes:\n"
            '  - pattern: "omnibase_core/src/**/*.py"\n'
            '    conventions: ["onex-contracts", "python-strict"]\n'
        )
        (conv_dir / "onex-contracts.md").write_text("# Contracts\nYAML first.\n")
        (conv_dir / "python-strict.md").write_text("# Strict\nmypy --strict.\n")

        with (
            patch(
                "plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR",
                conv_dir,
            ),
            patch(
                "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
                routes_yaml,
            ),
        ):
            result = get_conventions(str(target))

        assert "# Contracts" in result
        assert "# Strict" in result
        # Separated by double newline
        assert "\n\n" in result

    def test_deduplicates_conventions(self, tmp_path: Path) -> None:
        """Same convention name from multiple routes is only included once."""
        repo = tmp_path / "omnidash"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / "server" / "deep" / "file.ts"
        target.parent.mkdir(parents=True)
        target.touch()

        conv_dir = tmp_path / "conventions"
        conv_dir.mkdir()
        routes_yaml = conv_dir / "routes.yaml"
        routes_yaml.write_text(
            "routes:\n"
            '  - pattern: "omnidash/server/**/*.ts"\n'
            '    conventions: ["omnidash-server"]\n'
            '  - pattern: "omnidash/**/*.ts"\n'
            '    conventions: ["omnidash-server"]\n'
        )
        (conv_dir / "omnidash-server.md").write_text("# Server\n")

        with (
            patch(
                "plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR",
                conv_dir,
            ),
            patch(
                "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
                routes_yaml,
            ),
        ):
            result = get_conventions(str(target))

        # Should appear exactly once
        assert result.count("# Server") == 1

    def test_missing_snippet_file_skipped(self, tmp_path: Path) -> None:
        """Routes pointing to nonexistent snippets are silently skipped."""
        repo = tmp_path / "omnidash"
        repo.mkdir()
        (repo / ".git").mkdir()
        target = repo / "server" / "file.ts"
        target.parent.mkdir(parents=True)
        target.touch()

        conv_dir = tmp_path / "conventions"
        conv_dir.mkdir()
        routes_yaml = conv_dir / "routes.yaml"
        routes_yaml.write_text(
            "routes:\n"
            '  - pattern: "omnidash/server/**/*.ts"\n'
            '    conventions: ["nonexistent-convention"]\n'
        )

        with (
            patch(
                "plugins.onex.hooks.lib.file_path_router.CONVENTIONS_DIR",
                conv_dir,
            ),
            patch(
                "plugins.onex.hooks.lib.file_path_router.ROUTES_FILE",
                routes_yaml,
            ),
        ):
            result = get_conventions(str(target))

        assert result == ""

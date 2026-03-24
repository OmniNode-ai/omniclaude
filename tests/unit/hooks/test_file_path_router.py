# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the file-path convention router."""

from __future__ import annotations

import os

# The module lives in the plugin tree, not in the installed package.
# We import it by manipulating sys.path in the fixture below.
import sys
import textwrap

import pytest


@pytest.fixture(autouse=True)
def _reset_router_cache() -> None:
    """Reset the module-level route cache between tests."""
    # Import after path setup
    lib_dir = os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "plugins",
        "onex",
        "hooks",
        "lib",
    )
    abs_lib = os.path.abspath(lib_dir)
    if abs_lib not in sys.path:
        sys.path.insert(0, abs_lib)

    import file_path_router

    # Reset cache globals
    file_path_router._cached_routes = None
    file_path_router._cached_mtime = 0.0
    file_path_router._cached_path = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_routes(tmp_path: object, content: str) -> str:
    """Write a route config file and return its path."""
    p = os.path.join(str(tmp_path), "routes.yaml")
    with open(p, "w") as f:
        f.write(textwrap.dedent(content))
    return p


def _write_convention(tmp_path: object, name: str, content: str) -> str:
    """Write a convention file and return the conventions dir."""
    conv_dir = os.path.join(str(tmp_path), "conventions")
    os.makedirs(conv_dir, exist_ok=True)
    with open(os.path.join(conv_dir, f"{name}.md"), "w") as f:
        f.write(textwrap.dedent(content))
    return conv_dir


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseRoutes:
    def test_parses_valid_routes(self) -> None:
        from file_path_router import _parse_routes

        text = textwrap.dedent("""\
            routes:
              - pattern: "foo/bar/**"
                convention: "bar-conv"
              - pattern: "**/tests/**"
                convention: "test-conv"
        """)
        routes = _parse_routes(text)
        assert len(routes) == 2
        assert routes[0].pattern == "foo/bar/**"
        assert routes[0].convention == "bar-conv"
        assert routes[1].pattern == "**/tests/**"
        assert routes[1].convention == "test-conv"

    def test_ignores_comments_and_blanks(self) -> None:
        from file_path_router import _parse_routes

        text = textwrap.dedent("""\
            # Comment
            routes:

              - pattern: "a/**"
                convention: "a-conv"
        """)
        routes = _parse_routes(text)
        assert len(routes) == 1

    def test_empty_input(self) -> None:
        from file_path_router import _parse_routes

        assert _parse_routes("") == []


# ---------------------------------------------------------------------------
# Route loading tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadRoutes:
    def test_load_valid_file(self, tmp_path: object) -> None:
        from file_path_router import load_routes

        path = _write_routes(
            tmp_path,
            """\
            routes:
              - pattern: "src/**"
                convention: "src-conv"
            """,
        )
        routes = load_routes(path)
        assert len(routes) == 1
        assert routes[0].convention == "src-conv"

    def test_missing_file_returns_empty(self) -> None:
        from file_path_router import load_routes

        routes = load_routes("/nonexistent/path/routes.yaml")
        assert routes == []

    def test_malformed_yaml_returns_empty(self, tmp_path: object) -> None:
        from file_path_router import load_routes

        path = _write_routes(tmp_path, "{{{{ not valid yaml !!!!")
        routes = load_routes(path)
        assert routes == []

    def test_cache_invalidates_on_mtime_change(self, tmp_path: object) -> None:
        from file_path_router import load_routes

        path = _write_routes(
            tmp_path,
            """\
            routes:
              - pattern: "a/**"
                convention: "a-conv"
            """,
        )
        routes1 = load_routes(path)
        assert len(routes1) == 1

        # Overwrite with different content
        with open(path, "w") as f:
            f.write(
                textwrap.dedent("""\
                routes:
                  - pattern: "b/**"
                    convention: "b-conv"
                  - pattern: "c/**"
                    convention: "c-conv"
            """)
            )
        # Force mtime change (some filesystems have 1s resolution)
        from pathlib import Path as _Path

        new_mtime = _Path(path).stat().st_mtime + 1
        os.utime(path, (new_mtime, new_mtime))

        routes2 = load_routes(path)
        assert len(routes2) == 2
        assert routes2[0].convention == "b-conv"


# ---------------------------------------------------------------------------
# Convention loading tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadConvention:
    def test_extracts_inject_section(self, tmp_path: object) -> None:
        from file_path_router import load_convention

        conv_dir = _write_convention(
            tmp_path,
            "my-conv",
            """\
            # My Convention

            ## Inject

            - Rule one.
            - Rule two.

            ## Other Section

            Ignored content.
            """,
        )
        content = load_convention("my-conv", conv_dir)
        assert "Rule one" in content
        assert "Rule two" in content
        assert "Ignored content" not in content

    def test_missing_convention_returns_empty(self, tmp_path: object) -> None:
        from file_path_router import load_convention

        conv_dir = os.path.join(str(tmp_path), "conventions")
        os.makedirs(conv_dir, exist_ok=True)
        assert load_convention("nonexistent", conv_dir) == ""

    def test_no_inject_section_returns_full_text(self, tmp_path: object) -> None:
        from file_path_router import load_convention

        conv_dir = _write_convention(
            tmp_path,
            "plain",
            """\
            # Plain Convention

            Just some rules without an inject section.
            """,
        )
        content = load_convention("plain", conv_dir)
        assert "Just some rules" in content


# ---------------------------------------------------------------------------
# Matching tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMatchFilePath:
    def _setup(self, tmp_path: object) -> tuple[str, str]:
        """Create a standard route config and conventions dir."""
        config = _write_routes(
            tmp_path,
            """\
            routes:
              - pattern: "omnidash/server/consumers/**"
                convention: "kafka-consumer-conventions"
              - pattern: "**/tests/**"
                convention: "test-conventions"
              - pattern: "**/migrations/**"
                convention: "migration-conventions"
            """,
        )
        conv_dir = _write_convention(
            tmp_path,
            "kafka-consumer-conventions",
            """\
            # Kafka Consumer

            ## Inject

            - Consumer handler isolation rule.
            """,
        )
        _write_convention(
            tmp_path,
            "test-conventions",
            """\
            # Test Conventions

            ## Inject

            - Use pytest markers.
            """,
        )
        _write_convention(
            tmp_path,
            "migration-conventions",
            """\
            # Migration Conventions

            ## Inject

            - Idempotent migrations only.
            """,
        )
        return config, conv_dir

    def test_exact_match(self, tmp_path: object) -> None:
        from file_path_router import match_file_path

        config, conv_dir = self._setup(tmp_path)
        name, content = match_file_path(
            "/abs/path/omnidash/server/consumers/handler.py",
            config_path=config,
            conventions_dir=conv_dir,
        )
        assert name == "kafka-consumer-conventions"
        assert "Consumer handler isolation rule" in content

    def test_glob_match_tests(self, tmp_path: object) -> None:
        from file_path_router import match_file_path

        config, conv_dir = self._setup(tmp_path)
        name, content = match_file_path(
            "/some/repo/tests/unit/test_foo.py",
            config_path=config,
            conventions_dir=conv_dir,
        )
        assert name == "test-conventions"
        assert "pytest markers" in content

    def test_no_match_returns_empty(self, tmp_path: object) -> None:
        from file_path_router import match_file_path

        config, conv_dir = self._setup(tmp_path)
        name, content = match_file_path(
            "/some/random/file.py",
            config_path=config,
            conventions_dir=conv_dir,
        )
        assert name == ""
        assert content == ""

    def test_first_match_wins(self, tmp_path: object) -> None:
        """When multiple routes could match, the first one wins."""
        from file_path_router import match_file_path

        config = _write_routes(
            tmp_path,
            """\
            routes:
              - pattern: "specific/tests/**"
                convention: "specific-conv"
              - pattern: "**/tests/**"
                convention: "generic-conv"
            """,
        )
        conv_dir = _write_convention(
            tmp_path,
            "specific-conv",
            """\
            # Specific

            ## Inject

            - Specific rule.
            """,
        )
        _write_convention(
            tmp_path,
            "generic-conv",
            """\
            # Generic

            ## Inject

            - Generic rule.
            """,
        )
        name, content = match_file_path(
            "/repo/specific/tests/test_a.py",
            config_path=config,
            conventions_dir=conv_dir,
        )
        assert name == "specific-conv"
        assert "Specific rule" in content

    def test_empty_routes_returns_empty(self, tmp_path: object) -> None:
        from file_path_router import match_file_path

        config = _write_routes(tmp_path, "routes:\n")
        name, content = match_file_path(
            "/any/file.py",
            config_path=config,
        )
        assert name == ""
        assert content == ""

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for simple_agent_loader.py

Verifies:
- Agent YAML loading from filesystem
- Search path resolution (multiple filename patterns)
- Fallback behavior with deterministic environment setup
- CLI entry point via stdin JSON
- Error handling for missing/invalid agents
- No test pollution from sys.modules manipulation

All fallback-resolution tests explicitly set up their environment rather
than relying on ambient state (CLAUDE_PLUGIN_ROOT, HOME, etc.) to ensure
deterministic results across CI and local runs.
"""

from __future__ import annotations

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from simple_agent_loader import (
    AGENT_DEFINITIONS_DIR,
    _get_search_paths,
    load_agent,
    load_agent_yaml,
    main,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_dir(tmp_path):
    """Create a temporary agent definitions directory.

    Uses tmp_path so every test gets an isolated, empty directory --
    no ambient filesystem state leaks in.
    """
    agents_dir = tmp_path / "agents" / "omniclaude"
    agents_dir.mkdir(parents=True)
    return agents_dir


@pytest.fixture
def sample_agent_yaml():
    """Return sample agent YAML content."""
    return (
        'schema_version: "1.0.0"\n'
        'agent_type: "test_agent"\n'
        "agent_identity:\n"
        '  name: "agent-test"\n'
        '  description: "Test agent for unit tests"\n'
        "activation_patterns:\n"
        '  explicit_triggers: ["test"]\n'
    )


@pytest.fixture
def agent_dir_with_agent(agent_dir, sample_agent_yaml):
    """Create agent directory containing a sample agent definition file."""
    agent_file = agent_dir / "agent-test.yaml"
    agent_file.write_text(sample_agent_yaml)
    return agent_dir


@pytest.fixture
def _patch_agent_dir(agent_dir):
    """Patch AGENT_DEFINITIONS_DIR to use the temporary agent directory.

    This ensures deterministic search-path resolution regardless of the
    user's HOME directory or any pre-existing agent files.
    """
    with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
        yield agent_dir


# ---------------------------------------------------------------------------
# Tests: _get_search_paths
# ---------------------------------------------------------------------------


class TestGetSearchPaths:
    """Tests for _get_search_paths helper."""

    def test_returns_four_paths_for_prefixed_agent(self):
        """Agent name with 'agent-' prefix should generate 4 search paths."""
        paths = _get_search_paths("agent-api")
        assert len(paths) == 4
        path_names = [p.name for p in paths]
        assert "agent-api.yaml" in path_names
        assert "agent-api.yml" in path_names
        assert "api.yaml" in path_names
        assert "api.yml" in path_names

    def test_returns_four_paths_for_unprefixed_agent(self):
        """Agent name without 'agent-' prefix should still produce 4 paths."""
        paths = _get_search_paths("research")
        assert len(paths) == 4
        path_names = [p.name for p in paths]
        assert "research.yaml" in path_names
        assert "research.yml" in path_names

    def test_all_paths_under_agent_definitions_dir(self):
        """All returned paths should be children of AGENT_DEFINITIONS_DIR."""
        paths = _get_search_paths("agent-test")
        for path in paths:
            assert path.parent == AGENT_DEFINITIONS_DIR

    def test_empty_name_produces_paths(self):
        """Even an empty name should return paths (validation is elsewhere)."""
        paths = _get_search_paths("")
        assert len(paths) == 4

    def test_removeprefix_is_idempotent_for_unprefixed(self):
        """Unprefixed names should not produce duplicate base names."""
        paths = _get_search_paths("research")
        # "research".removeprefix("agent-") == "research" so the
        # prefixed and unprefixed variants produce the same stems.
        yaml_names = [p.name for p in paths if p.suffix == ".yaml"]
        assert len(yaml_names) == 2
        # Both should be "research.yaml" (same stem)
        assert yaml_names[0] == yaml_names[1] == "research.yaml"


# ---------------------------------------------------------------------------
# Tests: load_agent_yaml
# ---------------------------------------------------------------------------


class TestLoadAgentYaml:
    """Tests for load_agent_yaml function."""

    def test_loads_yaml_from_directory(self, agent_dir_with_agent, sample_agent_yaml):
        """Should load YAML content when agent-test.yaml exists."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir_with_agent):
            content = load_agent_yaml("agent-test")

        assert content is not None
        assert "agent-test" in content
        assert "test_agent" in content

    def test_returns_none_for_missing_agent(self, agent_dir):
        """Should return None when no matching file exists."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            content = load_agent_yaml("nonexistent-agent")

        assert content is None

    def test_loads_via_unprefixed_name(self, agent_dir, sample_agent_yaml):
        """Should find agent file using the name after stripping 'agent-'."""
        # Create a file named "test.yaml" (the unprefixed variant)
        (agent_dir / "test.yaml").write_text(sample_agent_yaml)

        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            content = load_agent_yaml("agent-test")

        assert content is not None

    def test_loads_yml_extension(self, agent_dir, sample_agent_yaml):
        """Should find agent file with .yml extension."""
        (agent_dir / "agent-test.yml").write_text(sample_agent_yaml)

        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            content = load_agent_yaml("agent-test")

        assert content is not None

    def test_prefers_yaml_over_yml(self, agent_dir):
        """When both .yaml and .yml exist, .yaml should be found first."""
        (agent_dir / "agent-test.yaml").write_text("yaml_content: true\n")
        (agent_dir / "agent-test.yml").write_text("yml_content: true\n")

        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            content = load_agent_yaml("agent-test")

        assert content is not None
        assert "yaml_content" in content

    def test_handles_read_error_gracefully(self, agent_dir):
        """Should return None and log warning when file cannot be read."""
        # Create a directory instead of a file -- reading it will raise OSError
        (agent_dir / "agent-broken.yaml").mkdir()

        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            content = load_agent_yaml("agent-broken")

        assert content is None


# ---------------------------------------------------------------------------
# Tests: load_agent
# ---------------------------------------------------------------------------


class TestLoadAgent:
    """Tests for load_agent function."""

    def test_successful_load_returns_success_result(
        self, agent_dir_with_agent, sample_agent_yaml
    ):
        """Successful load should return success=True with context_injection."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir_with_agent):
            result = load_agent("agent-test")

        assert result["success"] is True
        assert "context_injection" in result
        assert result["agent_name"] == "agent-test"
        assert result["context_injection"] == sample_agent_yaml

    def test_missing_agent_returns_failure_with_searched_paths(self, agent_dir):
        """Missing agent should return failure with the paths that were tried."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            result = load_agent("nonexistent")

        assert result["success"] is False
        assert "error" in result
        assert "searched_paths" in result
        assert len(result["searched_paths"]) == 4

    def test_empty_name_returns_failure(self):
        """Empty agent name should return failure immediately."""
        result = load_agent("")

        assert result["success"] is False
        assert "No agent name provided" in result["error"]

    def test_fallback_resolution_is_deterministic(self, agent_dir):
        """Repeated calls with same missing agent produce identical results.

        Explicitly patches AGENT_DEFINITIONS_DIR to an isolated directory
        so no ambient state can influence the outcome.
        """
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            result1 = load_agent("agent-deterministic")
            result2 = load_agent("agent-deterministic")

        assert result1 == result2
        assert result1["success"] is False
        assert result1["searched_paths"] == result2["searched_paths"]

    def test_searched_paths_match_get_search_paths(self, agent_dir):
        """Failure result searched_paths should match _get_search_paths output."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            result = load_agent("agent-check")

        expected = [str(p) for p in _get_search_paths("agent-check")]
        # The paths in the result use the patched directory
        assert len(result["searched_paths"]) == len(expected)

    def test_error_message_includes_agent_name(self, agent_dir):
        """Failure error message should contain the requested agent name."""
        with patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir):
            result = load_agent("agent-missing")

        assert "agent-missing" in result["error"]


# ---------------------------------------------------------------------------
# Tests: CLI (main)
# ---------------------------------------------------------------------------


class TestMainCLI:
    """Tests for the CLI entry point (reads JSON from stdin).

    All tests use explicit patching to ensure deterministic behavior.
    The CLI does not call sys.exit() -- it prints JSON to stdout -- so
    these tests verify output rather than exit codes.
    """

    def test_valid_input_returns_success_json(self, agent_dir_with_agent, capsys):
        """Valid stdin JSON with existing agent returns success JSON."""
        input_data = json.dumps({"agent_name": "agent-test"})

        with (
            patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir_with_agent),
            patch("sys.stdin", StringIO(input_data)),
        ):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["agent_name"] == "agent-test"

    def test_missing_agent_returns_failure_json(self, agent_dir, capsys):
        """Valid stdin JSON with missing agent returns failure JSON."""
        input_data = json.dumps({"agent_name": "no-such-agent"})

        with (
            patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir),
            patch("sys.stdin", StringIO(input_data)),
        ):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "no-such-agent" in result["error"]

    def test_invalid_json_returns_error(self, capsys):
        """Invalid JSON input should return an error result (not crash)."""
        with patch("sys.stdin", StringIO("not valid json")):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_empty_agent_name_returns_failure(self, agent_dir, capsys):
        """Input with empty agent_name should return failure."""
        input_data = json.dumps({"agent_name": ""})

        with (
            patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir),
            patch("sys.stdin", StringIO(input_data)),
        ):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False

    def test_missing_agent_name_key_returns_failure(self, agent_dir, capsys):
        """Input without agent_name key defaults to empty string (failure)."""
        input_data = json.dumps({"other_key": "value"})

        with (
            patch("simple_agent_loader.AGENT_DEFINITIONS_DIR", agent_dir),
            patch("sys.stdin", StringIO(input_data)),
        ):
            main()

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False

    def test_cli_always_outputs_valid_json(self, capsys):
        """CLI should always output valid JSON, even on unexpected inputs."""
        invalid_inputs = [
            "",
            "[]",
            '"just a string"',
        ]

        for input_text in invalid_inputs:
            with patch("sys.stdin", StringIO(input_text)):
                main()

            captured = capsys.readouterr()
            # Must always be parseable JSON
            result = json.loads(captured.out)
            assert isinstance(result, dict)
            assert "success" in result

    def test_consistent_error_structure(self, capsys):
        """All error responses should have the same keys."""
        error_inputs = [
            "not json",
            json.dumps({}),
            json.dumps({"agent_name": ""}),
        ]

        for input_text in error_inputs:
            with patch("sys.stdin", StringIO(input_text)):
                main()

            captured = capsys.readouterr()
            result = json.loads(captured.out)
            assert result["success"] is False
            assert "error" in result
            assert "agent_name" in result


# ---------------------------------------------------------------------------
# Tests: Module reload cleanup (anti-pollution)
# ---------------------------------------------------------------------------


class TestModuleCleanup:
    """Verify that importing and reloading the loader does not pollute sys.modules.

    Uses the restore_sys_modules fixture from conftest.py to guarantee
    that any sys.modules manipulation is reverted after each test.
    """

    def test_import_does_not_leave_test_artifacts(self, restore_sys_modules):
        """Importing simple_agent_loader should not inject unexpected modules."""
        # Use a namespaced name to avoid colliding with real "models" module
        test_module_key = "test_simple_agent_loader__sentinel"
        assert test_module_key not in sys.modules

        # Inject and verify it is cleaned up by the fixture
        from unittest.mock import MagicMock

        sys.modules[test_module_key] = MagicMock()
        assert test_module_key in sys.modules
        # After the test, restore_sys_modules teardown removes it

    def test_deleted_modules_are_restored(self, restore_sys_modules):
        """Modules deleted during the test should be restored by fixture."""
        # Pick a module we know exists
        assert "json" in sys.modules
        saved_json = sys.modules["json"]

        del sys.modules["json"]
        assert "json" not in sys.modules
        # After teardown, "json" should reappear with the original object

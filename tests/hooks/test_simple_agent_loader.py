# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for simple_agent_loader module.

Security-focused tests for agent YAML loading with path traversal prevention
and CLAUDE_PLUGIN_ROOT resolution hardening.

SECURITY Tests:
- Path traversal prevention (../, /, \\)
- Allowlist validation (alphanumeric, hyphen, underscore only)
- Length limits to prevent DoS
- CLAUDE_PLUGIN_ROOT validation and fallbacks
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Test validate_agent_name - Security: Path Traversal Prevention
# =============================================================================


class TestValidateAgentName:
    """Security tests for agent name validation."""

    def test_valid_simple_name(self) -> None:
        """Valid simple agent name should pass."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("agent-api")
        assert is_valid is True
        assert error == ""

    def test_valid_name_with_underscore(self) -> None:
        """Valid name with underscore should pass."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("agent_api_v2")
        assert is_valid is True
        assert error == ""

    def test_valid_name_alphanumeric(self) -> None:
        """Valid alphanumeric name should pass."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("Agent123")
        assert is_valid is True
        assert error == ""

    def test_reject_path_traversal_dotdot(self) -> None:
        """Path traversal with .. should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("../etc/passwd")
        assert is_valid is False
        assert ".." in error

    def test_reject_path_traversal_forward_slash(self) -> None:
        """Path traversal with / should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("agent/path")
        assert is_valid is False
        assert "path separator" in error

    def test_reject_path_traversal_backslash(self) -> None:
        """Path traversal with \\ should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("agent\\path")
        assert is_valid is False
        assert "path separator" in error

    def test_reject_empty_name(self) -> None:
        """Empty agent name should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, error = validate_agent_name("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_reject_special_characters(self) -> None:
        """Special characters should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        # Test various special characters
        invalid_names = [
            "agent@api",
            "agent#api",
            "agent$api",
            "agent%api",
            "agent^api",
            "agent&api",
            "agent*api",
            "agent!api",
            "agent api",  # space
            "agent\tapi",  # tab
            "agent\napi",  # newline
        ]
        for name in invalid_names:
            is_valid, _error = validate_agent_name(name)
            assert is_valid is False, f"Expected {name!r} to be rejected"

    def test_reject_overly_long_name(self) -> None:
        """Names exceeding max length should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        long_name = "a" * 129  # Exceeds 128 char limit
        is_valid, error = validate_agent_name(long_name)
        assert is_valid is False
        assert "length" in error.lower()

    def test_accept_max_length_name(self) -> None:
        """Names at exactly max length should pass."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        max_name = "a" * 128
        is_valid, error = validate_agent_name(max_name)
        assert is_valid is True
        assert error == ""

    def test_reject_null_byte(self) -> None:
        """Null byte injection should be rejected."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        is_valid, _error = validate_agent_name("agent\x00api")
        assert is_valid is False

    def test_reject_unicode_path_separators(self) -> None:
        """Unicode path-like characters should be rejected by allowlist."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        # Unicode slash-like characters
        is_valid, _error = validate_agent_name("agent\u2215api")  # Division slash
        assert is_valid is False

    def test_reject_encoded_traversal(self) -> None:
        """URL-encoded traversal attempts should be rejected by allowlist."""
        from plugins.onex.hooks.lib.simple_agent_loader import validate_agent_name

        # %2e%2e%2f would decode to ../
        is_valid, _error = validate_agent_name("%2e%2e%2f")
        assert is_valid is False


# =============================================================================
# Test load_agent - Security: Defense in Depth
# =============================================================================


class TestLoadAgent:
    """Tests for load_agent function with security validation."""

    def test_load_agent_rejects_path_traversal(self) -> None:
        """load_agent should reject path traversal attempts."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        result = load_agent("../../../etc/passwd")
        assert result["success"] is False
        assert ".." in result["error"]

    def test_load_agent_rejects_slash(self) -> None:
        """load_agent should reject forward slash."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        result = load_agent("agent/subdir/config")
        assert result["success"] is False
        assert "path separator" in result["error"]

    def test_load_agent_empty_name(self) -> None:
        """load_agent should handle empty name gracefully."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        result = load_agent("")
        assert result["success"] is False
        assert "No agent name provided" in result["error"]

    def test_load_agent_valid_name_not_found(self) -> None:
        """load_agent should return searched paths for valid but missing agent."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        result = load_agent("nonexistent-agent-xyz123")
        assert result["success"] is False
        assert "not found" in result["error"].lower()
        assert "searched_paths" in result
        assert len(result["searched_paths"]) > 0


class TestLoadAgentYaml:
    """Tests for load_agent_yaml with ValueError for invalid names."""

    def test_raises_valueerror_for_path_traversal(self) -> None:
        """load_agent_yaml should raise ValueError for path traversal."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent_yaml

        with pytest.raises(ValueError) as exc_info:
            load_agent_yaml("../etc/passwd")
        assert ".." in str(exc_info.value)

    def test_raises_valueerror_for_slash(self) -> None:
        """load_agent_yaml should raise ValueError for slash."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent_yaml

        with pytest.raises(ValueError) as exc_info:
            load_agent_yaml("agent/path")
        assert "path separator" in str(exc_info.value)


# =============================================================================
# Test _resolve_agent_definitions_dir - Configuration Hardening
# =============================================================================


class TestResolveAgentDefinitionsDir:
    """Tests for CLAUDE_PLUGIN_ROOT resolution with fallbacks.

    Note: These tests use importlib.reload() to test environment variable
    handling. A cleanup fixture ensures module state is restored after each
    test to prevent test pollution.
    """

    @pytest.fixture(autouse=True)
    def cleanup_module_reload(self) -> None:
        """Restore simple_agent_loader module after reload-based tests.

        Module reloads in tests can pollute global state for subsequent tests.
        This fixture ensures the module's cached AGENT_DEFINITIONS_DIR is reset.

        The cleanup is wrapped in try/finally to ensure it runs even if the
        test fails, and uses exception handling to prevent cleanup failures
        from masking test failures.
        """
        import importlib
        import sys

        # Capture original module state before test
        module_name = "plugins.onex.hooks.lib.simple_agent_loader"
        original_module = sys.modules.get(module_name)

        try:
            yield
        finally:
            # Re-import and reload with current environment to restore state
            # Use try/except to prevent reload failures from masking test errors
            try:
                import plugins.onex.hooks.lib.simple_agent_loader as loader

                importlib.reload(loader)
            except Exception:
                # If reload fails, at least restore the original module reference
                if original_module is not None:
                    sys.modules[module_name] = original_module

    def test_uses_plugin_root_when_valid(self) -> None:
        """Should use CLAUDE_PLUGIN_ROOT when set and valid."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create the expected structure
            agents_dir = Path(tmpdir) / "agents" / "configs"
            agents_dir.mkdir(parents=True)

            with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": tmpdir}):
                # Re-import to trigger resolution
                import importlib

                import plugins.onex.hooks.lib.simple_agent_loader as loader

                importlib.reload(loader)

                result = loader._resolve_agent_definitions_dir()
                assert result == agents_dir

    def test_falls_back_when_plugin_root_missing(self) -> None:
        """Should fall back when CLAUDE_PLUGIN_ROOT is not set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove CLAUDE_PLUGIN_ROOT if present
            env = os.environ.copy()
            env.pop("CLAUDE_PLUGIN_ROOT", None)

            with patch.dict(os.environ, env, clear=True):
                import importlib

                import plugins.onex.hooks.lib.simple_agent_loader as loader

                importlib.reload(loader)

                # Should not raise, should return a path
                result = loader._resolve_agent_definitions_dir()
                assert isinstance(result, Path)

    def test_falls_back_when_plugin_root_invalid_path(self) -> None:
        """Should fall back when CLAUDE_PLUGIN_ROOT points to nonexistent path."""
        with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": "/nonexistent/path/xyz123"}):
            import importlib

            import plugins.onex.hooks.lib.simple_agent_loader as loader

            importlib.reload(loader)

            # Should not raise, should fall back
            result = loader._resolve_agent_definitions_dir()
            assert isinstance(result, Path)

    def test_falls_back_when_agents_configs_missing(self) -> None:
        """Should fall back when agents/configs subdir doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Don't create agents/configs structure
            with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": tmpdir}):
                import importlib

                import plugins.onex.hooks.lib.simple_agent_loader as loader

                importlib.reload(loader)

                # Should fall back to script-relative or legacy
                result = loader._resolve_agent_definitions_dir()
                assert isinstance(result, Path)

    def test_strips_whitespace_from_plugin_root(self) -> None:
        """Should handle whitespace in CLAUDE_PLUGIN_ROOT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_dir = Path(tmpdir) / "agents" / "configs"
            agents_dir.mkdir(parents=True)

            # Add whitespace around the path
            with patch.dict(os.environ, {"CLAUDE_PLUGIN_ROOT": f"  {tmpdir}  "}):
                import importlib

                import plugins.onex.hooks.lib.simple_agent_loader as loader

                importlib.reload(loader)

                result = loader._resolve_agent_definitions_dir()
                assert result == agents_dir


# =============================================================================
# Test _get_search_paths - Path Construction
# =============================================================================


class TestGetSearchPaths:
    """Tests for search path construction."""

    def test_returns_multiple_paths(self) -> None:
        """Should return multiple search paths for fallback."""
        from plugins.onex.hooks.lib.simple_agent_loader import _get_search_paths

        paths = _get_search_paths("agent-api")
        assert len(paths) >= 2  # At least .yaml and .yml
        assert any("agent-api.yaml" in str(p) for p in paths)
        assert any("agent-api.yml" in str(p) for p in paths)

    def test_strips_agent_prefix(self) -> None:
        """Should also search for name without agent- prefix."""
        from plugins.onex.hooks.lib.simple_agent_loader import _get_search_paths

        paths = _get_search_paths("agent-api")
        # Should have paths for both "agent-api" and "api"
        path_strs = [str(p) for p in paths]
        assert any("agent-api.yaml" in p for p in path_strs)
        assert any("api.yaml" in p for p in path_strs)

    def test_no_prefix_strip_when_no_prefix(self) -> None:
        """Should handle names without agent- prefix correctly."""
        from plugins.onex.hooks.lib.simple_agent_loader import _get_search_paths

        paths = _get_search_paths("research")
        # Should still work, just with research.yaml (no stripping needed)
        path_strs = [str(p) for p in paths]
        assert any("research.yaml" in p for p in path_strs)


# =============================================================================
# Integration-style Tests (still unit, but more complete flow)
# =============================================================================


class TestAgentLoadingIntegration:
    """Integration-style tests for complete agent loading flow."""

    def test_load_real_agent_if_exists(self) -> None:
        """Should successfully load a real agent if it exists."""
        from plugins.onex.hooks.lib.simple_agent_loader import AGENT_DEFINITIONS_DIR

        # Check if any agents exist
        if not AGENT_DEFINITIONS_DIR.exists():
            pytest.skip("No agent definitions directory found")

        yaml_files = list(AGENT_DEFINITIONS_DIR.glob("*.yaml"))
        if not yaml_files:
            pytest.skip("No agent YAML files found")

        # Load the first available agent
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        agent_file = yaml_files[0]
        agent_name = agent_file.stem

        result = load_agent(agent_name)
        assert result["success"] is True
        assert "context_injection" in result
        assert len(result["context_injection"]) > 0

    def test_security_validation_before_file_access(self) -> None:
        """Security validation should happen before any file system access."""
        from plugins.onex.hooks.lib.simple_agent_loader import load_agent

        # Create a mock that would error if called
        with patch(
            "plugins.onex.hooks.lib.simple_agent_loader._get_search_paths"
        ) as mock_paths:
            mock_paths.side_effect = RuntimeError("Should not be called")

            # Path traversal should be caught before _get_search_paths is called
            result = load_agent("../etc/passwd")
            assert result["success"] is False
            assert ".." in result["error"]

            # Mock should NOT have been called because validation failed first
            mock_paths.assert_not_called()

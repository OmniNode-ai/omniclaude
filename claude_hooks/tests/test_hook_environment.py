#!/usr/bin/env python3
"""
Tests for Claude hooks environment setup.

These tests verify that the hooks have access to the omniclaude poetry
environment and all required dependencies.

Run with: pytest ~/.claude/hooks/tests/test_hook_environment.py -v
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest


HOOK_DIR = Path.home() / ".claude" / "hooks"
OMNICLAUDE_DIR = Path("/Volumes/PRO-G40/Code/omniclaude")


class TestHookEnvironmentSetup:
    """Tests for hook environment configuration."""

    def test_hook_dir_exists(self):
        """Verify hooks directory exists."""
        assert HOOK_DIR.exists(), f"Hooks directory not found: {HOOK_DIR}"

    def test_bin_python3_wrapper_exists(self):
        """Verify python3 wrapper script exists and is executable."""
        wrapper = HOOK_DIR / "bin" / "python3"
        assert wrapper.exists(), f"python3 wrapper not found: {wrapper}"
        assert os.access(wrapper, os.X_OK), f"python3 wrapper not executable: {wrapper}"

    def test_venv_symlink_exists(self):
        """Verify .venv symlink exists and points to valid directory."""
        venv = HOOK_DIR / ".venv"
        assert venv.exists(), (
            f".venv not found: {venv}\n" f"Run: ~/.claude/hooks/setup-venv.sh"
        )
        assert venv.is_symlink(), f".venv should be a symlink: {venv}"
        assert (
            venv.resolve().exists()
        ), f".venv symlink target doesn't exist: {venv.resolve()}"

    def test_venv_has_python(self):
        """Verify .venv has a working Python interpreter."""
        python = HOOK_DIR / ".venv" / "bin" / "python3"
        assert python.exists(), f"Python not found in venv: {python}"

        # Test it runs
        result = subprocess.run(
            [str(python), "--version"], capture_output=True, text=True
        )
        assert result.returncode == 0, f"Python failed: {result.stderr}"
        assert (
            "Python 3" in result.stdout
        ), f"Unexpected Python version: {result.stdout}"


class TestRequiredPackages:
    """Tests for required Python packages."""

    @pytest.mark.parametrize(
        ("package", "import_name"),
        [
            ("python-dotenv", "dotenv"),
            ("pyyaml", "yaml"),
            ("httpx", "httpx"),
            # ("loguru", "loguru"),  # Optional - not critical for hooks
            ("kafka-python", "kafka"),
        ],
    )
    def test_required_package_installed(self, package, import_name):
        """Verify required packages are importable via the hooks Python."""
        python = HOOK_DIR / ".venv" / "bin" / "python3"
        if not python.exists():
            pytest.skip(".venv not set up - run setup-venv.sh")

        result = subprocess.run(
            [str(python), "-c", f"import {import_name}"], capture_output=True, text=True
        )
        assert result.returncode == 0, (
            f"Package {package} (import {import_name}) not available:\n"
            f"{result.stderr}\n"
            f"Run: cd {OMNICLAUDE_DIR} && poetry add {package}"
        )

    def test_config_module_importable(self):
        """Verify config module from omniclaude is importable."""
        python = HOOK_DIR / ".venv" / "bin" / "python3"
        if not python.exists():
            pytest.skip(".venv not set up - run setup-venv.sh")

        result = subprocess.run(
            [
                str(python),
                "-c",
                "from config import settings; print(settings.enforcement_mode)",
            ],
            capture_output=True,
            text=True,
            cwd=str(HOOK_DIR),  # Run from hooks dir to test path resolution
        )
        assert result.returncode == 0, (
            f"Config module not importable:\n{result.stderr}\n"
            f"Check config symlink: ls -la {HOOK_DIR}/config"
        )


class TestHookScripts:
    """Tests for hook script functionality."""

    def test_quality_hook_passes_nonwrite_tools(self):
        """Verify quality hook passes through non-Write tools."""
        hook = HOOK_DIR / "pre-tool-use-quality.sh"
        if not hook.exists():
            pytest.skip("pre-tool-use-quality.sh not found")

        test_input = '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
        result = subprocess.run(
            ["bash", str(hook)],
            input=test_input,
            capture_output=True,
            text=True,
            cwd=str(HOOK_DIR),
        )

        assert result.returncode == 0, f"Hook failed: {result.stderr}"
        assert "Bash" in result.stdout, f"Tool info not passed through: {result.stdout}"

    def test_quality_hook_processes_write_tools(self):
        """Verify quality hook processes Write tools without crashing."""
        hook = HOOK_DIR / "pre-tool-use-quality.sh"
        if not hook.exists():
            pytest.skip("pre-tool-use-quality.sh not found")

        test_input = '{"tool_name":"Write","tool_input":{"file_path":"/tmp/test.txt","content":"test"}}'
        result = subprocess.run(
            ["bash", str(hook)],
            input=test_input,
            capture_output=True,
            text=True,
            cwd=str(HOOK_DIR),
            timeout=10,
        )

        # Exit 0 = pass, Exit 2 = blocked (both are valid)
        assert result.returncode in [0, 2], (
            f"Hook crashed with unexpected exit code {result.returncode}:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    def test_permissions_hook_works(self):
        """Verify permissions hook doesn't crash."""
        hook = HOOK_DIR / "pre_tool_use_permissions.py"
        python = HOOK_DIR / ".venv" / "bin" / "python3"

        if not hook.exists():
            pytest.skip("pre_tool_use_permissions.py not found")
        if not python.exists():
            pytest.skip(".venv not set up")

        test_input = '{"tool_name":"Bash","tool_input":{"command":"ls"}}'
        result = subprocess.run(
            [str(python), str(hook)], input=test_input, capture_output=True, text=True
        )

        assert result.returncode == 0, f"Permissions hook failed: {result.stderr}"


class TestCacheAndSymlinks:
    """Tests for cache and symlink integrity."""

    def test_poetry_venv_cache_exists(self):
        """Verify poetry venv path is cached."""
        cache_file = HOOK_DIR / ".cache" / "poetry_venv_path"
        assert cache_file.exists(), (
            f"Cache file not found: {cache_file}\n"
            f"Run: ~/.claude/hooks/setup-venv.sh"
        )

        cached_path = cache_file.read_text().strip()
        assert Path(cached_path).exists(), (
            f"Cached venv path doesn't exist: {cached_path}\n"
            f"Run: ~/.claude/hooks/setup-venv.sh"
        )

    def test_config_symlink_valid(self):
        """Verify config symlink points to omniclaude config."""
        config_link = HOOK_DIR / "config"
        assert config_link.exists(), f"Config symlink not found: {config_link}"

        target = config_link.resolve()
        assert target.exists(), f"Config symlink target doesn't exist: {target}"
        assert "omniclaude" in str(
            target
        ), f"Config should point to omniclaude: {target}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

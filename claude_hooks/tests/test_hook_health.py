#!/usr/bin/env python3
"""
Hook health verification tests.

Tests that hook scripts are syntactically valid and properly configured.
These tests catch issues before hooks fail in production.

Author: OmniClaude Framework
Version: 1.0.0
"""

import ast
import os
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest


# ============================================================================
# CONSTANTS
# ============================================================================

HOOKS_DIR = Path(__file__).parent.parent
LIB_DIR = HOOKS_DIR / "lib"


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def shell_scripts() -> List[Path]:
    """Get all shell scripts in hooks directory."""
    scripts = []
    for script in HOOKS_DIR.glob("*.sh"):
        scripts.append(script)
    for script in HOOKS_DIR.glob("**/*.sh"):
        # Skip .venv and other hidden directories
        if ".venv" not in str(script) and "/.cache/" not in str(script):
            if script not in scripts:
                scripts.append(script)
    return scripts


@pytest.fixture
def python_files() -> List[Path]:
    """Get all Python files in hooks directory."""
    files = []
    for py_file in HOOKS_DIR.glob("*.py"):
        files.append(py_file)
    for py_file in LIB_DIR.glob("*.py"):
        files.append(py_file)
    for py_file in HOOKS_DIR.glob("tests/*.py"):
        files.append(py_file)
    # Remove duplicates
    return list(set(files))


@pytest.fixture
def core_hook_scripts() -> List[Path]:
    """Get the core hook shell scripts that must be valid."""
    return [
        HOOKS_DIR / "user-prompt-submit.sh",
        HOOKS_DIR / "pre-tool-use-quality.sh",
        HOOKS_DIR / "post-tool-use-quality.sh",
        HOOKS_DIR / "session-start.sh",
        HOOKS_DIR / "session-end.sh",
    ]


@pytest.fixture
def core_python_modules() -> List[Path]:
    """Get core Python modules that must compile."""
    return [
        LIB_DIR / "hook_event_adapter.py",
        LIB_DIR / "correlation_manager.py",
        LIB_DIR / "metadata_extractor.py",
        LIB_DIR / "hook_event_logger.py",
        LIB_DIR / "agent_detector.py",
        LIB_DIR / "resilience.py",
        HOOKS_DIR / "pre_tool_use_permissions.py",
        HOOKS_DIR / "quality_enforcer.py",
    ]


# ============================================================================
# SHELL SCRIPT SYNTAX TESTS
# ============================================================================


@pytest.mark.unit
class TestShellScriptSyntax:
    """Verify all hook shell scripts have valid syntax."""

    def test_hook_scripts_syntax(self, shell_scripts):
        """Verify all hook shell scripts have valid bash syntax."""
        invalid_scripts: List[str] = []

        for script in shell_scripts:
            if not script.exists():
                continue

            # Check bash syntax with -n (no execute, syntax check only)
            result = subprocess.run(
                ["bash", "-n", str(script)],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                invalid_scripts.append(f"{script.name}: {result.stderr.strip()}")

        if invalid_scripts:
            pytest.fail(
                f"Shell scripts with syntax errors:\n"
                f"  {chr(10).join('- ' + s for s in invalid_scripts)}"
            )

    def test_core_hook_scripts_exist(self, core_hook_scripts):
        """Verify core hook scripts exist."""
        missing = [s for s in core_hook_scripts if not s.exists()]

        if missing:
            pytest.fail(
                f"Missing core hook scripts:\n"
                f"  {chr(10).join('- ' + str(s) for s in missing)}"
            )

    def test_core_hook_scripts_executable(self, core_hook_scripts):
        """Verify core hook scripts are executable."""
        non_executable = []

        for script in core_hook_scripts:
            if script.exists() and not os.access(script, os.X_OK):
                non_executable.append(script)

        if non_executable:
            pytest.fail(
                f"Hook scripts not executable:\n"
                f"  {chr(10).join('- ' + str(s) for s in non_executable)}\n\n"
                f"Fix with: chmod +x <script>"
            )

    @pytest.mark.parametrize(
        "script_name",
        [
            "user-prompt-submit.sh",
            "pre-tool-use-quality.sh",
            "post-tool-use-quality.sh",
        ],
    )
    def test_individual_core_script_syntax(self, script_name):
        """Test individual core script syntax."""
        script = HOOKS_DIR / script_name

        if not script.exists():
            pytest.skip(f"{script_name} not found")

        result = subprocess.run(
            ["bash", "-n", str(script)],
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode == 0
        ), f"{script_name} has syntax errors:\n{result.stderr}"

    def test_shebang_present(self, core_hook_scripts):
        """Verify core scripts have proper shebang."""
        missing_shebang = []

        for script in core_hook_scripts:
            if not script.exists():
                continue

            first_line = script.read_text().split("\n")[0]

            if not first_line.startswith("#!"):
                missing_shebang.append(script.name)

        if missing_shebang:
            pytest.fail(
                f"Scripts missing shebang (#!):\n"
                f"  {chr(10).join('- ' + s for s in missing_shebang)}"
            )


# ============================================================================
# PYTHON FILE COMPILATION TESTS
# ============================================================================


@pytest.mark.unit
class TestPythonFilesCompile:
    """Verify all Python files in hooks compile without syntax errors."""

    def test_python_files_compile(self, python_files):
        """Verify all Python files compile without syntax errors."""
        compilation_errors: List[str] = []

        for py_file in python_files:
            if not py_file.exists():
                continue

            try:
                py_compile.compile(str(py_file), doraise=True)
            except py_compile.PyCompileError as e:
                compilation_errors.append(f"{py_file.name}: {e}")

        if compilation_errors:
            pytest.fail(
                f"Python files with syntax errors:\n"
                f"  {chr(10).join('- ' + e for e in compilation_errors)}"
            )

    def test_core_python_modules_compile(self, core_python_modules):
        """Verify core Python modules compile."""
        errors: List[str] = []

        for module in core_python_modules:
            if not module.exists():
                errors.append(f"{module.name}: File not found")
                continue

            try:
                py_compile.compile(str(module), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(f"{module.name}: {e}")

        if errors:
            pytest.fail(
                f"Core Python modules with errors:\n"
                f"  {chr(10).join('- ' + e for e in errors)}"
            )

    def test_python_files_parse_ast(self, python_files):
        """Verify Python files can be parsed as valid AST."""
        parse_errors: List[str] = []

        for py_file in python_files:
            if not py_file.exists():
                continue

            try:
                source = py_file.read_text()
                ast.parse(source)
            except SyntaxError as e:
                parse_errors.append(f"{py_file.name}:{e.lineno}: {e.msg}")

        if parse_errors:
            pytest.fail(
                f"Python files with AST parse errors:\n"
                f"  {chr(10).join('- ' + e for e in parse_errors)}"
            )

    @pytest.mark.parametrize(
        "module_name",
        [
            "hook_event_adapter.py",
            "correlation_manager.py",
            "metadata_extractor.py",
            "hook_event_logger.py",
            "agent_detector.py",
        ],
    )
    def test_individual_core_module_compiles(self, module_name):
        """Test individual core module compilation."""
        module = LIB_DIR / module_name

        if not module.exists():
            pytest.skip(f"{module_name} not found")

        try:
            py_compile.compile(str(module), doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"{module_name} compilation error: {e}")


# ============================================================================
# HOOK CONFIGURATION TESTS
# ============================================================================


@pytest.mark.unit
class TestHookConfiguration:
    """Test hook configuration files are valid."""

    def test_pytest_ini_valid(self):
        """Verify pytest.ini is valid configuration."""
        pytest_ini = HOOKS_DIR / "pytest.ini"

        if not pytest_ini.exists():
            pytest.skip("pytest.ini not found")

        content = pytest_ini.read_text()

        # Check required sections
        assert "[pytest]" in content, "Missing [pytest] section"

        # Check for valid pytest options (no syntax errors)
        # We're running pytest with this config, so if it's invalid, this test fails

    def test_requirements_txt_format(self):
        """Verify requirements.txt has valid format."""
        req_file = HOOKS_DIR / "requirements.txt"

        if not req_file.exists():
            pytest.skip("requirements.txt not found")

        content = req_file.read_text()
        lines = content.strip().split("\n")

        invalid_lines: List[str] = []

        for i, line in enumerate(lines, 1):
            line = line.strip()

            # Skip comments and empty lines
            if not line or line.startswith("#"):
                continue

            # Basic validation: should have package name
            if not any(c.isalpha() for c in line):
                invalid_lines.append(f"Line {i}: '{line}' - no package name")
                continue

            # Check for common format errors
            if line.startswith("-") and not line.startswith("-r"):
                # Allow -r for recursive includes
                if not line.startswith("-r "):
                    invalid_lines.append(f"Line {i}: '{line}' - invalid option")

        if invalid_lines:
            pytest.fail(
                f"requirements.txt format errors:\n"
                f"  {chr(10).join('- ' + e for e in invalid_lines)}"
            )

    def test_config_yaml_valid(self):
        """Verify config.yaml is valid YAML if present."""
        config_file = HOOKS_DIR / "config.yaml"

        if not config_file.exists():
            pytest.skip("config.yaml not found")

        import yaml

        try:
            content = config_file.read_text()
            yaml.safe_load(content)
        except yaml.YAMLError as e:
            pytest.fail(f"config.yaml is invalid YAML: {e}")


# ============================================================================
# HOOK SCRIPT CONTENT TESTS
# ============================================================================


@pytest.mark.unit
class TestHookScriptContent:
    """Test hook script content for common issues."""

    def test_user_prompt_submit_reads_stdin(self):
        """Verify user-prompt-submit.sh reads from stdin."""
        script = HOOKS_DIR / "user-prompt-submit.sh"

        if not script.exists():
            pytest.skip("user-prompt-submit.sh not found")

        content = script.read_text()

        # Should read JSON from stdin (common patterns)
        stdin_patterns = [
            "read",
            "stdin",
            "cat",
            "/dev/stdin",
            "<&0",
        ]

        has_stdin_read = any(p in content.lower() for p in stdin_patterns)
        assert (
            has_stdin_read
        ), "user-prompt-submit.sh should read from stdin for hook input"

    def test_hook_outputs_json(self):
        """Verify hooks output JSON (required by Claude Code)."""
        core_hooks = [
            HOOKS_DIR / "user-prompt-submit.sh",
            HOOKS_DIR / "pre-tool-use-quality.sh",
            HOOKS_DIR / "post-tool-use-quality.sh",
        ]

        for hook in core_hooks:
            if not hook.exists():
                continue

            content = hook.read_text()

            # Should produce JSON output (look for jq, echo with JSON, etc.)
            json_patterns = [
                "jq",
                '{"',
                "json",
                "echo '{",
            ]

            has_json_output = any(p in content for p in json_patterns)
            assert has_json_output, f"{hook.name} should output JSON for Claude Code"

    def test_no_hardcoded_secrets(self):
        """Verify hooks don't have hardcoded secrets."""
        secret_patterns = [
            "password=",
            "api_key=",
            "secret=",
            "token=sk-",
            "ANTHROPIC_API_KEY=sk-",
        ]

        files_with_secrets: List[str] = []

        # Check shell scripts
        for script in HOOKS_DIR.glob("*.sh"):
            content = script.read_text().lower()
            for pattern in secret_patterns:
                if pattern.lower() in content:
                    # Exclude comments and environment variable references
                    lines = script.read_text().split("\n")
                    for i, line in enumerate(lines, 1):
                        if pattern.lower() in line.lower():
                            # Skip if it's an env var reference like $PASSWORD or ${PASSWORD}
                            if "$" in line:
                                continue
                            # Skip if it's a comment
                            if line.strip().startswith("#"):
                                continue
                            files_with_secrets.append(
                                f"{script.name}:{i} - possible secret"
                            )

        if files_with_secrets:
            pytest.fail(
                f"Possible hardcoded secrets found:\n"
                f"  {chr(10).join('- ' + f for f in files_with_secrets)}\n\n"
                f"Use environment variables instead"
            )


# ============================================================================
# HOOK RUNTIME TESTS
# ============================================================================


@pytest.mark.integration
class TestHookRuntime:
    """Test hooks can execute without crashing."""

    def test_user_prompt_submit_basic_execution(self):
        """Test user-prompt-submit.sh executes with basic input."""
        script = HOOKS_DIR / "user-prompt-submit.sh"

        if not script.exists():
            pytest.skip("user-prompt-submit.sh not found")

        import json

        hook_input = json.dumps({"prompt": "hello world"})

        result = subprocess.run(
            [str(script)],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "ENABLE_AI_AGENT_SELECTION": "false",
            },
        )

        # Should not crash (exit 0 or 2 for block)
        assert result.returncode in [0, 2], (
            f"Hook crashed with exit code {result.returncode}:\n"
            f"stderr: {result.stderr}"
        )

    def test_pre_tool_use_basic_execution(self):
        """Test pre-tool-use-quality.sh executes with basic input."""
        script = HOOKS_DIR / "pre-tool-use-quality.sh"

        if not script.exists():
            pytest.skip("pre-tool-use-quality.sh not found")

        import json

        hook_input = json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/test.txt"},
            }
        )

        result = subprocess.run(
            [str(script)],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should not crash
        assert result.returncode in [0, 2], (
            f"Hook crashed with exit code {result.returncode}:\n"
            f"stderr: {result.stderr}"
        )

    def test_post_tool_use_basic_execution(self):
        """Test post-tool-use-quality.sh executes with basic input."""
        script = HOOKS_DIR / "post-tool-use-quality.sh"

        if not script.exists():
            pytest.skip("post-tool-use-quality.sh not found")

        import json

        hook_input = json.dumps(
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/tmp/test.txt"},
                "tool_response": {"content": "test content"},
            }
        )

        result = subprocess.run(
            [str(script)],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Should not crash
        assert result.returncode in [0, 2], (
            f"Hook crashed with exit code {result.returncode}:\n"
            f"stderr: {result.stderr}"
        )


# ============================================================================
# LIB DIRECTORY STRUCTURE TESTS
# ============================================================================


@pytest.mark.unit
class TestLibDirectoryStructure:
    """Test lib directory has expected structure."""

    def test_lib_init_exists(self):
        """Verify lib/__init__.py exists."""
        init_file = LIB_DIR / "__init__.py"
        assert (
            init_file.exists()
        ), f"Missing lib/__init__.py - Python won't treat lib as a package"

    def test_core_modules_exist(self, core_python_modules):
        """Verify core Python modules exist."""
        missing = []

        for module in core_python_modules:
            if not module.exists():
                missing.append(module.name)

        if missing:
            pytest.fail(
                f"Missing core modules in lib/:\n"
                f"  {chr(10).join('- ' + m for m in missing)}"
            )

    def test_no_circular_imports(self):
        """Test for circular imports in core modules."""
        # Simple test: try importing all core modules in sequence
        lib_path = str(LIB_DIR)
        if lib_path not in sys.path:
            sys.path.insert(0, lib_path)

        core_modules = [
            "correlation_manager",
            "metadata_extractor",
            "agent_detector",
        ]

        import_errors: List[str] = []

        for module_name in core_modules:
            try:
                # Clear from cache to test fresh import
                if module_name in sys.modules:
                    del sys.modules[module_name]

                __import__(module_name)
            except ImportError as e:
                if "circular" in str(e).lower():
                    import_errors.append(f"{module_name}: circular import detected")
                else:
                    # Other import errors might be missing deps, not circular
                    pass
            except RecursionError:
                import_errors.append(f"{module_name}: circular import (recursion)")

        if import_errors:
            pytest.fail(
                f"Circular imports detected:\n"
                f"  {chr(10).join('- ' + e for e in import_errors)}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

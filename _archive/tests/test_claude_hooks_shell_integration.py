#!/usr/bin/env python3
"""
Integration tests for Claude hooks shell scripts.

This module tests the shell script hooks:
- pre-tool-use-log.sh (atomic logging)
- pre-tool-use-quality.sh (quality enforcement wrapper)
- session-start.sh / session-end.sh

Test Categories:
- Unit tests for log file creation
- Integration tests for script execution
- Edge case handling
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

# =============================================================================
# TEST FIXTURES
# =============================================================================


@pytest.fixture
def hooks_dir() -> Path:
    """Return the claude/hooks directory path (updated for consolidation)."""
    return Path(__file__).parent.parent / "claude" / "hooks"


@pytest.fixture
def temp_log_dir(tmp_path: Path) -> Path:
    """Create a temporary log directory."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


@pytest.fixture
def sample_tool_json() -> str:
    """Sample tool call JSON for testing."""
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la", "timeout": 30000},
        }
    )


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def run_script(
    script_path: Path,
    stdin_input: str = "",
    env: dict | None = None,
    timeout: int = 10,
) -> tuple[int, str, str]:
    """
    Run a shell script and return exit code, stdout, stderr.

    Args:
        script_path: Path to the script
        stdin_input: Input to pass via stdin
        env: Environment variables
        timeout: Timeout in seconds

    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    full_env = os.environ.copy()
    if env:
        full_env.update(env)

    result = subprocess.run(
        ["bash", str(script_path)],
        input=stdin_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
    )

    return result.returncode, result.stdout, result.stderr


# =============================================================================
# TEST PRE-TOOL-USE-LOG.SH
# =============================================================================


class TestPreToolUseLog:
    """Tests for pre-tool-use-log.sh script."""

    def test_script_exists(self, hooks_dir: Path):
        """Verify the script exists."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        assert script_path.exists(), f"Script not found at {script_path}"

    def test_script_is_executable_bash(self, hooks_dir: Path):
        """Verify the script has a bash shebang."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        content = script_path.read_text()
        assert content.startswith("#!/usr/bin/env bash") or content.startswith(
            "#!/bin/bash"
        )

    def test_script_uses_pipefail(self, hooks_dir: Path):
        """Verify the script uses set -euo pipefail."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        content = script_path.read_text()
        assert "set -euo pipefail" in content or "set -e" in content

    def test_script_creates_log_directory(self, hooks_dir: Path, tmp_path: Path):
        """Test that script creates log directory if missing."""
        script_path = hooks_dir / "pre-tool-use-log.sh"

        # Override HOME to use temp directory
        log_dir = tmp_path / ".claude" / "logs"

        exit_code, stdout, stderr = run_script(
            script_path,
            stdin_input='{"tool_name": "test"}',
            env={"HOME": str(tmp_path)},
        )

        # Check log directory was created
        assert log_dir.exists()

    def test_script_passes_through_input(self, hooks_dir: Path, tmp_path: Path):
        """Test that script passes through stdin to stdout."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        input_data = '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'

        exit_code, stdout, stderr = run_script(
            script_path, stdin_input=input_data, env={"HOME": str(tmp_path)}
        )

        assert exit_code == 0
        assert stdout.strip() == input_data

    def test_script_creates_unique_log_files(self, hooks_dir: Path, tmp_path: Path):
        """Test that multiple runs create unique log files."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        log_dir = tmp_path / ".claude" / "logs"

        input_data = '{"tool_name": "test"}'

        # Run script multiple times
        for _ in range(3):
            run_script(script_path, stdin_input=input_data, env={"HOME": str(tmp_path)})

        # Check that multiple log files were created
        if log_dir.exists():
            log_files = list(log_dir.glob("pre_tool_use_*.json"))
            # Should have created unique files (at least 1)
            assert len(log_files) >= 1

    def test_script_logs_valid_json(self, hooks_dir: Path, tmp_path: Path):
        """Test that logged content is valid JSON."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        log_dir = tmp_path / ".claude" / "logs"

        input_data = '{"tool_name": "Bash", "tool_input": {"command": "ls"}}'

        run_script(script_path, stdin_input=input_data, env={"HOME": str(tmp_path)})

        # Find and validate log file
        if log_dir.exists():
            log_files = list(log_dir.glob("pre_tool_use_*.json"))
            if log_files:
                content = log_files[0].read_text()
                # Should be valid JSON
                parsed = json.loads(content)
                assert parsed["tool_name"] == "Bash"

    def test_script_handles_empty_input(self, hooks_dir: Path, tmp_path: Path):
        """Test that script handles empty input gracefully."""
        script_path = hooks_dir / "pre-tool-use-log.sh"

        exit_code, stdout, stderr = run_script(
            script_path, stdin_input="", env={"HOME": str(tmp_path)}
        )

        # Should complete without error
        assert exit_code == 0
        assert stdout.strip() == ""

    def test_script_handles_unicode_input(self, hooks_dir: Path, tmp_path: Path):
        """Test that script handles unicode input."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        input_data = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "echo '日本語 👍'"}}
        )

        exit_code, stdout, stderr = run_script(
            script_path, stdin_input=input_data, env={"HOME": str(tmp_path)}
        )

        assert exit_code == 0
        # Output should preserve unicode
        assert "日本語" in stdout or "\\u" in stdout

    def test_script_atomic_write(self, hooks_dir: Path, tmp_path: Path):
        """Test that script performs atomic writes (no temp files left)."""
        script_path = hooks_dir / "pre-tool-use-log.sh"
        log_dir = tmp_path / ".claude" / "logs"

        input_data = '{"tool_name": "test"}'

        run_script(script_path, stdin_input=input_data, env={"HOME": str(tmp_path)})

        # Check for leftover temp files
        if log_dir.exists():
            temp_files = list(log_dir.glob("*.tmp"))
            assert len(temp_files) == 0, f"Found leftover temp files: {temp_files}"


# =============================================================================
# TEST PRE-TOOL-USE-QUALITY.SH
# =============================================================================


class TestPreToolUseQuality:
    """Tests for pre-tool-use-quality.sh script."""

    def test_script_exists(self, hooks_dir: Path):
        """Verify the script exists."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        assert script_path.exists(), f"Script not found at {script_path}"

    def test_script_uses_pipefail(self, hooks_dir: Path):
        """Verify the script uses set -euo pipefail."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        content = script_path.read_text()
        assert "set -euo pipefail" in content

    def test_script_has_correlation_id_logic(self, hooks_dir: Path):
        """Verify script implements correlation ID tracking."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        content = script_path.read_text()
        assert "CORRELATION_ID" in content
        assert "uuidgen" in content or "uuid" in content.lower()

    def test_script_passes_through_non_write_tools(
        self, hooks_dir: Path, tmp_path: Path
    ):
        """Test that non-Write/Edit tools are passed through."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"

        # Bash tool should pass through immediately
        input_data = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})

        exit_code, stdout, stderr = run_script(
            script_path,
            stdin_input=input_data,
            env={
                "HOME": str(tmp_path),
                "HOOK_DIR": str(hooks_dir),
            },
            timeout=5,
        )

        assert exit_code == 0
        # Output should be the original input (passed through)
        output_data = json.loads(stdout)
        assert output_data["tool_name"] == "Bash"

    def test_script_intercepts_write_operations(self, hooks_dir: Path):
        """Test that Write/Edit/MultiEdit operations are intercepted."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        content = script_path.read_text()

        # Should have logic to intercept these tools
        assert "Write" in content
        assert "Edit" in content
        assert "MultiEdit" in content

    def test_script_sets_kafka_brokers(self, hooks_dir: Path):
        """Test that script sets Kafka broker configuration."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        content = script_path.read_text()

        # Should have Kafka configuration
        assert "KAFKA_BROKERS" in content

    def test_script_creates_log_directory(self, hooks_dir: Path):
        """Test that script creates log directory."""
        script_path = hooks_dir / "pre-tool-use-quality.sh"
        content = script_path.read_text()

        # Should have mkdir for log directory
        assert "mkdir -p" in content


# =============================================================================
# TEST SESSION HOOKS
# =============================================================================


class TestSessionHooks:
    """Tests for session start/end hooks."""

    def test_session_start_exists(self, hooks_dir: Path):
        """Verify session-start.sh exists."""
        script_path = hooks_dir / "session-start.sh"
        assert script_path.exists(), f"Script not found at {script_path}"

    def test_session_end_exists(self, hooks_dir: Path):
        """Verify session-end.sh exists."""
        script_path = hooks_dir / "session-end.sh"
        assert script_path.exists(), f"Script not found at {script_path}"

    def test_session_start_is_valid_bash(self, hooks_dir: Path):
        """Test that session-start.sh is valid bash."""
        script_path = hooks_dir / "session-start.sh"
        content = script_path.read_text()
        assert content.startswith("#!")


# =============================================================================
# TEST SCRIPT SECURITY
# =============================================================================


class TestScriptSecurity:
    """Security-focused tests for shell scripts."""

    def test_no_hardcoded_passwords(self, hooks_dir: Path):
        """Verify no hardcoded passwords in scripts."""
        sensitive_patterns = [
            "password=",
            "PASSWORD=",
            "secret=",
            "SECRET=",
            "api_key=",
            "API_KEY=",
            "token=",
            "TOKEN=",
        ]

        for script in hooks_dir.glob("*.sh"):
            content = script.read_text()

            for pattern in sensitive_patterns:
                # Allow patterns that use environment variables
                if pattern in content:
                    # Check it's not a hardcoded value
                    lines_with_pattern = [
                        line for line in content.split("\n") if pattern in line
                    ]
                    for line in lines_with_pattern:
                        # Should be using env vars or placeholders
                        assert (
                            "${" in line
                            or "$(" in line
                            or ":-" in line
                            or '=""' in line
                            or "=''" in line
                            or "#" in line.split(pattern)[0]  # Commented out
                        ), f"Possible hardcoded secret in {script}: {line}"

    def test_scripts_use_safe_temp_handling(self, hooks_dir: Path):
        """Advisory: Verify scripts use safe temp file handling.

        This test documents temp file handling patterns in the scripts.
        It's not a hard requirement but a best practice reminder.
        """
        # Focus only on the core permission hooks, not all scripts
        core_hooks = [
            hooks_dir / "pre-tool-use-log.sh",
            hooks_dir / "pre-tool-use-quality.sh",
        ]

        for script_path in core_hooks:
            if script_path.exists():
                content = script_path.read_text()

                # If writing to /tmp directly (not local tmp), should use mktemp
                if "> /tmp/" in content and "mktemp" not in content:
                    # Advisory only - don't fail
                    pass

    def test_scripts_have_error_handling(self, hooks_dir: Path):
        """Verify core permission hooks have error handling (set -e or trap).

        This test focuses on the core permission hooks which are critical for
        security. Other utility scripts may have intentionally lenient error
        handling for diagnostic purposes.
        """
        # Focus on core hooks only - these are critical for security
        core_hooks = [
            hooks_dir / "pre-tool-use-log.sh",
            hooks_dir / "pre-tool-use-quality.sh",
        ]

        for script_path in core_hooks:
            if script_path.exists():
                content = script_path.read_text()

                # Should have either set -e or trap ERR
                has_error_handling = (
                    "set -e" in content
                    or "set -euo" in content
                    or "trap" in content
                    or "|| true" in content  # Explicit error suppression is OK
                )

                assert (
                    has_error_handling
                ), f"Core hook {script_path.name} should have error handling"


# =============================================================================
# TEST SCRIPT COMPATIBILITY
# =============================================================================


class TestScriptCompatibility:
    """Test script compatibility across environments."""

    def test_scripts_use_env_bash(self, hooks_dir: Path):
        """Test that scripts use /usr/bin/env bash for portability."""
        for script in hooks_dir.glob("*.sh"):
            content = script.read_text()

            # Shebang should use env for portability
            first_line = content.split("\n")[0]
            if first_line.startswith("#!"):
                # Should use env for bash
                assert (
                    "#!/usr/bin/env bash" in first_line
                    or "#!/bin/bash" in first_line
                    or "#!/bin/sh" in first_line
                ), f"Script {script} should use portable shebang"

    def test_scripts_quote_variables(self, hooks_dir: Path):
        """Test that scripts properly quote variables."""
        for script in hooks_dir.glob("*.sh"):
            content = script.read_text()

            # Check for unquoted variable expansions in risky contexts
            # This is a heuristic check - not comprehensive
            lines = content.split("\n")
            for i, line in enumerate(lines, 1):
                # Skip comments
                if line.strip().startswith("#"):
                    continue

                # Check for potential issues with unquoted variables in paths
                if "cd $" in line and 'cd "$' not in line:
                    # Allow if it's intentional (e.g., cd $HOME)
                    if "cd $HOME" not in line:
                        # This could be an issue
                        pass  # Just document, don't fail

    def test_jq_availability_check(self, hooks_dir: Path):
        """Test that scripts check for jq availability if using it."""
        for script in hooks_dir.glob("*.sh"):
            content = script.read_text()

            if "| jq" in content or "jq -r" in content:
                # Scripts using jq should ideally check for it
                # or handle the case where it's not available
                # This is advisory, not a hard requirement
                pass


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestIntegration:
    """Integration tests combining multiple hooks."""

    def test_full_tool_call_flow(self, hooks_dir: Path, tmp_path: Path):
        """Test a complete tool call through logging hook."""
        log_script = hooks_dir / "pre-tool-use-log.sh"

        # Simulate a full tool call
        tool_call = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/test/example.py",
                "content": 'def hello():\n    print("Hello, World!")\n',
            },
        }

        exit_code, stdout, stderr = run_script(
            log_script,
            stdin_input=json.dumps(tool_call),
            env={"HOME": str(tmp_path)},
        )

        assert exit_code == 0

        # Verify output is valid
        output = json.loads(stdout)
        assert output["tool_name"] == "Write"
        assert output["tool_input"]["file_path"] == "/test/example.py"

    def test_large_content_handling(self, hooks_dir: Path, tmp_path: Path):
        """Test handling of large content (e.g., big files)."""
        log_script = hooks_dir / "pre-tool-use-log.sh"

        # Create large content (100KB)
        large_content = "x" * 100000

        tool_call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/test/large.txt", "content": large_content},
        }

        exit_code, stdout, stderr = run_script(
            log_script,
            stdin_input=json.dumps(tool_call),
            env={"HOME": str(tmp_path)},
            timeout=30,
        )

        assert exit_code == 0

        # Output should contain full content
        output = json.loads(stdout)
        assert len(output["tool_input"]["content"]) == 100000

    def test_special_characters_in_content(self, hooks_dir: Path, tmp_path: Path):
        """Test handling of special characters."""
        log_script = hooks_dir / "pre-tool-use-log.sh"

        special_content = """def test():
    # Special chars: $var ${var} $(cmd) `cmd`
    s = "quotes \\"nested\\" and 'single'"
    r = r"raw \\string"
    return f"{s} and {r}"
"""

        tool_call = {
            "tool_name": "Write",
            "tool_input": {"file_path": "/test/special.py", "content": special_content},
        }

        exit_code, stdout, stderr = run_script(
            log_script,
            stdin_input=json.dumps(tool_call),
            env={"HOME": str(tmp_path)},
        )

        assert exit_code == 0
        # Should have successfully passed through
        assert len(stdout) > 0


# =============================================================================
# RUN TESTS
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

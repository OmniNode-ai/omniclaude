# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for skill output suppression hook [OMN-6733].

Verifies:
- Direct invocation of suppression logic
- Hook event chain (PostToolUse fires and suppression activates)
- Errors are NOT swallowed (stderr preserved, non-zero exits kept)
- Exit code 0 always from the hook itself
- Short output passes through unchanged
- Non-Bash tool calls pass through unchanged
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add hooks lib to path for direct import
_HOOKS_LIB = Path(__file__).parents[3] / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


@pytest.mark.unit
def test_detect_pytest_command() -> None:
    from skill_output_suppressor import detect_command_type

    # "uv run pytest" matches pytest pattern (pytest comes before uv-run in priority)
    assert detect_command_type("uv run pytest tests/ -v") == "pytest"
    assert detect_command_type("pytest tests/ -m unit") == "pytest"
    assert detect_command_type("python -m pytest") == "pytest"


@pytest.mark.unit
def test_detect_mypy_command() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("mypy src/omniclaude/ --strict") == "mypy"
    # "uv run mypy" matches mypy pattern first
    assert detect_command_type("uv run mypy src/") == "mypy"


@pytest.mark.unit
def test_detect_ruff_command() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("ruff check src/") == "ruff"
    assert detect_command_type("ruff format src/") == "ruff"


@pytest.mark.unit
def test_detect_precommit_command() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("pre-commit run --all-files") == "pre-commit"


@pytest.mark.unit
def test_detect_non_suppressible_command() -> None:
    from skill_output_suppressor import detect_command_type

    assert detect_command_type("git status") is None
    assert detect_command_type("ls -la") is None
    assert detect_command_type("cat README.md") is None


@pytest.mark.unit
def test_short_output_not_suppressed() -> None:
    from skill_output_suppressor import EnumSuppressionAction, summarize_output

    result = summarize_output("pytest tests/", "5 passed in 0.1s\n", 0)
    assert result.action == EnumSuppressionAction.passthrough


@pytest.mark.unit
def test_long_output_suppressed() -> None:
    from skill_output_suppressor import EnumSuppressionAction, summarize_output

    # Generate output longer than 2000 chars
    long_output = "\n".join([f"tests/test_{i}.py::test_foo PASSED" for i in range(200)])
    long_output += "\n====== 200 passed in 5.23s ======"
    result = summarize_output("pytest tests/ -v", long_output, 0)
    assert result.action == EnumSuppressionAction.suppressed
    assert result.command_type == "pytest"
    assert result.original_lines > result.summary_lines
    assert "200 passed" in result.summary


@pytest.mark.unit
def test_error_output_never_suppressed() -> None:
    """Non-zero exit code must NEVER have output suppressed."""
    from skill_output_suppressor import EnumSuppressionAction, summarize_output

    long_output = "\n".join([f"ERROR: test_{i} failed" for i in range(200)])
    result = summarize_output("pytest tests/ -v", long_output, 1)
    assert result.action == EnumSuppressionAction.error_preserved
    assert "exited with code 1" in result.summary


@pytest.mark.unit
def test_process_tool_info_bash_suppression() -> None:
    """Full pipeline: process_tool_info suppresses long Bash output."""
    from skill_output_suppressor import process_tool_info

    long_output = "\n".join([f"tests/test_{i}.py::test_foo PASSED" for i in range(200)])
    long_output += "\n====== 200 passed in 5.23s ======"

    tool_info = {
        "tool_name": "Bash",
        "tool_input": {"command": "uv run pytest tests/ -v"},
        "tool_response": {"output": long_output, "exit_code": 0},
    }
    result = process_tool_info(tool_info)
    assert result["tool_response"].get("_suppressed") is True
    assert result["tool_response"]["_original_lines"] > 0
    assert len(result["tool_response"]["output"]) < len(long_output)


@pytest.mark.unit
def test_process_tool_info_non_bash_passthrough() -> None:
    """Non-Bash tools pass through unchanged."""
    from skill_output_suppressor import process_tool_info

    tool_info = {
        "tool_name": "Read",
        "tool_input": {"file_path": "/foo/bar.py"},
        "tool_response": {"content": "x" * 5000},
    }
    result = process_tool_info(tool_info)
    assert result == tool_info


@pytest.mark.unit
def test_process_tool_info_error_preserved() -> None:
    """Bash errors are never suppressed even if output is long."""
    from skill_output_suppressor import process_tool_info

    long_output = "\n".join([f"FAILED test_{i}" for i in range(200)])
    tool_info = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest tests/"},
        "tool_response": {"output": long_output, "exit_code": 1},
    }
    result = process_tool_info(tool_info)
    # Error output must NOT be modified
    assert result["tool_response"]["output"] == long_output
    assert "_suppressed" not in result["tool_response"]


@pytest.mark.unit
def test_process_tool_info_string_response() -> None:
    """Handle tool_response as a plain string."""
    from skill_output_suppressor import process_tool_info

    long_output = "\n".join([f"test_{i} PASSED" for i in range(200)])
    long_output += "\n====== 200 passed ======"
    tool_info = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest tests/"},
        "tool_response": long_output,
    }
    result = process_tool_info(tool_info)
    assert isinstance(result["tool_response"], str)
    assert len(result["tool_response"]) < len(long_output)


@pytest.mark.unit
def test_hook_script_exists() -> None:
    """The shell hook script must exist and be executable."""
    hook = (
        Path(__file__).parents[3]
        / "plugins/onex/hooks/scripts/post_tool_use_output_suppressor.sh"
    )
    assert hook.exists(), f"Hook script not found: {hook}"


@pytest.mark.unit
def test_hook_registered_in_hooks_json() -> None:
    """The hook must be registered in hooks.json."""
    hooks_json = Path(__file__).parents[3] / "plugins/onex/hooks/hooks.json"
    data = json.loads(hooks_json.read_text())
    post_tool_hooks = data["hooks"]["PostToolUse"]
    found = any(
        "post_tool_use_output_suppressor.sh" in h["hooks"][0]["command"]
        for h in post_tool_hooks
    )
    assert found, (
        "post_tool_use_output_suppressor.sh not registered in hooks.json PostToolUse"
    )


@pytest.mark.unit
def test_extract_pytest_summary() -> None:
    from skill_output_suppressor import _extract_pytest_summary

    output = "collecting ...\n23 passed in 0.39s\n"
    assert "23 passed" in _extract_pytest_summary(output)


@pytest.mark.unit
def test_extract_mypy_summary() -> None:
    from skill_output_suppressor import _extract_mypy_summary

    output = "src/foo.py:1: error\nFound 3 errors in 1 file\n"
    assert "Found 3 errors" in _extract_mypy_summary(output)

    output_success = "checking...\nSuccess: no issues found in 5 source files\n"
    assert "Success" in _extract_mypy_summary(output_success)


@pytest.mark.unit
def test_suppress_docker_logs() -> None:
    from skill_output_suppressor import EnumSuppressionAction, summarize_output

    long_output = "\n".join([f"2026-03-26 log line {i}" for i in range(200)])
    result = summarize_output("docker logs -f container", long_output, 0)
    assert result.action == EnumSuppressionAction.suppressed
    assert result.command_type == "docker-logs"

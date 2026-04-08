# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for model_router_hook (OMN-7810).

Tests advisory-mode delegation classification:
- Simple Bash commands → advisory (delegate suggestion)
- Complex Bash commands → pass through (Opus-appropriate)
- Read/Grep/Glob → advisory (always simple)
- Orchestration tools → pass through
- Disabled config → pass through
- Enforce mode → hard block for simple tasks
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# The module lives in plugins/onex/hooks/lib/ — add it to sys.path for import
_HOOKS_LIB = str(
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
)
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from model_router_hook import classify_complexity, run_model_router

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_json(tool_name: str, tool_input: dict | None = None) -> str:
    return json.dumps({"tool_name": tool_name, "tool_input": tool_input or {}})


def _bash(command: str) -> str:
    return _tool_json("Bash", {"command": command})


def _edit(file_path: str = "/proj/file.py", new_string: str = "x") -> str:
    return _tool_json(
        "Edit", {"file_path": file_path, "old_string": "y", "new_string": new_string}
    )


# ---------------------------------------------------------------------------
# classify_complexity unit tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_simple_bash_is_low_complexity() -> None:
    assert classify_complexity("Bash", {"command": "git status"}) < 0.5


@pytest.mark.unit
def test_complex_bash_is_high_complexity() -> None:
    assert (
        classify_complexity(
            "Bash", {"command": "docker compose up -d && uv run pytest tests/"}
        )
        >= 0.7
    )


@pytest.mark.unit
def test_read_is_always_low() -> None:
    assert classify_complexity("Read", {"file_path": "/complex/handler_foo.py"}) < 0.5


@pytest.mark.unit
def test_edit_architecture_file_is_high() -> None:
    assert classify_complexity("Edit", {"file_path": "/src/handler_build.py"}) >= 0.7


@pytest.mark.unit
def test_edit_small_change_is_low() -> None:
    assert (
        classify_complexity("Edit", {"file_path": "/proj/readme.md", "new_string": "x"})
        < 0.5
    )


# ---------------------------------------------------------------------------
# run_model_router integration tests
# ---------------------------------------------------------------------------

_ADVISORY_CONFIG = {
    "enabled": True,
    "mode": "advisory",
    "implementation_tools": ["Bash", "Read", "Edit", "Write", "Grep", "Glob"],
    "orchestration_tools": ["SendMessage", "Agent", "TaskCreate"],
    "delegation_threshold": 0.7,
    "delegation_model": "glm-4.7-flash",
}

_ENFORCE_CONFIG = {**_ADVISORY_CONFIG, "mode": "enforce"}

_DISABLED_CONFIG = {**_ADVISORY_CONFIG, "enabled": False}


@pytest.mark.unit
def test_advisory_mode_simple_bash_passes_with_stderr(tmp_path: Path) -> None:
    """Simple Bash in advisory mode: exit 0 (pass through)."""
    with patch("model_router_hook._load_config", return_value=_ADVISORY_CONFIG):
        exit_code, output = run_model_router(_bash("ls -la"))

    assert exit_code == 0
    # Output should be the original JSON (pass through)
    parsed = json.loads(output)
    assert parsed["tool_name"] == "Bash"


@pytest.mark.unit
def test_advisory_mode_complex_bash_passes() -> None:
    """Complex Bash in advisory mode: exit 0 (no advisory needed)."""
    with patch("model_router_hook._load_config", return_value=_ADVISORY_CONFIG):
        exit_code, output = run_model_router(
            _bash("docker compose up -d && uv run pytest tests/ -v")
        )

    assert exit_code == 0


@pytest.mark.unit
def test_orchestration_tool_always_passes() -> None:
    """Orchestration tools always pass through regardless of config."""
    with patch("model_router_hook._load_config", return_value=_ADVISORY_CONFIG):
        exit_code, output = run_model_router(
            _tool_json("SendMessage", {"to": "team-lead", "message": "hello"})
        )

    assert exit_code == 0


@pytest.mark.unit
def test_enforce_mode_blocks_simple_bash() -> None:
    """Simple Bash in enforce mode: exit 2 (hard block)."""
    with patch("model_router_hook._load_config", return_value=_ENFORCE_CONFIG):
        exit_code, output = run_model_router(_bash("git status"))

    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"
    assert "glm-4.7-flash" in result["reason"]


@pytest.mark.unit
def test_enforce_mode_allows_complex_bash() -> None:
    """Complex Bash in enforce mode: exit 0 (complex enough for Opus)."""
    with patch("model_router_hook._load_config", return_value=_ENFORCE_CONFIG):
        exit_code, output = run_model_router(
            _bash("docker compose up -d && uv run pytest tests/ -v")
        )

    assert exit_code == 0


@pytest.mark.unit
def test_disabled_config_passes_everything() -> None:
    """When disabled, everything passes through."""
    with patch("model_router_hook._load_config", return_value=_DISABLED_CONFIG):
        exit_code, output = run_model_router(_bash("ls"))

    assert exit_code == 0


@pytest.mark.unit
def test_invalid_json_fails_open() -> None:
    """Invalid JSON input should fail open."""
    exit_code, output = run_model_router("not-json")
    assert exit_code == 0

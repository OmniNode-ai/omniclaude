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
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# The module lives in plugins/onex/hooks/lib/ — add it to sys.path for import
_HOOKS_LIB = str(
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
)
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)

from model_router_hook import _load_config, classify_complexity, run_model_router

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "onex"
_WRAPPER = _PLUGIN_ROOT / "hooks" / "scripts" / "pre_tool_use_model_router.sh"

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


@pytest.mark.unit
def test_shipped_mode_matches_module_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The installed config must preserve the module's advisory default."""
    config = _load_config(str(_PLUGIN_ROOT))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PLUGIN_ROOT))
    payload = _edit("README.md")
    shipped = run_model_router(payload)
    with patch(
        "model_router_hook._load_config",
        return_value={key: value for key, value in config.items() if key != "mode"},
    ):
        default = run_model_router(payload)
    assert shipped == default == (0, payload)
    assert config["mode"] == "advisory"


@pytest.mark.unit
def test_shipped_config_excludes_read_only_tools() -> None:
    config = _load_config(str(_PLUGIN_ROOT))
    assert {"Read", "Grep", "Glob"}.isdisjoint(config["implementation_tools"])
    assert {"Bash", "Edit", "Write"} <= set(config["implementation_tools"])


def _run_wrapper(
    payload: str, plugin_root: Path, tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "LOG_FILE": str(tmp_path / "router.log"),
        "_ERROR_GUARD_LOG_DIR": str(tmp_path / "errors"),
    }
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        cwd=_REPO_ROOT,
        timeout=30,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize("tool_name", ["Read", "Grep", "Glob"])
def test_shipped_wrapper_allows_read_only_tools(tool_name: str, tmp_path: Path) -> None:
    payload = _tool_json(tool_name, {"file_path": "README.md", "pattern": "README"})
    result = _run_wrapper(payload, _PLUGIN_ROOT, tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == payload


@pytest.mark.unit
def test_wrapper_explicit_enforcement_controls(tmp_path: Path) -> None:
    """Exercise real Python verdicts through the absolute-path shell entrypoint."""
    plugin_root = tmp_path / "plugin"
    hooks = plugin_root / "hooks"
    config_dir = hooks / "config"
    config_dir.mkdir(parents=True)
    for directory in ("scripts", "lib"):
        (hooks / directory).symlink_to(
            _PLUGIN_ROOT / "hooks" / directory, target_is_directory=True
        )
    config = _load_config(str(_PLUGIN_ROOT))
    config["mode"] = "enforce"
    (config_dir / "model_router_hook.yaml").write_text(yaml.safe_dump(config))

    refused = _run_wrapper(_edit("README.md"), plugin_root, tmp_path)
    assert refused.returncode == 2, refused.stderr
    assert json.loads(refused.stdout)["decision"] == "block"
    log = (tmp_path / "router.log").read_text()
    assert "BLOCKED Edit: delegation required" in log
    assert "failing open" not in log

    payload = _tool_json("Read", {"file_path": "README.md"})
    allowed = _run_wrapper(payload, plugin_root, tmp_path)
    assert allowed.returncode == 0, allowed.stderr
    assert allowed.stdout.strip() == payload

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for Stop-phase changed-file quality gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PY_GATE = _REPO_ROOT / "plugins/onex/hooks/scripts/stop_quality_gate.py"
_SH_GATE = _REPO_ROOT / "plugins/onex/hooks/scripts/stop_quality_gate.sh"
_STOP_JSON = json.dumps({"session_id": "sess-stop-quality", "status": "complete"})


def _run(
    command: list[str], cwd: Path, **kwargs: object
) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
        **kwargs,
    )


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src/pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nmarkers = ['unit']\n"
    )
    (repo / "src/pkg/example.py").write_text("def ok() -> int:\n    return 1\n")
    (repo / "tests/test_example.py").write_text(
        "import pytest\n\n\n@pytest.mark.unit\ndef test_ok():\n    assert True\n"
    )
    _run(["git", "init"], repo)
    _run(["git", "config", "user.email", "test@example.com"], repo)
    _run(["git", "config", "user.name", "Test User"], repo)
    _run(["git", "add", "."], repo)
    _run(["git", "commit", "-m", "initial"], repo)
    return repo


def _fake_uv(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(
        """#!/usr/bin/env python3
import os
import pathlib
import sys

log = pathlib.Path(os.environ["FAKE_UV_LOG"])
log.write_text(log.read_text() + " ".join(sys.argv[1:]) + "\\n" if log.exists() else " ".join(sys.argv[1:]) + "\\n")
fail = os.environ.get("FAKE_UV_FAIL", "")
tool = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "run" else ""
if fail == tool:
    print(f"{tool} failure", file=sys.stderr)
    sys.exit(1)
sys.exit(0)
"""
    )
    uv.chmod(0o755)
    return bin_dir, log_path


def _gate_env(tmp_path: Path, repo: Path, *, fail: str = "") -> dict[str, str]:
    bin_dir, log_path = _fake_uv(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["FAKE_UV_LOG"] = str(log_path)
    env["FAKE_UV_FAIL"] = fail
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_PLUGIN_ROOT"] = str(_REPO_ROOT / "plugins/onex")
    env["PLUGIN_PYTHON_BIN"] = sys.executable
    env["ONEX_STATE_DIR"] = str(tmp_path / "state")
    env["HOME"] = str(tmp_path)
    env["OMNICLAUDE_MODE"] = "full"
    return env


def _run_python_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return _run(
        [sys.executable, str(_PY_GATE), "--project-root", str(repo)],
        repo,
        env=env,
    )


def _run_shell_gate(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return _run(
        ["bash", str(_SH_GATE)],
        repo,
        input=_STOP_JSON,
        env=env,
    )


@pytest.mark.unit
def test_no_changed_files_passes(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = _gate_env(tmp_path, repo)
    result = _run_python_gate(repo, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["reason"] == "no changed Python files"
    assert not Path(env["FAKE_UV_LOG"]).exists()


@pytest.mark.unit
def test_ruff_violation_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "src/pkg/example.py").write_text(
        "import os\n\ndef ok() -> int:\n    return 1\n"
    )
    _run(["git", "add", "src/pkg/example.py"], repo)
    env = _gate_env(tmp_path, repo, fail="ruff")
    result = _run_python_gate(repo, env)
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "ruff exited 1" in payload["reason"]


@pytest.mark.unit
def test_mypy_violation_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "src/pkg/example.py").write_text("def ok() -> str:\n    return 1\n")
    _run(["git", "add", "src/pkg/example.py"], repo)
    env = _gate_env(tmp_path, repo, fail="mypy")
    result = _run_python_gate(repo, env)
    assert result.returncode == 2
    assert "mypy exited 1" in json.loads(result.stdout)["reason"]


@pytest.mark.unit
def test_test_file_failure_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "src/pkg/example.py").write_text("def ok() -> int:\n    return 2\n")
    _run(["git", "add", "src/pkg/example.py"], repo)
    env = _gate_env(tmp_path, repo, fail="pytest")
    result = _run_python_gate(repo, env)
    assert result.returncode == 2
    assert "pytest exited 1" in json.loads(result.stdout)["reason"]


@pytest.mark.unit
def test_hook_enabled_blocks(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "src/pkg/example.py").write_text("import os\n")
    _run(["git", "add", "src/pkg/example.py"], repo)
    env = _gate_env(tmp_path, repo, fail="ruff")
    result = _run_shell_gate(repo, env)
    assert result.returncode == 2
    assert json.loads(result.stdout)["decision"] == "block"


@pytest.mark.unit
def test_hook_disabled_skips(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    (repo / "src/pkg/example.py").write_text("import os\n")
    _run(["git", "add", "src/pkg/example.py"], repo)
    env = _gate_env(tmp_path, repo, fail="ruff")
    env["ONEX_HOOKS_MASK"] = "0"
    result = _run_shell_gate(repo, env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == json.loads(_STOP_JSON)
    assert not Path(env["FAKE_UV_LOG"]).exists()


@pytest.mark.unit
def test_non_worktree_skips(tmp_path: Path) -> None:
    env = _gate_env(tmp_path, tmp_path)
    result = _run_python_gate(tmp_path, env)
    assert result.returncode == 0
    assert json.loads(result.stdout)["reason"] == "not in git worktree"


@pytest.mark.unit
def test_performance_under_13s(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    env = _gate_env(tmp_path, repo)
    started = time.monotonic()
    result = _run_python_gate(repo, env)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert elapsed < 13

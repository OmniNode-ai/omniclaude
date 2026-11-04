# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22405: the dev runtime mutation check judges on a lab host.

On 2026-11-03 the registered entrypoint refused 79 lab-host calls as "could not judge
this call (exit 1)" with an empty detail. The measured cause on a lab host: in full mode
the hook sources ``common.sh`` with its output discarded, and ``common.sh`` hard-fails
(exit 1, one stderr line) when no plugin venv resolves. A lab host has no
``CLAUDE_PLUGIN_DATA`` venv, no repo ``.venv`` beside the plugin and no
``PLUGIN_PYTHON_BIN``; the interpreter that has ``omnimarket`` is the registry's own
``omnimarket/.venv``. The node therefore never ran.

Each test runs ``pre_tool_use_bash_guards.sh`` as Claude Code does, under the lab-host
environment: full mode, no ``PLUGIN_PYTHON_BIN``, ``OMNI_HOME`` naming a registry.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"

# The recorded lab-host refusal's command shape (FRICTION rows of 2026-11-03): a compose
# project mutation, run on the host.
RECORDED_RECREATE = (
    "docker compose -p omnibase-infra --profile runtime up -d --force-recreate "
    "--no-build --no-deps"
)
RECORDED_PS = "docker compose ps"
RECORDED_UP = "docker compose up -d"


def _registry_venv(registry: Path) -> None:
    """The lab layout: ``<registry>/omnimarket/.venv/bin/python3`` has omnimarket."""
    python = registry / "omnimarket" / ".venv" / "bin" / "python3"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)


def _lab_env(
    tmp_path: Path, *, registry_venv: bool, plugin_python: Path | None = None
) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(
            ("ONEX_", "CLAUDE_", "CODEX_", "GIT_", "COMPOSE_", "PLUGIN_", "PYTHON")
        )
    }
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    if registry_venv:
        _registry_venv(registry)
    env.update(
        OMNI_HOME=str(registry),
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_HOOK_LOG=str(tmp_path / "hooks.log"),
        CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
        CLAUDE_PROJECT_DIR=str(ROOT),
        CLAUDE_CODE_ENTRYPOINT="cli",
        CLAUDECODE="1",
        OMNICLAUDE_MODE="full",
        HOME=str(tmp_path),
        # No repo .venv beside the plugin, as in a plugin cache on a lab host.
        PLUGIN_ROOT=str(tmp_path / "plugin_root"),
    )
    if plugin_python is not None:
        env["PLUGIN_PYTHON_BIN"] = str(plugin_python)
    return env


def _run(command: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    payload = json.dumps(
        {
            "session_id": "fixture-session",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "cwd": str(ROOT),
        }
    )
    return subprocess.run(
        ["bash", str(HOOK)],
        input=payload,
        env=env,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def _grant_ledger(tmp_path: Path) -> Path:
    now = datetime.now(UTC).replace(microsecond=0)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger = tmp_path / "ROLLING_WORK_LEDGER.md"
    ledger.write_text(
        f"{stamp} | OPERATOR-CONSENT | lane=orchestrator | ticket=OMN-21795 | "
        f"grant=compose:omnibase-infra until={until} | APPROVED SCOPE: recreate\n",
        encoding="utf-8",
    )
    return ledger


def _fake_python(tmp_path: Path, stderr_line: str) -> Path:
    python = tmp_path / "bin" / "python3"
    python.parent.mkdir(exist_ok=True)
    python.write_text(
        f"#!/bin/sh\ncat >/dev/null\necho '{stderr_line}' >&2\nexit 1\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return python


def test_dev_runtime_mutation_could_not_judge_lab_host_judges_refusal(
    tmp_path: Path,
) -> None:
    """No resolvable plugin interpreter: the registry's omnimarket venv judges."""
    result = _run(RECORDED_RECREATE, _lab_env(tmp_path, registry_venv=True))
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout.strip().splitlines()[0])
    assert decision["decision"] == "block"
    assert decision["reason"].startswith("BLOCKED (OMN-21795)"), decision["reason"]
    assert "could not judge" not in decision["reason"]
    assert "grant=compose:omnibase-infra" in decision["reason"]


def test_dev_runtime_mutation_could_not_judge_lab_host_admits_under_grant(
    tmp_path: Path,
) -> None:
    env = _lab_env(tmp_path, registry_venv=True)
    env["ONEX_LEDGER_PATH"] = str(_grant_ledger(tmp_path))
    result = _run(RECORDED_RECREATE, env)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "OMN-21795" not in result.stdout + result.stderr


def test_dev_runtime_mutation_could_not_judge_interpreter_without_omnimarket(
    tmp_path: Path,
) -> None:
    """A resolved interpreter that lacks omnimarket falls back to the registry venv."""
    lacking = _fake_python(tmp_path, "No module named 'omnimarket'")
    env = _lab_env(tmp_path, registry_venv=True, plugin_python=lacking)
    result = _run(RECORDED_RECREATE, env)
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout.strip().splitlines()[0])
    assert decision["reason"].startswith("BLOCKED (OMN-21795)"), decision["reason"]


def test_dev_runtime_mutation_refusal_detail_no_interpreter(tmp_path: Path) -> None:
    """Nothing resolves: still refuses, and the detail names why the node never ran."""
    result = _run(RECORDED_RECREATE, _lab_env(tmp_path, registry_venv=False))
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout.strip().splitlines()[0])
    assert decision["decision"] == "block"
    first_line = result.stderr.strip().splitlines()[0]
    # The text before ". Detail:" is what the refusal recorder writes as the FRICTION
    # detail, so the cause rides there, not only in the trailing detail.
    assert "could not judge this call (exit 1): ERROR: onex hooks need a python3" in (
        first_line
    )
    assert "ERROR: onex hooks need a python3" in decision["reason"]


def test_dev_runtime_mutation_refusal_detail_carries_node_stderr_line(
    tmp_path: Path,
) -> None:
    """The node run's first stderr line is in the refusal; the call stays refused."""
    lacking = _fake_python(tmp_path, "boom: first line from the node run")
    env = _lab_env(tmp_path, registry_venv=False, plugin_python=lacking)
    result = _run(RECORDED_RECREATE, env)
    assert result.returncode == 2, (result.stdout, result.stderr)
    first_line = result.stderr.strip().splitlines()[0]
    assert (
        "could not judge this call (exit 1): boom: first line from the node run"
        in first_line
    )
    decision = json.loads(result.stdout.strip().splitlines()[0])
    assert decision["decision"] == "block"


def test_dev_runtime_mutation_lab_judges_ps_and_up(tmp_path: Path) -> None:
    """AC3: `docker compose ps` passes and `docker compose up -d` is judged, not exit 1."""
    env = _lab_env(tmp_path, registry_venv=True)
    passed = _run(RECORDED_PS, env)
    assert passed.returncode == 0, (passed.stdout, passed.stderr)
    judged = _run(RECORDED_UP, env)
    assert "could not judge" not in judged.stdout + judged.stderr, (
        judged.stdout,
        judged.stderr,
    )
    assert judged.returncode in (0, 2), (judged.stdout, judged.stderr)
    # Positive control: the same environment still refuses a protected recreate.
    protected = _run(RECORDED_RECREATE, env)
    assert protected.returncode == 2, (protected.stdout, protected.stderr)

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21795 AC1 and AC3: the registered PreToolUse entrypoint refuses a dev runtime
container recreate, removal or restart outside a deployment or a grant.

Each test runs ``pre_tool_use_bash_guards.sh`` exactly as Claude Code does: the hook
payload on stdin, the caller's environment, exit 2 with the block JSON for a refusal.
The planted commands are the shapes the ledger recorded taking the dev runtime down by
hand, run over ssh from the operator Mac.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"

PLANTED_RESTART = "ssh lab-dev-host 'docker restart omninode-runtime'"
PLANTED_RECREATE = (
    "ssh lab-dev-host 'docker compose -p omnibase-infra --profile runtime "
    "up -d --force-recreate --no-build --no-deps'"
)


def _env(tmp_path: Path, ledger: Path | None = None) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ONEX_", "CLAUDE_", "CODEX_", "GIT_", "COMPOSE_"))
    }
    registry = tmp_path / "registry"
    registry.mkdir(exist_ok=True)
    env.update(
        OMNI_HOME=str(registry),
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_HOOK_LOG=str(tmp_path / "hooks.log"),
        CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
        CLAUDE_PROJECT_DIR=str(ROOT),
        CLAUDE_CODE_ENTRYPOINT="cli",
        CLAUDECODE="1",
        PLUGIN_PYTHON_BIN=sys.executable,
        OMNICLAUDE_MODE="full",
        HOME=str(tmp_path),
    )
    if ledger is not None:
        env["ONEX_LEDGER_PATH"] = str(ledger)
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


@pytest.mark.parametrize("command", [PLANTED_RESTART, PLANTED_RECREATE])
def test_ac1_planted_hand_recreate_is_refused(tmp_path: Path, command: str) -> None:
    result = _run(command, _env(tmp_path))
    assert result.returncode == 2, (result.stdout, result.stderr)
    decision = json.loads(result.stdout.strip().splitlines()[0])
    assert decision["decision"] == "block"
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert decision["reason"].startswith("BLOCKED (OMN-21795)")
    assert "grant=compose:omnibase-infra" in decision["reason"]
    assert "BLOCKED (OMN-21795)" in result.stderr


def test_ac1_live_grant_admits(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC).replace(microsecond=0)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = (now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ledger = tmp_path / "ROLLING_WORK_LEDGER.md"
    ledger.write_text(
        f"{stamp} | OPERATOR-CONSENT | lane=orchestrator | ticket=OMN-21795 | "
        f"grant=compose:omnibase-infra until={until} | APPROVED SCOPE: restart the dev runtime\n",
        encoding="utf-8",
    )
    result = _run(PLANTED_RESTART, _env(tmp_path, ledger))
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "OMN-21795" not in result.stdout


@pytest.mark.parametrize(
    "command",
    [
        "ssh lab-dev-host 'docker ps -a --filter label=com.docker.compose.project=omnibase-infra'",
        "docker compose -p omnibase-infra-fixture-lane restart",
        "git log --oneline -3",
    ],
)
def test_ac3_read_only_and_other_projects_pass(tmp_path: Path, command: str) -> None:
    env = _env(tmp_path)
    result = _run(command, env)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "OMN-21795" not in result.stdout + result.stderr

    # An allow proves selectivity only when the same hook and environment still
    # refuse a protected mutation. An absent guard must not satisfy AC3.
    protected = _run(PLANTED_RESTART, env)
    assert protected.returncode == 2, (protected.stdout, protected.stderr)
    decision = json.loads(protected.stdout.strip().splitlines()[0])
    assert decision["decision"] == "block"
    assert decision["reason"].startswith("BLOCKED (OMN-21795)")
    assert "grant=compose:omnibase-infra" in decision["reason"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18645: exercise the registered admission seam, never a real push/merge."""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard
from omniclaude.nodes.node_git_effect.handlers.handler_git_subprocess import (
    HandlerGitSubprocess,
)
from omniclaude.nodes.node_git_effect.models import GitOperation, ModelGitRequest
from tests.hooks._bash_guard_registration import is_live_on_bash_matcher

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_shared_tree_git_guard.sh"
CLAIM = "2026-10-01T00:00:00Z | CLAIM | lane=worker | ticket=OMN-18645 | actor=codex | worktree=none | claimed"
RULING = '2026-10-01T00:01:00Z | RULING | lane=operator | ticket=OMN-18645 | "Use the configured model."'
pytestmark = pytest.mark.unit


@pytest.fixture
def ledger_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    ledger = tmp_path / "ROLLING_WORK_LEDGER.md"
    ledger.write_text(CLAIM + "\n", encoding="utf-8")
    env = {
        "ONEX_LANE": "worker",
        "ONEX_LEDGER_PATH": str(ledger),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
    }
    monkeypatch.delenv("ONEX_LANE_ID", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def append(env: dict[str, str], *rows: str) -> None:
    with Path(env["ONEX_LEDGER_PATH"]).open("a", encoding="utf-8") as file:
        file.write("\n".join(rows) + "\n")


def acknowledge(
    env: dict[str, str], *, lane: str = "worker", ruling: str = RULING
) -> None:
    digest = hashlib.sha256(ruling.encode()).hexdigest()
    append(
        env,
        f"2026-10-01T00:02:00Z | ACK | lane={lane} | from={lane} | to=operator | "
        "id=2026-10-01T00:02:00Z-worker | re=2026-10-01T00:01:00Z | "
        f"ruling={env['ONEX_LEDGER_PATH']}:2 | ruling-sha256={digest} | read and applied",
    )


def run_hook(env: dict[str, str], command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(
            {"tool_name": "Bash", "cwd": str(ROOT), "tool_input": {"command": command}}
        ),
        text=True,
        capture_output=True,
        timeout=60,
        env={
            **os.environ,
            **env,
            "CLAUDE_PLUGIN_ROOT": str(ROOT / "plugins/onex"),
            "CLAUDE_PROJECT_DIR": str(ROOT),
            "PLUGIN_PYTHON_BIN": sys.executable,
            "ONEX_HOOK_LOG": str(Path(env["ONEX_STATE_DIR"]).parent / "hook.log"),
        },
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        "git push origin feature",
        "gh pr merge 12 --squash",
        "gh -R org/repo pr merge 12 --squash",
        "env -u PYTHONPATH git push origin feature",
        "env -u PYTHONPATH gh pr merge 12 --squash",
    ],
)
def test_registered_hook_refuses_mid_lane_ruling(
    ledger_env: dict[str, str], command: str
) -> None:
    append(ledger_env, RULING)
    result = run_hook(ledger_env, command)
    assert result.returncode == 2, (result.stdout, result.stderr)
    reason = json.loads(result.stdout)["reason"]
    assert RULING in reason
    assert f"{ledger_env['ONEX_LEDGER_PATH']}:2" in reason


def test_all_new_rulings_are_surfaced(ledger_env: dict[str, str]) -> None:
    second = RULING.replace("00:01:00Z", "00:01:30Z").replace(
        "configured model", "runtime adapter"
    )
    append(ledger_env, RULING, second)
    reason = guard.ruling_reread_refusal(os.environ)
    assert reason and RULING in reason and second in reason


def test_positive_control_older_ruling_passes(ledger_env: dict[str, str]) -> None:
    Path(ledger_env["ONEX_LEDGER_PATH"]).write_text(
        RULING.replace("00:01:00Z", "00:00:00Z")
        + "\n"
        + CLAIM.replace("00:00:00Z", "00:01:00Z")
        + "\n",
        encoding="utf-8",
    )
    result = run_hook(ledger_env, "gh pr merge 12 --squash")
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_acknowledgement_is_durable_and_exact(ledger_env: dict[str, str]) -> None:
    append(ledger_env, RULING)
    assert guard.ruling_reread_refusal(os.environ)
    acknowledge(ledger_env)
    assert guard.ruling_reread_refusal(os.environ) is None
    assert run_hook(ledger_env, "gh pr merge 12 --squash").returncode == 0


@pytest.mark.parametrize("change", ["delete", "edit", "replace", "reclaim"])
def test_ruling_mutation_or_reclaim_is_not_ack(
    ledger_env: dict[str, str], change: str
) -> None:
    append(ledger_env, RULING)
    assert guard.ruling_reread_refusal(os.environ)
    path = Path(ledger_env["ONEX_LEDGER_PATH"])
    if change == "delete":
        path.write_text(CLAIM + "\n", encoding="utf-8")
    elif change == "edit":
        path.write_text(
            CLAIM + "\n" + RULING.replace("RULING", "STATUS") + "\n", encoding="utf-8"
        )
    elif change == "replace":
        path.write_text(
            CLAIM + "\n" + RULING.replace("configured", "different") + "\n",
            encoding="utf-8",
        )
    else:
        append(ledger_env, CLAIM.replace("00:00:00Z", "00:03:00Z"))
    reason = guard.ruling_reread_refusal(os.environ)
    assert reason and RULING in reason


@pytest.mark.parametrize(
    "change",
    [
        "other-lane",
        "no-citation",
        "wrong-hash",
        "wrong-ref",
        "before-ruling",
        "status",
        "no-recipient",
        "wrong-id",
    ],
)
def test_invalid_ack_never_clears(ledger_env: dict[str, str], change: str) -> None:
    append(ledger_env, RULING)
    assert guard.ruling_reread_refusal(os.environ)
    acknowledge(ledger_env, lane="peer" if change == "other-lane" else "worker")
    path = Path(ledger_env["ONEX_LEDGER_PATH"])
    text = path.read_text(encoding="utf-8")
    if change == "no-citation":
        text = text.replace(f"ruling={path}:2", "comment=read")
    elif change == "wrong-hash":
        text = text.replace(hashlib.sha256(RULING.encode()).hexdigest(), "0" * 64)
    elif change == "wrong-ref":
        text = text.replace("re=2026-10-01T00:01:00Z", "re=2026-10-01T00:00:00Z")
    elif change == "before-ruling":
        text = text.replace("00:02:00Z", "00:00:30Z")
    elif change == "status":
        text = text.replace(" | ACK |", " | STATUS |")
    elif change == "no-recipient":
        text = text.replace("to=operator", "comment=received")
    elif change == "wrong-id":
        text = text.replace(
            "id=2026-10-01T00:02:00Z-worker", "id=2026-10-01T00:02:00Z-peer"
        )
    path.write_text(text, encoding="utf-8")
    assert guard.ruling_reread_refusal(os.environ)


def test_roll_preserves_claim_ruling_and_ack(ledger_env: dict[str, str]) -> None:
    append(ledger_env, RULING)
    assert guard.ruling_reread_refusal(os.environ)
    path = Path(ledger_env["ONEX_LEDGER_PATH"])
    archive = path.parent / "archive"
    archive.mkdir()
    path.rename(archive / "ROLLING_WORK_LEDGER_2026-10-02-split.md")
    path.write_text("", encoding="utf-8")
    assert guard.ruling_reread_refusal(os.environ)
    acknowledge(ledger_env)
    assert guard.ruling_reread_refusal(os.environ) is None


def test_missing_claim_or_unreadable_ledger_refuses(ledger_env: dict[str, str]) -> None:
    path = Path(ledger_env["ONEX_LEDGER_PATH"])
    path.write_text(RULING + "\n", encoding="utf-8")
    assert "CLAIM" in (guard.ruling_reread_refusal(os.environ) or "")
    path.unlink()
    assert guard.ruling_reread_refusal(os.environ)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "gh pr checks 12",
        "printf '%s' 'git push'",
        "# gh pr merge 12\necho read",
    ],
)
def test_read_only_commands_do_not_read_ledger(
    ledger_env: dict[str, str], command: str
) -> None:
    Path(ledger_env["ONEX_LEDGER_PATH"]).unlink()
    result = run_hook(ledger_env, command)
    assert result.returncode == 0, (result.stdout, result.stderr)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [GitOperation.PUSH, GitOperation.PR_MERGE])
async def test_bus_handler_refuses_before_subprocess(
    ledger_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, operation: GitOperation
) -> None:
    append(ledger_env, RULING)
    spawn = AsyncMock()
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    handler = HandlerGitSubprocess()
    handler._git_available = True
    handler._gh_available = True
    request = ModelGitRequest(operation=operation, branch_name="feature", pr_number=12)
    result = await (
        handler.push(request)
        if operation == GitOperation.PUSH
        else handler.pr_merge(request)
    )
    assert result.error_code == "LEDGER_RULING_UNACKNOWLEDGED"
    assert result.error and RULING in result.error
    spawn.assert_not_awaited()


def test_shared_brief_template_requires_reread() -> None:
    phrase = "re-read the ledger for RULING rows appended after CLAIM"
    template = ROOT / "plugins/onex/skills/_shared/skill_orchestrator_template.md"
    dispatch = ROOT / "src/omniclaude/shared/handler_skill_requested.py"
    assert phrase in template.read_text(encoding="utf-8")
    assert phrase in dispatch.read_text(encoding="utf-8")


def test_reread_adapter_is_registered() -> None:
    assert is_live_on_bash_matcher(HOOK.name)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [GitOperation.PUSH, GitOperation.PR_MERGE])
async def test_bus_handler_ack_positive_control(
    ledger_env: dict[str, str], monkeypatch: pytest.MonkeyPatch, operation: GitOperation
) -> None:
    append(ledger_env, RULING)
    acknowledge(ledger_env)
    process = AsyncMock()
    process.returncode = 0
    process.communicate.return_value = (b"success", b"")
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr("asyncio.create_subprocess_exec", spawn)
    handler = HandlerGitSubprocess()
    handler._git_available = True
    handler._gh_available = True
    request = ModelGitRequest(operation=operation, branch_name="feature", pr_number=12)
    result = await (
        handler.push(request)
        if operation == GitOperation.PUSH
        else handler.pr_merge(request)
    )
    assert result.status.value == "success"
    spawn.assert_awaited_once()


def test_every_dispatched_brief_requires_reread() -> None:
    tree = ast.parse(
        (ROOT / "src/omniclaude/shared/handler_skill_requested.py").read_text()
    )
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "handle_skill_requested"
    )
    # The instruction is in the unconditional prompt assignment, shared by every
    # skill request, rather than hidden inside a skill-specific branch.
    prompt = next(
        node
        for node in handler.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "prompt"
            for target in node.targets
        )
    )
    constants = [
        node.value
        for node in ast.walk(prompt.value)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert any(
        "re-read the ledger for RULING rows appended after CLAIM" in value
        for value in constants
    )


def test_no_lane_or_ticket_suppression_surface(ledger_env: dict[str, str]) -> None:
    source = inspect.getsource(guard.ruling_reread_refusal)
    for forbidden in ("allowlist", "suppression", "SKIP", "disable", "ticket="):
        assert forbidden not in source
    append(ledger_env, RULING)
    # An invented suppression field is ordinary data and cannot unblock the gate.
    append(
        ledger_env,
        "2026-10-01T00:02:00Z | STATUS | lane=worker | ruling-ignore=true | ticket=OMN-18645 | ignore",
    )
    assert guard.ruling_reread_refusal(os.environ)


def test_corrupt_journal_refuses(ledger_env: dict[str, str]) -> None:
    append(ledger_env, RULING)
    assert guard.ruling_reread_refusal(os.environ)
    journal = Path(ledger_env["ONEX_STATE_DIR"]) / "hooks/ruling-reread.jsonl"
    journal.write_bytes(b"not a database")
    assert "could not be verified" in (guard.ruling_reread_refusal(os.environ) or "")


def test_ack_removal_reinstates_refusal(ledger_env: dict[str, str]) -> None:
    append(ledger_env, RULING)
    acknowledge(ledger_env)
    assert guard.ruling_reread_refusal(os.environ) is None
    Path(ledger_env["ONEX_LEDGER_PATH"]).write_text(
        CLAIM + "\n" + RULING + "\n", encoding="utf-8"
    )
    assert guard.ruling_reread_refusal(os.environ)


def test_ack_for_one_ruling_does_not_clear_another(ledger_env: dict[str, str]) -> None:
    append(ledger_env, RULING)
    acknowledge(ledger_env)
    second = RULING.replace("00:01:00Z", "00:03:00Z").replace(
        "configured model", "runtime adapter"
    )
    append(ledger_env, second)
    reason = guard.ruling_reread_refusal(os.environ)
    assert reason and second in reason


def test_missing_state_root_refuses(
    ledger_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEX_STATE_DIR")
    assert "ONEX_STATE_DIR" in (guard.ruling_reread_refusal(os.environ) or "")


def test_unattributed_lane_worktree_refuses() -> None:
    reason = guard.ruling_reread_refusal(
        {}, "/registry/omni_worktrees/worker/omniclaude"
    )
    assert reason and "resolve the executing lane" in reason
    assert guard.ruling_reread_refusal({}, "/operator/repo") is None


def test_same_second_ruling_is_conservatively_refused(
    ledger_env: dict[str, str],
) -> None:
    append(ledger_env, RULING.replace("00:01:00Z", "00:00:00Z"))
    assert guard.ruling_reread_refusal(os.environ)

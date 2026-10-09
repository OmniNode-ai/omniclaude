# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19699: the claim CLI and hook must agree without admitting peers."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.onex.hooks.lib.pr_ownership_guard import evaluate_command, resolve_lane_id

pytestmark = pytest.mark.unit
CLI = Path(__file__).resolve().parents[3] / "scripts/pr_claim_registry_cli.py"
KEY = "omninode-ai/omniclaude#19699"
COMMAND = "gh pr close 19699 --repo OmniNode-ai/omniclaude"
SESSION = "same-session-123456789"


@pytest.fixture
def caller(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name in (
        "ONEX_LANE_ID",
        "ONEX_LANE",
        "ONEX_AGENT_NAME",
        "CLAUDE_AGENT_NAME",
        "CLAUDE_SUBAGENT_NAME",
        "OMNI_HOME",
        "ONEX_WORKTREES_ROOT",
        "OMNI_WORKTREES_DIR",
        "CLAUDE_SESSION_ID",
        "ONEX_SESSION_ID",
        "SESSION_ID",
    ):
        env.pop(name, None)
    env.update(
        ONEX_STATE_DIR=str(tmp_path / "state"),
        CLAUDE_CODE_SESSION_ID=SESSION,
        ONEX_RUN_ID="run-self",
        PWD=str(tmp_path),
    )
    return env


def claim(
    env: dict[str, str], tmp_path: Path, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), "claim", KEY, *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def verdict(env: dict[str, str], tmp_path: Path):
    return evaluate_command(
        COMMAND,
        claims_dir=tmp_path / "state/pr-queue/claims",
        env=env,
        cwd=tmp_path,
    )[0]


def test_readable_alias_is_visibly_resolved_and_own_mutation_admitted(caller, tmp_path):
    result = claim(caller, tmp_path, "--lane", "repo-drain-x")
    assert result.returncode == 0, result.stderr
    lane = resolve_lane_id(env=caller, cwd=tmp_path)
    assert lane in result.stderr and "repo-drain-x" in result.stderr
    data = json.loads(
        next((tmp_path / "state/pr-queue/claims").glob("*.json")).read_text()
    )
    assert data["lane_id"] == lane
    assert data["claimed_by_run"] == "run-self"
    assert verdict(caller, tmp_path).allowed


def test_different_run_with_same_session_and_lane_is_refused(caller, tmp_path):
    assert claim(caller, tmp_path).returncode == 0
    peer = {**caller, "ONEX_RUN_ID": "run-peer"}
    decision = verdict(peer, tmp_path)
    assert not decision.allowed
    assert resolve_lane_id(env=caller, cwd=tmp_path) in decision.message
    assert "run-self" in decision.message


@pytest.mark.parametrize("peer_run", [False, True])
def test_named_claim_with_session_only_hook_identity(caller, tmp_path, peer_run):
    owner = {**caller, "ONEX_LANE_ID": "repo-drain-x"}
    result = claim(owner, tmp_path, "--lane", "repo-drain-x")
    assert result.returncode == 0, result.stderr
    data = json.loads(
        next((tmp_path / "state/pr-queue/claims").glob("*.json")).read_text()
    )
    assert data["lane_id"] == "repo-drain-x"
    hook = {**caller, "ONEX_RUN_ID": "run-peer" if peer_run else "run-self"}
    decision = verdict(hook, tmp_path)
    assert decision.allowed is (not peer_run)
    assert "repo-drain-x" in decision.message


@pytest.mark.parametrize(
    "missing_field", [None, "claimed_by_session", "claimed_by_run"]
)
def test_named_claim_session_fallback_requires_full_identity(
    caller, tmp_path, missing_field
):
    owner = {**caller, "ONEX_LANE_ID": "repo-drain-x"}
    assert claim(owner, tmp_path, "--lane", "repo-drain-x").returncode == 0
    if missing_field:
        path = next((tmp_path / "state/pr-queue/claims").glob("*.json"))
        data = json.loads(path.read_text())
        data.pop(missing_field)
        path.write_text(json.dumps(data))
    else:
        caller["CLAUDE_CODE_SESSION_ID"] = SESSION + "-peer"
    decision = verdict(caller, tmp_path)
    assert not decision.allowed
    assert "repo-drain-x" in decision.message


def test_missing_run_does_not_authorize_a_named_lane_claim(caller, tmp_path):
    caller.pop("CLAUDE_CODE_SESSION_ID")
    caller["ONEX_LANE_ID"] = "owner-lane"
    assert claim(caller, tmp_path).returncode == 0
    peer = dict(caller)
    peer.pop("ONEX_RUN_ID")
    assert not verdict(peer, tmp_path).allowed


def test_explicit_peer_lane_sharing_session_and_run_still_refused(caller, tmp_path):
    owner = {**caller, "ONEX_LANE_ID": "owner-lane"}
    assert claim(owner, tmp_path, "--lane", "repo-drain-x").returncode == 0
    decision = verdict({**caller, "ONEX_LANE_ID": "peer-lane"}, tmp_path)
    assert not decision.allowed
    assert "owner-lane" in decision.message


@pytest.mark.parametrize("explicit_run", [False, True])
def test_session_prefix_collision_does_not_authorize_another_session(
    caller, tmp_path, explicit_run
):
    if not explicit_run:
        caller.pop("ONEX_RUN_ID")
    assert claim(caller, tmp_path).returncode == 0
    assert verdict(caller, tmp_path).allowed
    peer = {**caller, "CLAUDE_CODE_SESSION_ID": SESSION + "-peer"}
    assert resolve_lane_id(env=peer, cwd=tmp_path) == resolve_lane_id(
        env=caller, cwd=tmp_path
    )
    assert not verdict(peer, tmp_path).allowed


def test_alias_without_resolvable_identity_is_refused(caller, tmp_path):
    caller.pop("CLAUDE_CODE_SESSION_ID")
    result = claim(caller, tmp_path, "--lane", "repo-drain-x")
    assert result.returncode != 0
    assert not list((tmp_path / "state/pr-queue/claims").glob("*.json"))


def test_printed_remedy_runs_verbatim_and_then_admits(caller, tmp_path):
    before = verdict(caller, tmp_path)
    assert not before.allowed
    remedy = next(
        line.strip() for line in before.message.splitlines() if line.startswith("    ")
    )
    result = subprocess.run(
        shlex.split(remedy),
        cwd=tmp_path,
        env=caller,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert verdict(caller, tmp_path).allowed


def test_printed_remedy_preserves_hook_identity_from_another_directory(
    caller, tmp_path
):
    root = tmp_path / "worktrees"
    hook_cwd = root / "OMN-19699" / "omniclaude"
    hook_cwd.mkdir(parents=True)
    caller["ONEX_WORKTREES_ROOT"] = str(root)
    before = evaluate_command(
        COMMAND,
        claims_dir=tmp_path / "state/pr-queue/claims",
        env=caller,
        cwd=hook_cwd,
    )[0]
    remedy = next(
        line.strip() for line in before.message.splitlines() if line.startswith("    ")
    )
    result = subprocess.run(
        shlex.split(remedy),
        cwd=tmp_path,
        env=caller,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    after = evaluate_command(
        COMMAND,
        claims_dir=tmp_path / "state/pr-queue/claims",
        env=caller,
        cwd=hook_cwd,
    )[0]
    assert after.allowed

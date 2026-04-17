# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for stop_session_bootstrap_guard.sh — Block B backlog gate + bypass.

DoD evidence for OMN-9054 plan Task 5: stop hook blocks premature session-end
when org-wide backlog has >5 BLOCKED PRs with no in-flight fixer agents, and
honors STOP_GUARD_ACK=1 bypass.

Block A (TODO pending-items check) is NOT in this PR — see OMN-9059 follow-up.
State-source discovery (Task 5 Step 2a) confirmed the Claude Code runtime does
not expose TODO state to Stop hooks.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
_SCRIPT = "plugins/onex/hooks/scripts/stop_session_bootstrap_guard.sh"
_STOP_JSON = json.dumps(
    {"session_id": "sess-omn-9054", "completion_status": "complete"}
)


def _run_hook(
    state_dir: str,
    *,
    bootstrap_flag: bool = True,
    claims: int = 0,
    blocked_pr_count: int = 0,
    stop_guard_ack: bool = False,
    mode: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the Stop guard with a mocked gh CLI that reports blocked_pr_count.

    `claims` creates N lock files under $ONEX_STATE_DIR/dispatch_claims/
    (nonzero = active fixer agents in flight).
    """
    state_path = Path(state_dir)

    if bootstrap_flag:
        flag = state_path / "session" / "cron_bootstrap.flag"
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("1")

    claims_dir = state_path / "dispatch_claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    for i in range(claims):
        (claims_dir / f"claim_{i}.lock").write_text(
            json.dumps({"kind": "ticket_dispatch", "claimant": f"fix-{i}", "ttl": 3600})
        )

    # Build a fake gh shim that echoes a json array of blocked_pr_count stubs.
    bin_dir = state_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    gh_shim = bin_dir / "gh"
    stub_array = json.dumps([{"number": 9000 + i} for i in range(blocked_pr_count)])
    gh_shim.write_text(f"#!/bin/bash\necho '{stub_array}'\n")
    gh_shim.chmod(0o755)

    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = state_dir
    env["HOME"] = state_dir
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    if stop_guard_ack:
        env["STOP_GUARD_ACK"] = "1"
    else:
        env.pop("STOP_GUARD_ACK", None)
    if mode is not None:
        env["OMNICLAUDE_MODE"] = mode

    return subprocess.run(
        ["bash", _SCRIPT],
        input=_STOP_JSON,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        cwd=_REPO_ROOT,
        env=env,
    )


@pytest.mark.unit
def test_bootstrap_flag_present_and_backlog_clean_allows_stop() -> None:
    """Existing bootstrap check still passes when backlog is empty (no regression)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(tmpdir, blocked_pr_count=0, claims=0)
    assert result.returncode == 0, (
        f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
    )


@pytest.mark.unit
def test_many_blocked_prs_with_no_fixers_blocks_stop() -> None:
    """Block B: >5 BLOCKED PRs + zero active fixer claims → exit 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(tmpdir, blocked_pr_count=12, claims=0)
    assert result.returncode == 2, (
        f"Expected exit 2 (blocked), got {result.returncode}. "
        f"stdout: {result.stdout} stderr: {result.stderr}"
    )
    assert "BLOCKED" in result.stderr
    assert "12" in result.stderr, "message must name the PR count"
    assert (
        "no fixer agents" in result.stderr.lower()
        or "no fixer" in result.stderr.lower()
    )


@pytest.mark.unit
def test_many_blocked_prs_with_active_fixers_allows_stop() -> None:
    """Block B: >5 BLOCKED PRs + active fixer claims → exit 0 (fixers will drain backlog)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(tmpdir, blocked_pr_count=12, claims=3)
    assert result.returncode == 0, (
        f"Expected exit 0 (fixers present), got {result.returncode}. stderr: {result.stderr}"
    )


@pytest.mark.unit
def test_stop_guard_ack_bypasses_block_b() -> None:
    """STOP_GUARD_ACK=1 allows session-end regardless of backlog state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(tmpdir, blocked_pr_count=99, claims=0, stop_guard_ack=True)
    assert result.returncode == 0, (
        f"STOP_GUARD_ACK=1 must bypass Block B. got {result.returncode}. stderr: {result.stderr}"
    )


@pytest.mark.unit
def test_missing_bootstrap_flag_still_blocks() -> None:
    """Existing behavior: missing bootstrap flag blocks independent of Block B."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = _run_hook(tmpdir, bootstrap_flag=False, blocked_pr_count=0, claims=0)
    assert result.returncode == 2, (
        f"Expected exit 2 (bootstrap), got {result.returncode}. stderr: {result.stderr}"
    )
    assert "bootstrap" in result.stderr.lower()

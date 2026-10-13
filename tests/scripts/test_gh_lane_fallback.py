# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20911: named consumers keep their old gh call from a lane, and every use is logged.

RULING 2026-10-12T05:03:28Z: a gate whose replacement path does not work end to end
today falls back to the old path with a logged fallback until the replacement proves
out, and is then made strict. The lane read guard (OMN-20911) and the lane write guard
(OMN-20914) each let a short list of named consumers through, decided on the direct
parent, and every such use appends one FRICTION row naming the gate, the consumer and
the call it fell back to. A use that cannot be recorded is refused.

Each test puts a scripted fake ``gh`` behind the user shim. No test uses the network or
an operator credential.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from tests.scripts.conftest import install_ancestry_ps
from tests.scripts.test_gh_lane_write_guard import _install

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
printf '%s' "${FAKE_GH_STDOUT:-ok}"
exit "${FAKE_GH_RC:-0}"
"""

PY_BODY = (
    "import subprocess, sys\n"
    "r = subprocess.run(['gh', *sys.argv[1:]])\n"
    "sys.exit(r.returncode)\n"
)
SH_BODY = 'gh "$@"\nexit $?\n'

# consumer -> (interpreter, script path relative to tmp_path, the read it makes)
CONSUMERS: dict[str, tuple[str, str, list[str]]] = {
    "enforcement-surface-placement": (
        "python3",
        ".venv/bin/check-platform-leads-review-tripwire",
        ["api", "repos/OmniNode-ai/onex_change_control/branches/dev/protection"],
    ),
    "worktree-prune": (
        "bash",
        "scripts/prune-worktrees.sh",
        ["pr", "list", "--repo", "OmniNode-ai/omniclaude", "--state", "merged"],
    ),
    "worktree-auto-prune": (
        "python3",
        "scripts/worktree_auto_prune.py",
        ["pr", "list", "--repo", "OmniNode-ai/omniclaude", "--state", "all"],
    ),
    "bulk-pr-throttle": (
        "python3",
        "scripts/ci/bulk_pr_throttle.py",
        ["api", "repos/OmniNode-ai/omnimarket"],
    ),
}


def _write_exec(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A lane (ONEX_LANE set) whose state directory is a temporary one."""
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    install_ancestry_ps(fake_dir)
    workspace = tmp_path / "workspace"
    _install(workspace)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "ONEX_GH_CALLS_LOG": str(tmp_path / "gh-calls.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "ONEX_LANDING_CONTROLLER_ROOT": str(tmp_path / "controller"),
        "OMNI_HOME": str(workspace),
        "ONEX_LANE": "fallback-lane",
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _rows(env: dict[str, str]) -> list[str]:
    path = Path(env["ONEX_STATE_DIR"]) / "friction" / "gh-lane-fallback.rows"
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _calls(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["FAKE_GH_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def _run_as(
    env: dict[str, str], tmp_path: Path, interpreter: str, rel: str, argv: list[str]
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / rel
    _write_exec(script, PY_BODY if interpreter == "python3" else SH_BODY)
    return subprocess.run(
        [interpreter, rel, *argv],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize("consumer", list(CONSUMERS), ids=str)
def test_named_consumer_read_falls_back_and_writes_one_friction_row(
    env: dict[str, str], tmp_path: Path, consumer: str
) -> None:
    interpreter, rel, argv = CONSUMERS[consumer]

    result = _run_as(env, tmp_path, interpreter, rel, argv)

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert "FALLBACK (OMN-20911): " in result.stderr
    assert f"named consumer {consumer} " in result.stderr
    rows = _rows(env)
    assert len(rows) == 1, rows
    cells = rows[0].split(" | ")
    assert cells[1] == "FRICTION"
    assert "lane=fallback-lane" in cells
    assert "ticket=OMN-20911" in cells
    assert "gate=gh-lane-read-guard" in cells
    assert f"consumer={consumer}" in cells
    assert any(c.startswith("fallback=gh ") for c in cells), cells
    assert any(c.startswith("cost=~") for c in cells), cells
    assert "RULING 2026-10-12T05:03:28Z" in cells[-1]


@pytest.mark.unit
def test_each_use_is_one_more_row(env: dict[str, str], tmp_path: Path) -> None:
    interpreter, rel, argv = CONSUMERS["worktree-prune"]
    for _ in range(3):
        assert _run_as(env, tmp_path, interpreter, rel, argv).returncode == 0
    assert len(_rows(env)) == 3
    assert len(_calls(env)) == 3


def _set_strict(env: dict[str, str], verb: str) -> None:
    """Make one verb strict in gh-gateway.env, the only place that can (never the env)."""
    conf = Path(env["XDG_CONFIG_HOME"]) / "omni" / "gh-gateway.env"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(f"ONEX_GH_LANE_READ_STRICT_{verb}=1\n")


def _call_log_actions(env: dict[str, str]) -> list[str]:
    log = Path(env["ONEX_GH_CALLS_LOG"])
    if not log.exists():
        return []
    return [line.split("\t")[7] for line in log.read_text().splitlines()]


@pytest.mark.unit
def test_an_unnamed_script_is_refused_when_its_verb_is_strict_and_writes_no_row(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Negative twin: the same read under another script name is a lane read."""
    _, _, argv = CONSUMERS["bulk-pr-throttle"]
    _set_strict(env, "API")

    result = _run_as(env, tmp_path, "python3", "scripts/ci/bulk_pr_throttle2.py", argv)

    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20911): ")
    assert _calls(env) == []
    assert _rows(env) == []


@pytest.mark.unit
def test_an_unnamed_script_takes_the_budgeted_gateway_not_the_named_fallback(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Strict is off by default: the unnamed read is counted by the gateway, not by a row."""
    _, _, argv = CONSUMERS["bulk-pr-throttle"]

    result = _run_as(env, tmp_path, "python3", "scripts/ci/bulk_pr_throttle2.py", argv)

    assert result.returncode == 0, result.stderr
    assert "named consumer" not in result.stderr
    assert _calls(env) == [argv]
    assert _call_log_actions(env) == ["fallback"]
    assert _rows(env) == []


@pytest.mark.unit
def test_a_named_fallback_that_cannot_be_recorded_is_not_taken(
    env: dict[str, str], tmp_path: Path
) -> None:
    """An uncounted named fallback could never be proven unused, so it is not taken.

    The consumer is then an ordinary lane read: refused when its verb is strict.
    """
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("")
    interpreter, rel, argv = CONSUMERS["worktree-auto-prune"]
    _set_strict(env, "PR_LIST")

    result = _run_as(
        {**env, "ONEX_STATE_DIR": str(blocker)}, tmp_path, interpreter, rel, argv
    )

    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20911): ")
    assert _calls(env) == []


@pytest.mark.unit
def test_a_named_fallback_that_cannot_be_recorded_falls_to_the_budgeted_gateway(
    env: dict[str, str], tmp_path: Path
) -> None:
    """With the verb not strict, the unrecordable consumer is counted by the gateway instead."""
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("")
    interpreter, rel, argv = CONSUMERS["worktree-auto-prune"]

    result = _run_as(
        {**env, "ONEX_STATE_DIR": str(blocker)}, tmp_path, interpreter, rel, argv
    )

    assert result.returncode == 0, result.stderr
    assert "named consumer" not in result.stderr
    assert _calls(env) == [argv]
    assert _call_log_actions(env) == ["fallback"]


@pytest.mark.unit
def test_outside_a_lane_the_consumer_reads_with_no_row(
    env: dict[str, str], tmp_path: Path
) -> None:
    """Positive control: a launchd timer or operator shell is not a lane and is untouched."""
    not_lane = {k: v for k, v in env.items() if k != "ONEX_LANE"}
    interpreter, rel, argv = CONSUMERS["worktree-prune"]

    result = _run_as(not_lane, tmp_path, interpreter, rel, argv)

    assert result.returncode == 0, result.stderr
    assert "FALLBACK" not in result.stderr
    assert _rows(env) == []


@pytest.mark.unit
def test_lane_workflow_run_falls_back_and_writes_one_friction_row(
    env: dict[str, str],
) -> None:
    argv = ["workflow", "run", "ci.yml", "--repo", "OmniNode-ai/omnimarket"]

    result = subprocess.run(
        ["gh", *argv], env=env, capture_output=True, text=True, timeout=30, check=False
    )

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert "FALLBACK (OMN-20911): gh workflow run from a lane" in result.stderr
    assert "onex scm workflow-run" in result.stderr
    rows = _rows(env)
    assert len(rows) == 1, rows
    cells = rows[0].split(" | ")
    assert "gate=gh-lane-write-guard" in cells
    assert "consumer=workflow-run" in cells
    assert "fallback=gh workflow run" in cells


@pytest.mark.unit
def test_lane_workflow_run_unrecordable_is_refused(
    env: dict[str, str], tmp_path: Path
) -> None:
    blocker = tmp_path / "state-is-a-file"
    blocker.write_text("")
    argv = ["workflow", "run", "ci.yml", "--repo", "OmniNode-ai/omnimarket"]

    result = subprocess.run(
        ["gh", *argv],
        env={**env, "ONEX_STATE_DIR": str(blocker)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20914): gh workflow run")
    assert _calls(env) == []


@pytest.mark.unit
def test_other_covered_writes_stay_refused(env: dict[str, str]) -> None:
    """The write fallback is workflow run only; pr create keeps its onex scm refusal."""
    argv = [
        "pr",
        "create",
        "--repo",
        "OmniNode-ai/omnimarket",
        "--title",
        "t",
        "--body",
        "b",
    ]

    result = subprocess.run(
        ["gh", *argv], env=env, capture_output=True, text=True, timeout=30, check=False
    )

    assert result.returncode == 1, result.stderr
    assert result.stderr.startswith("REFUSED (OMN-20914): gh pr create")
    assert _calls(env) == []
    assert _rows(env) == []


@pytest.mark.unit
@pytest.mark.parametrize("consumer", list(CONSUMERS), ids=str)
def test_strict_read_refused_switch_leaves_a_named_consumer_on_its_fallback(
    env: dict[str, str], tmp_path: Path, consumer: str
) -> None:
    """The read-strict switch (OMN-20911, W8) is for unnamed reads; a named consumer's
    logged fallback is decided first and keeps its row until it is deleted from the shim."""
    conf = Path(env["XDG_CONFIG_HOME"]) / "omni" / "gh-gateway.env"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("ONEX_GH_LANE_READ_STRICT=1\n")
    interpreter, rel, argv = CONSUMERS[consumer]

    result = _run_as(env, tmp_path, interpreter, rel, argv)

    assert result.returncode == 0, result.stderr
    assert _calls(env) == [argv]
    assert len(_rows(env)) == 1

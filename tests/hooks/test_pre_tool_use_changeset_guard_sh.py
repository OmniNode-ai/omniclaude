# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Shell-wrapper tests for pre_tool_use_changeset_guard.sh (OMN-13848).

Two defects fixed and proven here:

1. Unanchored ``\\.`` regex: ``git add (-A|--all|\\.)`` matched a literal dot
   ANYWHERE after ``git add ``, so specific-file stages like
   ``git add .gitignore`` / ``git add .env`` / ``git add ./src/x.py`` produced
   false-positive warnings (~72% noise). The trailing ``([[:space:]]|$)`` anchor
   makes ``.`` match only as the whole pathspec argument.

2. Dead event sink: the guard appended to
   ``~/.claude/changeset-guard-events/events.jsonl`` -- a path no tool reads and
   which violates the "never write state under ~/.claude" doctrine. The event is
   now recorded on the observable friction registry
   (``$ONEX_STATE_DIR/friction/changeset_guard/``) that friction tooling scans.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_changeset_guard.sh"
)


def _run(command: str, tmp: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    # Neutralize any ambient mask that disables the CHANGESET_GUARD_PRE bit.
    env.pop("ONEX_HOOKS_MASK", None)
    env["ONEX_STATE_DIR"] = str(tmp / "state")
    env["HOME"] = str(tmp / "home")
    (tmp / "home").mkdir(exist_ok=True)
    payload = {
        "tool_name": "Bash",
        "session_id": "sess-cg-01",
        "tool_input": {"command": command},
    }
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=env,
    )


def _warned(result: subprocess.CompletedProcess) -> bool:
    assert result.returncode == 0, f"hook must never block; got {result.returncode}"
    return "Changeset Guard" in result.stdout


# ---------------------------------------------------------------------------
# Anchored regex: specific-file stages must NOT warn (former false positives)
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "git add .gitignore",
        "git add .env",
        "git add ./src/x.py",
        "git add README.md",
        "git add src/module.py",
    ],
)
def test_specific_file_stage_does_not_warn(command: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run(command, Path(td))
    assert not _warned(result), (
        f"{command!r} should not trigger a broad-staging warning"
    )


# ---------------------------------------------------------------------------
# Anchored regex: genuine broad staging must still warn
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "command",
    [
        "git add .",
        "git add -A",
        "git add --all",
        "git add . && echo done",
        "git commit -am x && git add -A",
    ],
)
def test_broad_staging_warns(command: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        result = _run(command, Path(td))
    assert _warned(result), f"{command!r} should trigger a broad-staging warning"


# ---------------------------------------------------------------------------
# Event sink: recorded on the observable friction registry, never in ~/.claude
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_broad_staging_writes_friction_to_onex_state() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        result = _run("git add -A", tmp)
        assert result.returncode == 0

        friction_dir = tmp / "state" / "friction" / "changeset_guard"
        files = list(friction_dir.glob("*-broad-staging-*.yaml"))
        assert len(files) == 1, f"expected 1 friction file, found {files}"

        data = yaml.safe_load(files[0].read_text())
        assert data["severity"] == "P3"
        assert data["surface"] == "changeset_guard"
        assert data["category"] == "changeset"
        assert data["session_id"] == "sess-cg-01"

        # The dead ~/.claude sink must NOT be recreated.
        assert not (tmp / "home" / ".claude" / "changeset-guard-events").exists()


@pytest.mark.unit
def test_specific_file_stage_writes_no_friction() -> None:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _run("git add .gitignore", tmp)
        friction_dir = tmp / "state" / "friction" / "changeset_guard"
        assert not friction_dir.exists() or not list(friction_dir.glob("*.yaml"))


@pytest.mark.unit
def test_broad_staging_without_onex_state_dir_still_warns_and_no_fallback() -> None:
    """Missing ONEX_STATE_DIR must degrade gracefully: warn, but write no fallback."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        env = os.environ.copy()
        env.pop("ONEX_HOOKS_MASK", None)
        env.pop("ONEX_STATE_DIR", None)
        env["HOME"] = str(tmp / "home")
        (tmp / "home").mkdir()
        payload = {
            "tool_name": "Bash",
            "session_id": "s1",
            "tool_input": {"command": "git add -A"},
        }
        result = subprocess.run(
            ["bash", str(_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
            env=env,
        )
    assert result.returncode == 0
    assert "Changeset Guard" in result.stdout
    # No friction file fabricated under the $HOME/.onex_state fallback.
    assert list((tmp / "home").rglob("*-broad-staging-*.yaml")) == []

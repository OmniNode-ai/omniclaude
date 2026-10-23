# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the doubled registry-root admission gate (OMN-18607).

Written red first against the tree at omniclaude c0bb5b38, where none of the
PreToolUse guards refused a doubled path: every case in
``DOUBLED_REFUSED`` was ADMITTED there, by the Bash guard family and by the
Write/Edit matcher alike, and `test_the_gap_this_ticket_closes_is_real` records
that measurement as the RED baseline the fix turns GREEN.

``$OMNI_HOME`` IS the ``omni_home`` repository root on this fleet. A lane that
followed the old `$OMNI_HOME/CLAUDE.md:169` ("Run from $OMNI_HOME/omni_home
(repo root)", corrected in omni_home#365) created a stray untracked
``$OMNI_HOME/omni_home/`` directory; two lanes then wrote scratch output into it
over three weeks before anyone noticed, and a second lane hit the identical
doubling on 2026-09-16 (``docs/tracking/ROLLING_WORK_LEDGER.md:3695``). The
directory was never git-added, so no repo-scoped CI gate could have caught it.

Both directions are tested, because a guard that refuses the doubled path by
refusing everything that says ``omni_home`` would break every ordinary call in
the registry clone. The anchored half (AC4) is the one that separates them: a
path carrying the characters ``omni_home/omni_home`` OUTSIDE the resolved
``$OMNI_HOME`` -- a worktree for a ticket named after the repo -- is a real
place and is admitted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
GUARD_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_omni_home_path_guard.sh"
BUNDLE_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_bash_guards.sh"

sys.path.insert(0, str(HOOKS_DIR / "lib"))

from omni_home_doubled_path_guard import (  # noqa: E402
    DOUBLED_SEGMENT,
    GATE_BIT_NAME,
    TICKET,
    evaluate_payload,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# The vocabulary under test
# ---------------------------------------------------------------------------

#: Calls that must be refused: each resolves inside $OMNI_HOME/omni_home.
DOUBLED_REFUSED: list[tuple[str, dict]] = [
    (
        "bash mkdir, the 2026-09-16 shape",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p {home}/omni_home/.claude_scratch"},
        },
    ),
    (
        "bash mkdir through $OMNI_HOME",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p $OMNI_HOME/omni_home/.onex_state/x"},
        },
    ),
    (
        "bash mkdir through ${OMNI_HOME}",
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'mkdir -p "${OMNI_HOME}/omni_home/reports"'},
        },
    ),
    (
        "bash write through a redirection",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "echo hi > $OMNI_HOME/omni_home/notes.md"},
        },
    ),
    (
        "a relative path from the registry root",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p omni_home/.claude_scratch"},
            "cwd": "{home}",
        },
    ),
    (
        "Write",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "{home}/omni_home/.claude_scratch/r.md",
                "content": "x",
            },
        },
    ),
    (
        "Edit",
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "$OMNI_HOME/omni_home/r.md",
                "old_string": "a",
                "new_string": "b",
            },
        },
    ),
    (
        "MultiEdit",
        {
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": "{home}/omni_home/r.md", "edits": []},
        },
    ),
    (
        "NotebookEdit",
        {
            "tool_name": "NotebookEdit",
            "tool_input": {"notebook_path": "{home}/omni_home/r.ipynb"},
        },
    ),
]

#: Calls that must be admitted. Each either names no doubled segment, or names
#: one that is NOT anchored at the resolved $OMNI_HOME -- AC4's direction.
ADMITTED: list[tuple[str, dict]] = [
    (
        "an ordinary path in the registry clone",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "mkdir -p $OMNI_HOME/.claude_scratch/reports"},
        },
    ),
    (
        "an ordinary repo path",
        {
            "tool_name": "Bash",
            "tool_input": {"command": "ls $OMNI_HOME/omniclaude/plugins"},
        },
    ),
    (
        "a worktree for a ticket named after the repo",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "{home}/omni_worktrees/omni_home/omni_home/notes.md",
                "content": "x",
            },
        },
    ),
    (
        "the same doubled characters under another tree entirely",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/elsewhere/omni_home/omni_home/notes.md",
                "content": "x",
            },
        },
    ),
    (
        "a path naming the segment once, outside the root",
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/elsewhere/omni_home/notes.md",
                "content": "x",
            },
        },
    ),
    (
        "a tool this guard reads no path from",
        {"tool_name": "Read", "tool_input": {"file_path": "{home}/omni_home/r.md"}},
    ),
]


def _fill(payload: dict, home: Path) -> dict:
    """The payload with ``{home}`` resolved to this run's registry root."""
    raw = json.dumps(payload).replace("{home}", str(home))
    return json.loads(raw)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    """A stand-in for $OMNI_HOME: the registry clone's root directory."""
    root = tmp_path / "omni"
    (root / "omni_worktrees").mkdir(parents=True)
    (root / ".claude_scratch").mkdir()
    return root


# ---------------------------------------------------------------------------
# AC1 + AC4 on the decision core
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "payload"), DOUBLED_REFUSED, ids=[c[0] for c in DOUBLED_REFUSED]
)
def test_a_path_doubled_onto_the_registry_root_is_refused(
    label: str, payload: dict, home: Path
) -> None:
    """AC1: the doubled path is refused and the refusal names it."""
    decision = evaluate_payload(
        _fill(payload, home), {"OMNI_HOME": str(home)}, cwd=str(home)
    )
    assert decision.blocked, (label, decision.notes)
    assert str(home / DOUBLED_SEGMENT) in decision.reason, label


@pytest.mark.parametrize(("label", "payload"), ADMITTED, ids=[c[0] for c in ADMITTED])
def test_a_path_that_is_not_anchored_at_the_root_is_admitted(
    label: str, payload: dict, home: Path
) -> None:
    """AC4: anchored at $OMNI_HOME, never a substring match.

    The third and fourth cases carry the literal characters the naive check
    would match on. Without this direction the guard would refuse a real
    worktree whose ticket is named after the repository.
    """
    decision = evaluate_payload(
        _fill(payload, home), {"OMNI_HOME": str(home)}, cwd=str(home)
    )
    assert not decision.blocked, (label, decision.reason)


def test_no_omni_home_means_no_anchor_and_no_refusal(home: Path) -> None:
    """Operating Rule 16 control: the refusals come from the anchor.

    With OMNI_HOME unset there is no root, and every refused shape above is
    admitted -- the pre-change behaviour. A guard that refused these anyway
    would be matching the substring, not the root.
    """
    for label, payload in DOUBLED_REFUSED:
        decision = evaluate_payload(_fill(payload, home), {}, cwd=str(home))
        assert not decision.blocked, label
        assert "OMNI_HOME is unset" in " ".join(decision.notes), label


# ---------------------------------------------------------------------------
# AC3 -- the refusal text
# ---------------------------------------------------------------------------


def test_the_refusal_names_omni_home_and_the_correction(home: Path) -> None:
    """AC3: a lane must not have to re-derive the fix from CLAUDE.md."""
    payload = _fill(DOUBLED_REFUSED[0][1], home)
    decision = evaluate_payload(payload, {"OMNI_HOME": str(home)}, cwd=str(home))
    assert decision.blocked
    reason = decision.reason
    assert "$OMNI_HOME is already the omni_home repo root" in reason
    assert "drop the extra 'omni_home/' segment" in reason
    assert f"$OMNI_HOME={home}" in reason
    # The corrected path, spelled out, not described.
    assert str(home / ".claude_scratch") in reason
    assert TICKET in reason
    assert f"onex hooks disable {GATE_BIT_NAME}" in reason


# ---------------------------------------------------------------------------
# AC1 end to end: the hook script, and the bundled entrypoint that sources it
# ---------------------------------------------------------------------------


def _run(
    script: Path, payload: dict, home: Path, tmp_path: Path, mask: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(tmp_path / "fakehome"),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
        "OMNI_HOME": str(home),
    }
    if mask is not None:
        env["ONEX_HOOKS_MASK"] = mask
    (tmp_path / "fakehome").mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(home),
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    ("label", "payload"),
    [c for c in DOUBLED_REFUSED if c[1]["tool_name"] != "Bash"],
    ids=[c[0] for c in DOUBLED_REFUSED if c[1]["tool_name"] != "Bash"],
)
def test_the_hook_refuses_a_write_end_to_end(
    label: str, payload: dict, home: Path, tmp_path: Path
) -> None:
    """AC1: the Write/Edit registration refuses, and the write never happens."""
    result = _run(GUARD_SCRIPT, _fill(payload, home), home, tmp_path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    verdict = json.loads(result.stdout)
    assert verdict["decision"] == "block"
    assert "doubles the repo root" in verdict["reason"]
    assert not (home / DOUBLED_SEGMENT).exists()


def test_the_bundled_bash_entrypoint_refuses_the_doubled_mkdir(
    home: Path, tmp_path: Path
) -> None:
    """AC1 for Bash: the one registered Bash entrypoint sources this guard."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"mkdir -p {home}/omni_home/.claude_scratch"},
        "cwd": str(home),
    }
    result = _run(BUNDLE_SCRIPT, payload, home, tmp_path)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "doubles the repo root" in result.stdout
    assert not (home / DOUBLED_SEGMENT).exists()


def test_the_bundled_entrypoint_still_admits_an_ordinary_command(
    home: Path, tmp_path: Path
) -> None:
    """Positive control for the case above: the bundle did not start refusing."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": f"mkdir -p {home}/.claude_scratch/reports"},
        "cwd": str(home),
    }
    result = _run(BUNDLE_SCRIPT, payload, home, tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_the_guard_is_disabled_by_its_own_bit(home: Path, tmp_path: Path) -> None:
    """The gate bit is honoured, and nothing else refuses in its place."""
    payload = _fill(DOUBLED_REFUSED[5][1], home)
    result = _run(GUARD_SCRIPT, payload, home, tmp_path, mask="0x0")
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_the_gap_this_ticket_closes_is_real(home: Path, tmp_path: Path) -> None:
    """The RED baseline, recorded rather than asserted (AC2).

    At omniclaude c0bb5b38 this guard did not exist: the file below was absent
    and no other PreToolUse guard refused any shape in ``DOUBLED_REFUSED``,
    which is the measurement on the ticket (checked live 2026-09-17, re-checked
    2026-10-23). This test pins the two facts that make that gap closed rather
    than described: the decision core exists where the registration names it,
    and the registration is the Write/Edit matcher the gap was found on.
    """
    assert (HOOKS_DIR / "lib" / "omni_home_doubled_path_guard.py").is_file()
    hooks = json.loads((HOOKS_DIR / "hooks.json").read_text())
    registered = [
        group
        for group in hooks["hooks"]["PreToolUse"]
        if any(GUARD_SCRIPT.name in h["command"] for h in group["hooks"])
    ]
    assert len(registered) == 1, registered
    assert registered[0]["matcher"] == "^(Write|Edit|MultiEdit|NotebookEdit)$"
    assert all(h.get("onFailure") == "block" for h in registered[0]["hooks"])
    bundle = BUNDLE_SCRIPT.read_text()
    assert GUARD_SCRIPT.name in bundle

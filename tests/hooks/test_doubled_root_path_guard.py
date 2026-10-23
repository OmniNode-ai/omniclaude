# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the doubled registry-root arm of the git admission gate (OMN-18607).

Written red first against omniclaude c0bb5b38, where no PreToolUse guard refused
a doubled path: every case in ``DOUBLED_REFUSED`` was ADMITTED there, through the
decision core and through the hook script end to end. The policy carried no
``doubled_root_segments`` at all, so ``test_the_policy_declares_the_vocabulary``
also fails on that tree.

The registry root IS the repository's own root on this fleet. The old
`CLAUDE.md:169` said to run from a copy of the repo nested one segment inside it;
a lane that followed it created a stray untracked directory there, and two lanes
wrote scratch output into it over three weeks before anyone noticed
(2026-08-19 and 2026-09-16, `docs/tracking/ROLLING_WORK_LEDGER.md:3695`). It was
never git-added, so no repo-scoped CI gate could see it.

Both directions are tested, because a guard that refuses the doubled path by
refusing every path naming the segment would refuse half the ordinary commands
in the registry clone. The anchored half (AC4) separates them: the same
characters OUTSIDE the resolved root are a real place and are admitted.

The segment itself is never spelled here. It is read from the policy the guard
reads, so this file and the guard cannot drift apart on it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from omniclaude.nodes.node_git_effect.handlers.handler_git_admission import (
    GATE_BIT_NAME,
    Policy,
    evaluate_bash_command,
    load_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
HOOK_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_shared_tree_git_guard.sh"
POLICY_PATH = (
    REPO_ROOT / "src/omniclaude/nodes/node_git_effect/git_admission_policy.json"
)

pytestmark = pytest.mark.unit


def _git(*args: str) -> None:
    subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        env=scrub_git_location_env(os.environ),
    )


@pytest.fixture(autouse=True)
def _isolate_ambient_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in load_policy(POLICY_PATH).fetch_lane_envs:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


@pytest.fixture
def segment(policy: Policy) -> str:
    """The segment that must not sit directly under the root, from the policy."""
    assert policy.doubled_root_segments, "the policy declares no doubled segment"
    return policy.doubled_root_segments[0]


@pytest.fixture
def registry(tmp_path: Path, policy: Policy) -> Path:
    """A stand-in for the registry clone at the resolved root."""
    root = tmp_path / "registry_clone"
    root.mkdir(parents=True)
    _git("init", "-q", "-b", "main", str(root))
    _git("-C", str(root), "config", "user.email", "t@example.com")
    _git("-C", str(root), "config", "user.name", "t")
    _git("-C", str(root), "commit", "-q", "--allow-empty", "-m", "init")
    for marker in policy.registry_root_markers:
        target = root / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n")
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "commit", "-q", "-m", "markers")
    (root / "omni_worktrees").mkdir()
    return root


#: Commands that must be refused. Each resolves inside the doubled root.
DOUBLED_REFUSED = [
    "mkdir -p {root}/{seg}/.claude_scratch",
    "mkdir -p $OMNI_HOME/{seg}/.onex_state/omn16191-tier0-proof",
    'mkdir -p "${{OMNI_HOME}}/{seg}/reports"',
    "echo hi > $OMNI_HOME/{seg}/notes.md",
    "cp report.md {root}/{seg}/.claude_scratch/reports/sweep.md",
    "cd {root} && mkdir -p {seg}/.claude_scratch",
]

#: Commands that must be admitted: no doubled path, or the same characters
#: somewhere that is not the resolved root.
ADMITTED = [
    "mkdir -p {root}/.claude_scratch/reports",
    "ls {root}/omniclaude/plugins",
    "mkdir -p {root}/omni_worktrees/{seg}/{seg}/.claude_scratch",
    "mkdir -p /tmp/elsewhere/{seg}/{seg}/notes",
    "mkdir -p /tmp/elsewhere/{seg}/notes",
    "git status",
]


def _fill(template: str, registry: Path, segment: str) -> str:
    return template.format(root=registry, seg=segment)


# ---------------------------------------------------------------------------
# AC1 -- the refusal
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", DOUBLED_REFUSED)
def test_a_path_doubled_onto_the_root_is_refused(
    template: str, registry: Path, policy: Policy, segment: str
) -> None:
    command = _fill(template, registry, segment)
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked, command
    assert str(registry / segment) in decision.reason, command


@pytest.mark.parametrize("template", ADMITTED)
def test_a_path_that_is_not_anchored_at_the_root_is_admitted(
    template: str, registry: Path, policy: Policy, segment: str
) -> None:
    """AC4: anchored at the resolved root, never a substring match.

    The third and fourth cases carry the exact characters a naive check would
    match on. Without this direction the guard would refuse a real worktree
    whose ticket is named after the repository.
    """
    command = _fill(template, registry, segment)
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert not decision.blocked, (command, decision.reason)


def test_no_resolved_root_means_no_anchor_and_no_refusal(
    registry: Path, policy: Policy, segment: str
) -> None:
    """Operating Rule 16 control: the refusals come from the anchor.

    With no registry root resolved, every refused command above is admitted --
    the pre-change behaviour. A guard that refused these anyway would be
    matching the characters, not the root.
    """
    for template in DOUBLED_REFUSED:
        command = _fill(template, registry, segment)
        decision = evaluate_bash_command(
            command, policy, cwd=registry, registry_root=None
        )
        assert not decision.blocked, command


def test_a_segment_nobody_types_admits_every_doubled_path(
    tmp_path: Path, registry: Path, segment: str
) -> None:
    """Second control: the vocabulary is what refuses, not the code path."""
    raw = json.loads(POLICY_PATH.read_text())
    raw["doubled_root_segments"] = ["a-directory-nobody-makes"]
    quiet_path = tmp_path / "no-doubled-segments.json"
    quiet_path.write_text(json.dumps(raw))
    quiet = load_policy(quiet_path)
    for template in DOUBLED_REFUSED:
        command = _fill(template, registry, segment)
        decision = evaluate_bash_command(
            command, quiet, cwd=registry, registry_root=registry
        )
        assert not decision.blocked, command


# ---------------------------------------------------------------------------
# AC3 -- the refusal text
# ---------------------------------------------------------------------------


def test_the_refusal_names_the_root_and_the_correction(
    registry: Path, policy: Policy, segment: str
) -> None:
    """AC3: a lane must not have to re-derive the fix from CLAUDE.md."""
    command = _fill(DOUBLED_REFUSED[0], registry, segment)
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    reason = decision.reason
    assert f"$OMNI_HOME is already the {segment} repo root" in reason
    assert f"drop the extra {segment}/ segment" in reason
    assert f"$OMNI_HOME={registry}" in reason
    # The corrected path, spelled out rather than described.
    assert str(registry / ".claude_scratch") in reason
    assert policy.doubled_root_ticket in reason
    assert f"onex hooks disable {GATE_BIT_NAME}" in reason


# ---------------------------------------------------------------------------
# AC2 -- the gap, and the vocabulary that closes it
# ---------------------------------------------------------------------------


def test_the_policy_declares_the_vocabulary(policy: Policy) -> None:
    """AC2: at c0bb5b38 the policy had no such field, so this failed on import
    of its own expectation. The ticket id travels with the vocabulary."""
    assert policy.doubled_root_ticket == "OMN-18607"
    assert policy.doubled_root_segments
    assert all(seg and "/" not in seg for seg in policy.doubled_root_segments)


# ---------------------------------------------------------------------------
# AC1 end to end -- the registered hook refuses the mkdir
# ---------------------------------------------------------------------------


def _run_hook(
    tmp_path: Path, command: str, cwd: Path, registry_root_dir: str
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "PLUGIN_PYTHON_BIN": sys.executable,
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
        "OMNI_HOME": registry_root_dir,
    }
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


def test_the_hook_refuses_the_doubled_mkdir_end_to_end(
    tmp_path: Path, registry: Path, segment: str
) -> None:
    """AC1 through the registered surface: the directory is never created."""
    command = _fill(DOUBLED_REFUSED[0], registry, segment)
    result = _run_hook(tmp_path, command, registry, str(registry))
    assert result.returncode == 2, (result.stdout, result.stderr)
    verdict = json.loads(result.stdout)
    assert verdict["decision"] == "block"
    assert "doubles the repository root" in verdict["reason"]
    assert not (registry / segment).exists()


def test_the_hook_still_admits_an_ordinary_command(
    tmp_path: Path, registry: Path, segment: str
) -> None:
    """Positive control for the case above: the hook did not start refusing."""
    command = _fill(ADMITTED[0], registry, segment)
    result = _run_hook(tmp_path, command, registry, str(registry))
    assert result.returncode == 0, (result.stdout, result.stderr)

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18853: the stamp rebind moved to the writer; the guard did not move.

OMN-18853 gives the omnimarket autobind writer the power to replace a foreign
or duplicated change-control evidence line with the one companion the receipt
gate's own validator proves binds the PR's head. That power belongs to the
writer, which runs in the effects runtime off a published command and never
issues an agent Bash call. It must NOT leak into this guard.

These tests pin both halves from the guard's side:

* the exact edits the writer now performs -- foreign line replaced, duplicate
  collapsed, duplicate demoted into a fence -- are still REFUSED when an agent
  issues them by hand, over every body-replacing shape the guard parses;
* the one agent action the rebind path needs, re-requesting the writer through
  the autobind manual-replay dispatch, names no body edit and is admitted.

The fixture bodies are the live shapes that stranded omnibase_core#1762,
omniclaude#2338, omnimemory#533 and omnibase_infra#4104 on 2026-09-25. Their
stamp values are FIXTURES and bind nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
POLICY_PATH = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "config" / "pr_body_stamp_policy.json"
)

sys.path.insert(0, str(LIB_DIR))

from pr_body_stamp_guard import (  # noqa: E402
    Policy,
    check_bash_command,
    load_policy,
    stamp_lines,
)

pytestmark = pytest.mark.unit

_PREFIX = "Evidence-" + "Source: "


def _stamp(n: int) -> str:
    return f"{_PREFIX}OCC#{n}"


#: omniclaude#2338 as the cascade opened it: the inherited release companion.
FOREIGN_LIVE = (
    f"Bumps omnibase-core to 0.47.23.\n\nEvidence-Ticket: OMN-18595\n{_stamp(11192)}\n"
)
#: What the writer now writes for it: the PR's own proven companion.
FOREIGN_REBOUND = (
    f"Bumps omnibase-core to 0.47.23.\n\nEvidence-Ticket: OMN-18595\n{_stamp(11213)}\n"
)

#: omnibase_core#1762: two lines, which the receipt gate refuses outright.
DUPLICATE_LIVE = (
    "Receipt gates re-run on ready_for_review.\n\n"
    "Evidence-Ticket: OMN-19512\n"
    f"{_stamp(11171)}\n"
    f"{_stamp(11170)}\n"
)
#: What the writer now writes for it: exactly one line.
DUPLICATE_COLLAPSED = (
    "Receipt gates re-run on ready_for_review.\n\n"
    "Evidence-Ticket: OMN-19512\n"
    f"{_stamp(11171)}\n"
)
#: The receipt gate's own printed remedy for two lines: fence one of them.
DUPLICATE_FENCED = (
    "Receipt gates re-run on ready_for_review.\n\n"
    "Evidence-Ticket: OMN-19512\n"
    f"{_stamp(11171)}\n\n"
    "```\n"
    f"{_stamp(11170)}\n"
    "```\n"
)


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


def _reader(bodies: dict[str, str]):
    def _read(edit) -> str | None:
        return bodies.get(f"{edit.repo}#{edit.selector}")

    return _read


def _edit_shapes(repo: str, number: int, body_file: Path) -> list[str]:
    """Every body-replacing shape an agent would reach for, over one body."""
    return [
        f"gh pr edit {number} --repo {repo} --body-file {body_file}",
        f'gh pr edit {number} --repo {repo} --body "$(cat {body_file})"',
        f"gh api -X PATCH repos/{repo}/pulls/{number} -F body=@{body_file}",
    ]


@pytest.mark.parametrize(
    ("repo", "number", "live", "replacement", "dropped"),
    [
        pytest.param(
            "OmniNode-ai/omniclaude",
            2338,
            FOREIGN_LIVE,
            FOREIGN_REBOUND,
            _stamp(11192),
            id="foreign-line-replaced",
        ),
        pytest.param(
            "OmniNode-ai/omnibase_core",
            1762,
            DUPLICATE_LIVE,
            DUPLICATE_COLLAPSED,
            _stamp(11170),
            id="duplicate-collapsed",
        ),
        pytest.param(
            "OmniNode-ai/omnibase_core",
            1762,
            DUPLICATE_LIVE,
            DUPLICATE_FENCED,
            _stamp(11170),
            id="duplicate-fenced",
        ),
    ],
)
def test_the_writers_edit_is_still_refused_when_an_agent_makes_it(
    policy: Policy,
    tmp_path: Path,
    repo: str,
    number: int,
    live: str,
    replacement: str,
    dropped: str,
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(replacement, encoding="utf-8")
    bodies = {f"{repo}#{number}": live}
    for command in _edit_shapes(repo, number, body_file):
        findings = check_bash_command(command, policy, _reader(bodies))
        assert findings, f"an agent rebind must stay refused: {command}"
        assert findings[0].kind == "dropped_stamp", command
        assert dropped in findings[0].dropped_lines, command


def test_the_writers_output_is_the_one_line_body_the_gate_wants(
    policy: Policy,
) -> None:
    """Positive control on the fixtures: the replacements are what they claim.

    Without this, a fixture typo that left the stamp in place would make the
    refusal tests above pass for the wrong reason.
    """
    assert stamp_lines(FOREIGN_LIVE, policy) == [_stamp(11192)]
    assert stamp_lines(FOREIGN_REBOUND, policy) == [_stamp(11213)]
    assert len(stamp_lines(DUPLICATE_LIVE, policy)) == 2
    assert stamp_lines(DUPLICATE_COLLAPSED, policy) == [_stamp(11171)]
    assert stamp_lines(DUPLICATE_FENCED, policy) == [_stamp(11171)]


def test_retaining_every_live_line_is_still_admitted(
    policy: Policy, tmp_path: Path
) -> None:
    """The guard is unchanged in the other direction too: prose edits pass."""
    body_file = tmp_path / "body.md"
    body_file.write_text("A reworded summary.\n\n" + DUPLICATE_LIVE, encoding="utf-8")
    bodies = {"OmniNode-ai/omnibase_core#1762": DUPLICATE_LIVE}
    command = (
        f"gh pr edit 1762 --repo OmniNode-ai/omnibase_core --body-file {body_file}"
    )
    assert check_bash_command(command, policy, _reader(bodies)) == []


@pytest.mark.parametrize(
    "command",
    [
        "gh workflow run call-occ-autobind.yml --repo OmniNode-ai/omniclaude "
        "-f pr_number=2338",
        "gh workflow run call-occ-autobind.yml --repo OmniNode-ai/omnimemory "
        "--ref dev -f pr_number=533",
        "gh api -X POST repos/OmniNode-ai/omnibase_core/actions/workflows/"
        "call-occ-autobind.yml/dispatches -f ref=dev -f inputs[pr_number]=1762",
    ],
)
def test_requesting_the_writer_is_admitted(policy: Policy, command: str) -> None:
    """The sanctioned path: an agent asks the writer, it does not edit the body.

    The manual-replay dispatch publishes the autobind command; the writer then
    performs the rebind in the effects runtime. It names no body-replacing
    flag, so the guard has nothing to judge and must not stand in the way.
    """
    assert check_bash_command(command, policy, _reader({})) == []

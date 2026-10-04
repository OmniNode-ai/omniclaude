# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The release skill runs no PR-state read the gh shim refuses (OMN-19489).

The gh user shim (``scripts/user-bin/gh``, OMN-19856 and OMN-20436) refuses ``gh pr checks`` and
``gh pr view`` from every lane. The one read it lets through is the declared exact-head check right
before a mutation: ``ONEX_GH_EXACT_HEAD=<owner>/<repo>#<n> gh pr view <n> --repo <owner>/<repo>
--json <fields>``, with no ``--jq`` or ``--template`` and only the fields the shim lists. Everything
else about a PR comes from the PR watcher's state file, read with the omni plugin's
``merge-drain/scripts/pr_state_local.py``, and a merge commit comes from the canonical clone.

omniclaude#2529 replaced the release skill's CI watch loop with ``gh pr checks --required``, which
the shim refuses, so the release skill would fail at its merge step the moment the shim is
installed. This test keeps every executable line of the prompt inside the shim's allowance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROMPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "release"
    / "prompt.md"
)

# The fields the shim's exact-head check allows (scripts/user-bin/gh, _prs_exact_head).
EXACT_HEAD_FIELDS = frozenset(
    {
        "headRefOid",
        "headRefName",
        "baseRefName",
        "state",
        "isDraft",
        "mergedAt",
        "mergeStateStatus",
        "number",
    }
)


def _code_lines(text: str) -> list[str]:
    """Lines inside fenced code blocks, plus inline backtick spans outside them."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            if not line.lstrip().startswith("#"):
                out.append(line)
        else:
            out.extend(re.findall(r"`([^`]+)`", line))
    return out


def refused_reads(text: str) -> list[str]:
    """Each executable ``gh pr checks`` or ``gh pr view`` the shim would refuse."""
    bad: list[str] = []
    for line in _code_lines(text):
        if re.search(r"\bgh\s+pr\s+checks\b", line):
            bad.append(line.strip())
            continue
        if not re.search(r"\bgh\s+pr\s+view\b", line):
            continue
        if "ONEX_GH_EXACT_HEAD=" not in line or re.search(
            r"--jq\b|--template\b|-q\b", line
        ):
            bad.append(line.strip())
            continue
        m = re.search(r"--json[ =]([\w,]+)", line)
        if m is None or not set(m.group(1).split(",")) <= EXACT_HEAD_FIELDS:
            bad.append(line.strip())
    return bad


@pytest.mark.unit
def test_positive_control_refused_shapes_are_flagged() -> None:
    text = "\n".join(
        [
            "```bash",
            'gh pr checks "${PR_NUMBER}" --repo "${GITHUB_REPO}" --required',
            "PR_STATE=$(gh pr view 9 --repo o/r --json state --jq '.state')",
            'ONEX_GH_EXACT_HEAD=o/r#9 gh pr view 9 --repo o/r --json state --jq ".state"',
            "ONEX_GH_EXACT_HEAD=o/r#9 gh pr view 9 --repo o/r --json mergeCommit",
            "```",
        ]
    )
    assert len(refused_reads(text)) == 4


@pytest.mark.unit
def test_negative_control_allowed_shapes_pass() -> None:
    text = "\n".join(
        [
            "```bash",
            "# gh pr checks is refused by the shim",
            'ONEX_GH_EXACT_HEAD="o/r#9" gh pr view 9 --repo o/r --json state,mergedAt | jq -r .state',
            'python3 "$PR_STATE_LOCAL" --pr "o/r#9"',
            "gh pr merge 9 --repo o/r --squash",
            "```",
        ]
    )
    assert refused_reads(text) == []


@pytest.mark.unit
def test_release_prompt_runs_no_refused_pr_state_read() -> None:
    bad = refused_reads(PROMPT.read_text(encoding="utf-8"))
    assert not bad, (
        "release/prompt.md runs PR-state reads the gh shim refuses; read the PR watcher state "
        "(pr_state_local.py) or declare an exact-head check instead:\n  "
        + "\n  ".join(bad)
    )

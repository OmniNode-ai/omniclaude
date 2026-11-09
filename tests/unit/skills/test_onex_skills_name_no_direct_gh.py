# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The lane-run onex skills name the read-only mirror, never a direct gh call (OMN-18946).

Floor row ``hook-refusal:lane-github-read-real-gh``: 110 occurrences in the 24 hours to 2026-11-09T06:51Z, 92 of them from
subagents running ``gh pr view`` (52), ``gh pr create`` (18), ``gh api`` GET (12), ``gh pr list`` (11) and ``gh run`` (6)
after a skill or a brief told them to. A lane reads PR state from the PR watcher (``pr_state_local.py``, ``onex scm``)
and writes through ``onex scm`` (RULING 2026-10-10T18:17:36Z).

SCANNED names the skills this change moved to the mirror. A line that forbids a call (``never``, ``refused``, ``instead of``)
or quotes history (a ``>`` line) is not an instruction. There is no allowlist and no baseline: a finding is moved to the
mirror, never listed here. Each refusal has a positive control (the line naming the mirror passes).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "plugins" / "onex" / "skills"

SCANNED = (
    "_lib/cdqa-gate/helpers.md",
    "_lib/dispatch-laws/helpers.md",
    "_lib/integration-branch/helpers.md",
    "_lib/integration-verification-gate/helpers.md",
    "_lib/pr-safety/helpers.md",
    "create_followup_tickets/SKILL.md",
    "dashboard_sweep/prompt.md",
    "decompose_epic/SKILL.md",
    "decompose_epic/prompt.md",
    "dep_cascade_dedup/SKILL.md",
    "dod_sweep/SKILL.md",
    "epic_team/SKILL.md",
    "epic_team/prompt.md",
    "executing_plans/SKILL.md",
    "gap/SKILL.md",
    "gap/prompt.md",
    "multi_agent/SKILL.md",
    "pr_watch/SKILL.md",
    "release/SKILL.md",
    "release/prompt.md",
    "ticket_pipeline/SKILL.md",
    "verification_receipt_generator/SKILL.md",
    "verification_sweep/SKILL.md",
    "worktree/SKILL.md",
)

GH_CALL = re.compile(
    r"\bgh\s+(?:pr\s+(?:view|checks|status|list|diff|checkout|create|comment|edit|ready|close|reopen)"
    r"|run\s+(?:view|list|watch|download)|repo\s+(?:view|list)|issue\s+(?:view|list|status)|search\s+\w+"
    r"|release\s+(?:list|view|download)|workflow\s+(?:list|view|run)|api\b)"
)
GH_API_NOT_A_CALL = re.compile(r"\brate_limit\b|--help\b|\bmutation\b")
PROHIBITION_BEFORE = re.compile(
    r"\b(?:never|not|no|nor|without|refus\w*|forbid\w*|instead of|in place of|rather than|replaces?|replaced"
    r"|was|were|don't|do not|bars?|barred|direct use of|raw)\b",
    re.IGNORECASE,
)
PROHIBITION_AFTER = re.compile(
    r"^\W{0,3}(?:is|are|was|were)?\s*(?:refus|forbid|barred|denied)", re.IGNORECASE
)
ARGV_JOIN = re.compile(r"""["']\s*,\s*["']""")


def gh_call_lines(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if raw.lstrip().startswith(">"):
            continue
        line = ARGV_JOIN.sub(" ", raw)
        for m in GH_CALL.finditer(line):
            if m.group(0).endswith("api") and GH_API_NOT_A_CALL.search(line[m.end() :]):
                continue
            before = re.split(r"[.;:]\s", line[max(0, m.start() - 90) : m.start()])[-1]
            if PROHIBITION_BEFORE.search(before) or PROHIBITION_AFTER.match(
                line[m.end() : m.end() + 60].lstrip("`)\" '")
            ):
                continue
            found.append((number, raw.strip()))
            break
    return found


@pytest.mark.parametrize("name", SCANNED)
def test_skill_names_no_direct_gh_call(name: str) -> None:
    found = gh_call_lines((SKILLS / name).read_text(encoding="utf-8"))
    assert not found, (
        f"plugins/onex/skills/{name} tells a lane to run gh; name `onex scm <verb>` or "
        f"`pr_state_local.py` instead: {found}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "gh pr view 9 --repo o/r --json state",
        "gh pr checks 9 --repo o/r",
        "gh pr list --repo o/r --state open",
        "gh run view 123 --log-failed",
        "gh api repos/o/r/pulls/9 --jq .head.sha",
        'subprocess.run(["gh", "pr", "view", str(n)])',
        "gh pr create --base main --title t",
    ],
)
def test_the_detector_flags_each_refused_shape(line: str) -> None:
    assert gh_call_lines(line), line


@pytest.mark.parametrize(
    "line",
    [
        "onex scm pr-checks o/r#9",
        "python3 pr_state_local.py --pr o/r#9",
        "never run gh pr view from a lane",
        "`gh pr checks` is refused from a lane; use onex scm pr-checks",
        "> gh pr view 9 was refused at 06:39Z",
        "gh api rate_limit",
    ],
)
def test_the_detector_admits_the_mirror_a_negation_and_quoted_history(
    line: str,
) -> None:
    assert not gh_call_lines(line), line


def test_named_break_a_skill_that_tells_a_lane_to_run_gh_pr_view_is_refused() -> None:
    text = (SKILLS / "pr_watch" / "SKILL.md").read_text(encoding="utf-8")
    assert not gh_call_lines(text)
    broken = (
        text
        + "\n1. Fetch PR review state via `gh pr view {pr_number} --repo {repo} --json reviews`\n"
    )
    assert len(gh_call_lines(broken)) == 1

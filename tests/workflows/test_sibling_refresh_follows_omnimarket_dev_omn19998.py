# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: omniclaude's omnimarket git pin follows omnimarket dev, no release wait.

Operator ruling 2026-10-16T07:34:18Z: "There's no reason we need to wait for a
release." omniclaude already pins omnimarket by git rev, advanced to the
canonical clone's head by ``scripts/relock_git_sources.py`` inside
``sibling-lock-refresh.yml``. That workflow ran once a day, so the pin sat a
day and 69 commits behind omnimarket dev (0143496c against dae3f3e6 on
2026-10-16). These tests pin the three things that make the advance follow
omnimarket dev:

* the workflow runs on the ``omnimarket-dev-moved`` dispatch that omnimarket's
  ci.yml sends on every dev push (the event type is spelled in both repos;
  a cross-repo test would skip wherever the other clone is absent);
* an hourly schedule is the fallback for a dispatch that never arrived;
* every run reuses one branch, so a refresh on every omnimarket merge moves the
  one open bot PR instead of opening a new PR that conflicts with the last.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "sibling-lock-refresh.yml"
)
DISPATCH_TYPE = "omnimarket-dev-moved"


def _workflow() -> dict[Any, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers() -> dict[str, Any]:
    wf = _workflow()
    # PyYAML reads the bare key `on` as the boolean True.
    triggers = wf.get("on", wf.get(True))
    assert isinstance(triggers, dict), f"unreadable triggers: {triggers!r}"
    return triggers


def _refresh_pr_script() -> str:
    steps = _workflow()["jobs"]["refresh"]["steps"]
    scripts = [s.get("run", "") for s in steps if s.get("name") == "Open refresh PR"]
    assert len(scripts) == 1, "the Open refresh PR step is missing or duplicated"
    return scripts[0]


def test_the_refresh_runs_when_omnimarket_dev_moves() -> None:
    dispatch = _triggers().get("repository_dispatch")
    assert isinstance(dispatch, dict), "no repository_dispatch trigger"
    assert DISPATCH_TYPE in dispatch.get("types", []), (
        f"repository_dispatch does not accept {DISPATCH_TYPE!r}; omnimarket's "
        "dev push would dispatch into nothing and the pin would wait for the "
        "schedule"
    )


def test_the_fallback_schedule_is_hourly() -> None:
    crons = [entry["cron"] for entry in _triggers().get("schedule", [])]
    assert crons, "no fallback schedule"
    for cron in crons:
        minute, hour, *_ = cron.split()
        assert minute.isdigit(), f"{cron!r}: minute is not one fixed minute"
        assert hour == "*", (
            f"{cron!r} runs less than hourly; a lost dispatch would leave the "
            "pin behind omnimarket dev for up to a day again"
        )


def test_every_run_reuses_one_branch() -> None:
    script = _refresh_pr_script()
    lines = [
        ln.strip() for ln in script.splitlines() if ln.strip().startswith("BRANCH=")
    ]
    assert len(lines) == 1, lines
    assert "$(" not in lines[0] and "${{" not in lines[0], (
        f"{lines[0]!r} varies per run, so every omnimarket merge would open "
        "another refresh PR"
    )
    assert "omn-13902" in lines[0].lower(), (
        "the Receipt Gate reads the ticket from the branch"
    )


def test_an_open_refresh_pr_is_moved_not_duplicated() -> None:
    script = _refresh_pr_script()
    push = script.index("git push --force origin")
    listing = script.index("gh pr list --head")
    create = script.index("gh pr create")
    assert push < listing < create, (
        "the branch must be pushed, then the open PR on it looked up, before "
        "a new PR is opened"
    )

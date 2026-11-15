# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""``sibling-lock-refresh.yml`` runs the nightly sibling-pin train (OMN-19998).

RULING 2026-10-19T10:11:00Z and its MSG 2026-10-19T10:11:27Z: once a night, ONE
bump PR per consumer moving every internal sibling to its newest dev merge tag
whose dev CI is green, a workflow_dispatch of the same train for urgent fixes,
and no per-tag PRs. These tests pin the workflow's half: the train step runs
before the lock is re-resolved, reads dev CI with gh, honours a dry run, and the
PR step reuses one fixed branch and updates an open PR in place.
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


def _load() -> dict[Any, Any]:
    return yaml.safe_load(WORKFLOW.read_text())


def _steps() -> list[dict[str, Any]]:
    return _load()["jobs"]["refresh"]["steps"]


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected one step running {needle!r}, found {hits}"
    return hits[0]


def test_manual_dispatch_with_dry_run_and_no_schedule() -> None:
    triggers = _load()[True]  # PyYAML reads the bare `on:` key as True
    assert "schedule" not in triggers
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["dry_run"]["type"] == "boolean"
    assert inputs["dry_run"]["default"] is False


def test_train_runs_before_the_lock_is_resolved() -> None:
    steps = _steps()
    train = _index(steps, "--dev-tag-train")
    lock = _index(steps, 'uv lock "${ARGS[@]}"')
    assert train < lock
    run = str(steps[train]["run"])
    assert "--green-from github" in run
    assert "--registry-root" in run
    assert "--plan-out" in run
    assert steps[train]["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token }}"


def test_train_applies_only_when_not_a_dry_run() -> None:
    run = str(_steps()[_index(_steps(), "--dev-tag-train")]["run"])
    assert "DRY_RUN" in run
    assert "--apply" in run


def test_train_clones_each_member_with_its_tags() -> None:
    steps = _steps()
    clone = _index(steps, "parse_dev_tag_pins")
    assert clone < _index(steps, "--dev-tag-train")
    assert "--tags" in str(steps[clone]["run"]) or "git clone" in str(
        steps[clone]["run"]
    )


def test_pr_step_reuses_one_branch_and_updates_in_place() -> None:
    steps = _steps()
    pr = steps[_index(steps, "gh pr create")]
    run = str(pr["run"])
    assert "date -u" not in run, "a timestamped branch opens one PR per night"
    assert "gh pr list" in run
    assert "--force-with-lease" in run or "--force" in run
    assert "dry_run" in str(pr["if"])


def test_refresh_stages_and_counts_the_pre_commit_config() -> None:
    """OMN-22636: the train's hook-block moves are part of the refresh, never left unstaged."""
    steps = _steps()
    delta = str(steps[_index(steps, "git diff --quiet")]["run"])
    commit = str(steps[_index(steps, "gh pr create")]["run"])
    assert (
        ".pre-commit-config.yaml"
        in delta.split("git --no-pager diff --stat", maxsplit=1)[0]
    )
    assert ".pre-commit-config.yaml" in delta.split("git --no-pager diff --stat")[1]
    staged = next(line for line in commit.splitlines() if "git add" in line)
    assert ".pre-commit-config.yaml" in staged

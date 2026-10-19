# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pass the pull request head commit to cli_review so substitute receipts can be read.

OMN-17427, port of OMN-20947.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit]

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "hostile-reviewer.yml"
)
HEAD_SHA_EXPR = "${{ github.event.pull_request.head.sha }}"
HEAD_SHA_ARG = '--head-sha "$HEAD_SHA"'


def review_step(workflow_text: str) -> dict[str, Any]:
    workflow = yaml.safe_load(workflow_text)
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("id") == "review":
                return dict(step)
    raise AssertionError("no step with id 'review'")


def head_sha_problems(workflow_text: str) -> list[str]:
    problems: list[str] = []
    step = review_step(workflow_text)
    if step.get("env", {}).get("HEAD_SHA") != HEAD_SHA_EXPR:
        problems.append("HEAD_SHA is not the pull request head sha")
    run = str(step.get("run", ""))
    if "omniintelligence.review_pairing.cli_review" not in run:
        problems.append("the review step does not run cli_review")
    if HEAD_SHA_ARG not in run:
        problems.append("cli_review is not passed --head-sha")
    return problems


def test_review_passes_the_pull_request_head_sha() -> None:
    assert head_sha_problems(WORKFLOW.read_text(encoding="utf-8")) == []


def test_a_review_step_without_the_head_sha_is_caught() -> None:
    """The review step as it was before this change."""
    text = WORKFLOW.read_text(encoding="utf-8")
    before = re.sub(r"^\s+HEAD_SHA: .*\n", "", text, flags=re.M).replace(
        f"              {HEAD_SHA_ARG} \\\n", ""
    )
    assert head_sha_problems(before) == [
        "HEAD_SHA is not the pull request head sha",
        "cli_review is not passed --head-sha",
    ]


def test_the_head_is_the_pull_request_head_not_the_merge_ref() -> None:
    step = review_step(WORKFLOW.read_text(encoding="utf-8"))
    head_sha = step["env"]["HEAD_SHA"]
    assert "github.sha" not in head_sha
    assert head_sha == HEAD_SHA_EXPR

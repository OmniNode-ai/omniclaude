# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: each Hostile Reviewer attempt holds two chunk-scaled deadlines."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# omnibase_internal#844 (3d5b9d93) sets review_deadline_seconds 1500 for both CI voters.
TWO_VOTER_REVIEW_DEADLINE_SECONDS = 2 * 1500


@pytest.fixture(scope="module")
def budget_config() -> tuple[int, str]:
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "hostile-reviewer.yml").read_text(
            encoding="utf-8"
        )
    )
    job = workflow["jobs"]["hostile-review"]
    step = next(step for step in job["steps"] if step.get("id") == "retry-budget")
    return int(job["env"]["HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS"]), step["run"]


def _per_attempt_budget(ceiling: int, run_text: str) -> int:
    values: dict[str, int] = {}
    for name in (
        "SETUP_OVERHEAD_SECONDS",
        "REVIEW_ATTEMPTS",
        "RETRY_PAUSE_SECONDS",
    ):
        match = re.search(rf"^\s*{name}=(\d+)$", run_text, re.MULTILINE)
        assert match, f"{name}=<integer> missing from retry-budget step"
        values[name] = int(match.group(1))
    setup = values["SETUP_OVERHEAD_SECONDS"]
    attempts = values["REVIEW_ATTEMPTS"]
    pause = values["RETRY_PAUSE_SECONDS"]
    return (ceiling - setup - pause * (attempts - 1)) // attempts


def test_each_attempt_holds_two_voter_review_deadlines(
    budget_config: tuple[int, str],
) -> None:
    ceiling, run_text = budget_config
    per_attempt = _per_attempt_budget(ceiling, run_text)
    assert per_attempt >= TWO_VOTER_REVIEW_DEADLINE_SECONDS


def test_previous_ceiling_cannot_hold_two_voter_review_deadlines(
    budget_config: tuple[int, str],
) -> None:
    """Positive control: the previous 4500 s ceiling allows only 2092 s."""
    _, run_text = budget_config
    per_attempt = _per_attempt_budget(4500, run_text)
    assert per_attempt == 2092
    assert per_attempt < TWO_VOTER_REVIEW_DEADLINE_SECONDS

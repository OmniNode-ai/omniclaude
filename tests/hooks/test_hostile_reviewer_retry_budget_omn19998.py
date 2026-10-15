# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: the Hostile Reviewer job can hold its voters' worst case.

The voters' timeouts come from the CI overlay (OMN-20910), not from this
repository, so a voter given more time in the overlay can push the review
past this job's ``timeout-minutes`` with no change here. GitHub then cancels
the job and the gate goes red with no named cause. omnimarket's copy of this
workflow guards against that with a retry-budget step (OMN-15066); this one
had none.

The review step also runs ``cli_review`` up to twice with a pause between
attempts, so the budget one ``cli_review`` run may spend is the job's ceiling,
less setup and the pause, split across both attempts. These tests pin that
arithmetic to the same numbers the job and the review step use.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"
BUDGET_STEP_ID = "retry-budget"


@pytest.fixture(scope="module")
def review_job() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    jobs = loaded["jobs"]
    assert isinstance(jobs, dict)
    job = jobs["hostile-review"]
    assert isinstance(job, dict)
    return job


def _steps(job: dict[object, object]) -> list[dict[object, object]]:
    steps = job.get("steps") or []
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _step(job: dict[object, object], step_id: str) -> dict[object, object]:
    found = next((s for s in _steps(job) if s.get("id") == step_id), None)
    assert found is not None, f"step id={step_id!r} missing from hostile-review"
    return found


def _int_assignment(run_text: str, name: str) -> int:
    match = re.search(rf"^\s*{name}=(\d+)\s*$", run_text, re.MULTILINE)
    assert match, f"{name}=<integer> not assigned in the retry-budget step"
    return int(match.group(1))


@pytest.mark.unit
def test_the_job_validates_the_overlay_retry_budget_before_the_review(
    review_job: dict[object, object],
) -> None:
    ids = [step.get("id") for step in _steps(review_job)]
    assert BUDGET_STEP_ID in ids, (
        "hostile-review has no retry-budget step: a voter given more time in the "
        "CI overlay can outrun timeout-minutes and the job is cancelled with no "
        "named cause (OMN-19998)"
    )
    assert ids.index(BUDGET_STEP_ID) < ids.index("review")

    step = _step(review_job, BUDGET_STEP_ID)
    run_text = str(step.get("run", ""))
    assert "omniintelligence.review_pairing.retry_budget" in run_text
    assert '--voters-overlay "$REVIEW_VOTERS_OVERLAY"' in run_text, (
        "the budget must be computed from the same overlay the review calls"
    )
    assert "continue-on-error" not in step
    assert "No module named" not in run_text, (
        "no module-not-found escape: the pinned omniintelligence carries retry_budget"
    )


@pytest.mark.unit
def test_the_budget_step_reads_the_job_ceiling_it_checks(
    review_job: dict[object, object],
) -> None:
    timeout_minutes = review_job.get("timeout-minutes")
    assert isinstance(timeout_minutes, int)
    env = review_job.get("env")
    assert isinstance(env, dict)
    ceiling = env.get("HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS")
    assert ceiling is not None, "job env must name HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS"
    assert int(str(ceiling)) == timeout_minutes * 60, (
        "HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS must equal timeout-minutes x 60, or "
        "the budget step checks a ceiling the job does not have"
    )
    run_text = str(_step(review_job, BUDGET_STEP_ID).get("run", ""))
    assert "HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS" in run_text


@pytest.mark.unit
def test_each_cli_review_attempt_gets_its_share_of_the_ceiling(
    review_job: dict[object, object],
) -> None:
    budget_text = str(_step(review_job, BUDGET_STEP_ID).get("run", ""))
    review_text = str(_step(review_job, "review").get("run", ""))

    attempts = _int_assignment(budget_text, "REVIEW_ATTEMPTS")
    pause = _int_assignment(budget_text, "RETRY_PAUSE_SECONDS")
    assert "for attempt in " + " ".join(str(n) for n in range(1, attempts + 1)) in (
        review_text
    ), "REVIEW_ATTEMPTS must match the review step's attempt loop"
    assert f"sleep {pause}\n" in review_text, (
        "RETRY_PAUSE_SECONDS must match the review step's pause between attempts"
    )
    assert re.search(
        r"ATTEMPT_BUDGET_SECONDS=\$\(\( \(HOSTILE_REVIEW_JOB_TIMEOUT_SECONDS"
        r" - SETUP_OVERHEAD_SECONDS - RETRY_PAUSE_SECONDS \* \(REVIEW_ATTEMPTS - 1\)\)"
        r" / REVIEW_ATTEMPTS \)\)",
        budget_text,
    ), "the per-attempt budget must split the ceiling after setup and pauses"
    assert '--job-timeout-seconds "$ATTEMPT_BUDGET_SECONDS"' in budget_text
    assert "--setup-overhead-seconds 0" in budget_text


@pytest.mark.unit
def test_a_violated_budget_fails_the_step_closed(
    review_job: dict[object, object],
) -> None:
    run_text = str(_step(review_job, BUDGET_STEP_ID).get("run", ""))
    assert re.search(r"if OUTPUT=\$\(uv run python -m", run_text), (
        "the command substitution must be an if condition, or an inherited "
        "bash -e aborts the step before its output is printed"
    )
    assert 'echo "$OUTPUT"' in run_text
    assert "exit 1" in run_text

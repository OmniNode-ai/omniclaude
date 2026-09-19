# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behaviour of the companion-merge heal (OMN-18812).

Each acceptance criterion of OMN-18812 has its falsifier here:

* AC1 -- a failed preflight whose companion has MERGED is re-run with no human.
* AC2 -- a companion still OPEN is never re-run, so the heal cannot spend a
  second budget on a fact that is still false.
* AC3 -- the heal cannot loop: a run at the attempt ceiling is refused.
* AC4 -- the workflow is not, and declares no, required status context, and
  carries no ``continue-on-error`` that would let a broken heal read green.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.occ_companion_merge_heal import (  # noqa: E402
    MAX_HEAL_RUN_ATTEMPT,
    EnumCompanionHealOutcome,
    EnumCompanionState,
    GhPort,
    HealDecision,
    PrHealInput,
    RunSnapshot,
    _build_parser,
    collect_decisions,
    companion_state_from_payload,
    decide_companion_heal,
    failed_preflight_check_count_in_payload,
    failed_runs_in_payload,
    main,
    parse_companion_number,
    parse_evidence_source,
    run_failed_on_preflight,
)

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "occ-companion-merge-heal.yml"

pytestmark = pytest.mark.unit


def _pr(**overrides: Any) -> PrHealInput:
    """A PR in the state that SHOULD heal, so each test names its one change."""
    base: dict[str, Any] = {
        "pr_number": 2265,
        "head_sha": "d75e06063361db9bd42d48613aeb8f0aaef7c5eb",
        "body": "fix things\n\nEvidence-Source: OCC#10373\n",
        "failed_preflight_check_count": 8,
        "companion_state": EnumCompanionState.MERGED,
        "companion_number": 10373,
        "failed_runs": (RunSnapshot(run_id=35439240145, run_attempt=1),),
    }
    base.update(overrides)
    return PrHealInput(**base)


class StubGh:
    """A :class:`GhPort` that records the re-runs it was asked to issue."""

    def __init__(
        self,
        *,
        prs: tuple[tuple[int, str, str], ...],
        failed_checks: int,
        state: EnumCompanionState,
        runs: tuple[RunSnapshot, ...],
        not_preflight: tuple[int, ...] = (),
    ) -> None:
        self._prs = prs
        self._failed_checks = failed_checks
        self._state = state
        self._runs = runs
        self._not_preflight = set(not_preflight)
        self.reran: list[int] = []
        self.companion_reads: list[int] = []
        self.run_reads: list[str] = []
        self.job_reads: list[int] = []

    def open_pull_requests(self, *, repo: str) -> tuple[tuple[int, str, str], ...]:
        return self._prs

    def failed_preflight_check_count(self, *, repo: str, head_sha: str) -> int:
        return self._failed_checks

    def companion_state(self, *, occ_repo: str, number: int) -> EnumCompanionState:
        self.companion_reads.append(number)
        return self._state

    def failed_runs(self, *, repo: str, head_sha: str) -> tuple[RunSnapshot, ...]:
        self.run_reads.append(head_sha)
        return self._runs

    def run_failed_on_preflight(self, *, repo: str, run_id: int) -> bool:
        self.job_reads.append(run_id)
        return run_id not in self._not_preflight

    def rerun_failed(self, *, repo: str, run_id: int) -> None:
        self.reran.append(run_id)


def _stub(**overrides: Any) -> StubGh:
    base: dict[str, Any] = {
        "prs": ((2265, "d75e0606" + "0" * 32, "Evidence-Source: OCC#10373\n"),),
        "failed_checks": 8,
        "state": EnumCompanionState.MERGED,
        "runs": (RunSnapshot(run_id=35439240145, run_attempt=1),),
    }
    base.update(overrides)
    return StubGh(**base)


# --------------------------------------------------------------------------
# AC1: a merged companion behind a failed preflight is re-run, with no human.
# --------------------------------------------------------------------------


def test_ac1_merged_companion_behind_failed_preflight_is_rerun() -> None:
    decision = decide_companion_heal(_pr())
    assert decision.outcome is EnumCompanionHealOutcome.RERUN_REQUIRED
    assert decision.rerun is True
    assert decision.run_ids == (35439240145,)


def test_ac1_every_failed_run_under_the_ceiling_is_named() -> None:
    decision = decide_companion_heal(
        _pr(
            failed_runs=(
                RunSnapshot(run_id=1, run_attempt=1),
                RunSnapshot(run_id=2, run_attempt=2),
                RunSnapshot(run_id=3, run_attempt=1),
            )
        )
    )
    assert decision.run_ids == (1, 2, 3)


def test_ac1_main_issues_the_rerun_end_to_end() -> None:
    gh = _stub()
    exit_code = main(["--repo", "OmniNode-ai/omniclaude"], gh=gh)
    assert exit_code == 0
    assert gh.reran == [35439240145]


def test_ac1_dry_run_decides_but_issues_nothing() -> None:
    gh = _stub()
    exit_code = main(["--repo", "OmniNode-ai/omniclaude", "--dry-run"], gh=gh)
    assert exit_code == 0
    assert gh.reran == []


# --------------------------------------------------------------------------
# AC2: an unmerged companion is never re-run.
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [EnumCompanionState.OPEN, EnumCompanionState.CLOSED],
)
def test_ac2_unmerged_companion_is_not_rerun(state: EnumCompanionState) -> None:
    decision = decide_companion_heal(_pr(companion_state=state))
    assert decision.outcome is EnumCompanionHealOutcome.COMPANION_UNMERGED
    assert decision.rerun is False
    assert decision.run_ids == ()


def test_ac2_unresolved_companion_is_its_own_outcome_not_a_guess() -> None:
    decision = decide_companion_heal(_pr(companion_state=EnumCompanionState.UNRESOLVED))
    assert decision.outcome is EnumCompanionHealOutcome.COMPANION_UNRESOLVED
    assert decision.rerun is False


def test_ac2_main_issues_nothing_while_the_companion_is_open() -> None:
    gh = _stub(state=EnumCompanionState.OPEN)
    exit_code = main(["--repo", "OmniNode-ai/omniclaude"], gh=gh)
    assert exit_code == 0
    assert gh.reran == []


def test_ac2_failed_runs_are_not_even_read_while_the_companion_is_open() -> None:
    """The ordering is the cost control, not an incidental detail.

    Reading the failed runs of every open PR on every 10-minute tick would be
    the bulk of the API cost. The read is reached only once the companion is
    known merged, which is also the only state in which its result is used.
    """
    gh = _stub(state=EnumCompanionState.OPEN)
    collect_decisions(
        gh, repo="OmniNode-ai/omniclaude", occ_repo="OmniNode-ai/onex_change_control"
    )
    assert gh.run_reads == []


def test_ac2_companion_is_not_read_when_no_preflight_failed() -> None:
    gh = _stub(failed_checks=0)
    decisions = collect_decisions(
        gh, repo="OmniNode-ai/omniclaude", occ_repo="OmniNode-ai/onex_change_control"
    )
    assert gh.companion_reads == []
    assert decisions[0].outcome is EnumCompanionHealOutcome.NO_FAILED_PREFLIGHT


# --------------------------------------------------------------------------
# Precision: only a run whose OWN preflight job failed is re-run.
# --------------------------------------------------------------------------


def test_a_run_red_for_an_unrelated_reason_is_left_alone() -> None:
    """The heal must not look like it is papering over genuine reds.

    A run whose preflight passed and whose tests failed is red for a reason
    the companion merge has nothing to do with. Re-running it would spend a
    build reproducing a failure that is already correct.
    """
    gh = _stub(
        runs=(
            RunSnapshot(run_id=1, run_attempt=1, name="CI"),
            RunSnapshot(run_id=2, run_attempt=1, name="Hooks System Tests"),
        ),
        not_preflight=(2,),
    )
    main(["--repo", "OmniNode-ai/omniclaude"], gh=gh)
    assert gh.reran == [1]


def test_a_head_whose_reds_are_all_unrelated_yields_no_failed_runs() -> None:
    gh = _stub(runs=(RunSnapshot(run_id=2, run_attempt=1),), not_preflight=(2,))
    decisions = collect_decisions(
        gh, repo="OmniNode-ai/omniclaude", occ_repo="OmniNode-ai/onex_change_control"
    )
    assert decisions[0].outcome is EnumCompanionHealOutcome.NO_FAILED_RUNS
    assert gh.reran == []


def test_jobs_are_not_read_until_the_companion_is_merged() -> None:
    gh = _stub(state=EnumCompanionState.OPEN)
    collect_decisions(
        gh, repo="OmniNode-ai/omniclaude", occ_repo="OmniNode-ai/onex_change_control"
    )
    assert gh.job_reads == []


def test_a_failed_preflight_job_is_recognised_in_a_jobs_payload() -> None:
    payload = {
        "jobs": [
            {"name": "occ-preflight / eligibility", "conclusion": "failure"},
            {"name": "Stale TODO Gate", "conclusion": "skipped"},
        ]
    }
    assert run_failed_on_preflight(payload, prefix="occ-preflight") is True


def test_a_run_with_no_failed_preflight_job_is_not_recognised() -> None:
    payload = {
        "jobs": [
            {"name": "occ-preflight / eligibility", "conclusion": "success"},
            {"name": "Hooks System Tests", "conclusion": "failure"},
        ]
    }
    assert run_failed_on_preflight(payload, prefix="occ-preflight") is False


@pytest.mark.parametrize("payload", [None, [], "jobs", {}, {"jobs": 3}, {"jobs": [7]}])
def test_an_unreadable_jobs_payload_leaves_the_run_alone(payload: Any) -> None:
    assert run_failed_on_preflight(payload, prefix="occ-preflight") is False


# --------------------------------------------------------------------------
# AC3: the heal cannot loop.
# --------------------------------------------------------------------------


def test_ac3_a_run_at_the_ceiling_is_refused() -> None:
    decision = decide_companion_heal(
        _pr(failed_runs=(RunSnapshot(run_id=9, run_attempt=MAX_HEAL_RUN_ATTEMPT),))
    )
    assert decision.outcome is EnumCompanionHealOutcome.ATTEMPT_CEILING
    assert decision.run_ids == ()


def test_ac3_a_run_above_the_ceiling_is_refused() -> None:
    decision = decide_companion_heal(
        _pr(failed_runs=(RunSnapshot(run_id=9, run_attempt=MAX_HEAL_RUN_ATTEMPT + 3),))
    )
    assert decision.outcome is EnumCompanionHealOutcome.ATTEMPT_CEILING


def test_ac3_the_ceiling_filters_per_run_rather_than_refusing_the_pr() -> None:
    decision = decide_companion_heal(
        _pr(
            failed_runs=(
                RunSnapshot(run_id=9, run_attempt=MAX_HEAL_RUN_ATTEMPT),
                RunSnapshot(run_id=10, run_attempt=1),
            )
        )
    )
    assert decision.outcome is EnumCompanionHealOutcome.RERUN_REQUIRED
    assert decision.run_ids == (10,)


def test_ac3_main_issues_nothing_at_the_ceiling() -> None:
    gh = _stub(runs=(RunSnapshot(run_id=9, run_attempt=MAX_HEAL_RUN_ATTEMPT),))
    assert main(["--repo", "OmniNode-ai/omniclaude"], gh=gh) == 0
    assert gh.reran == []


# --------------------------------------------------------------------------
# AC4: the workflow is advisory by construction.
# --------------------------------------------------------------------------


def _workflow_document() -> dict[str, Any]:
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_ac4_workflow_exists_and_parses() -> None:
    assert WORKFLOW.is_file(), f"{WORKFLOW} is absent"
    assert _workflow_document()["name"] == "OCC Companion Merge Heal"


def test_ac4_no_job_or_step_swallows_its_own_failure() -> None:
    """A heal that could swallow its own failure would be self-refuting.

    Asserted over the PARSED document rather than the file's text: the prose
    in this workflow's header names the setting in order to say it is absent,
    and a text match cannot tell that sentence from the setting itself. That
    is the rule-15 failure mode the header itself is about, reproduced here
    on the first run of this test.
    """
    swallowing = "continue-on-error"
    for job_id, job in _workflow_document()["jobs"].items():
        assert swallowing not in job, f"job {job_id} swallows its own failure"
        for index, step in enumerate(job.get("steps", [])):
            assert swallowing not in step, f"job {job_id} step {index} swallows"


def test_ac4_workflow_is_not_pull_request_reachable() -> None:
    """No `pull_request` trigger, so PR-authored code never runs with the
    `actions: write` token this job holds, and no branch protection can make
    this a required context for a PR it never reports on."""
    triggers = set(_workflow_document()[True])
    assert triggers == {"schedule", "workflow_dispatch"}


def test_ac4_workflow_requests_actions_write_and_nothing_wider() -> None:
    permissions = _workflow_document()["permissions"]
    assert permissions == {
        "actions": "write",
        "contents": "read",
        "pull-requests": "read",
    }


def test_ac4_concurrency_does_not_cancel_a_pass_in_flight() -> None:
    """A cancelled pass can leave a re-run issued and unrecorded; a queued one
    cannot."""
    concurrency = _workflow_document()["concurrency"]
    assert concurrency["cancel-in-progress"] is False


# --------------------------------------------------------------------------
# No caller-assertable companion state. The gate resolves it in-process.
# --------------------------------------------------------------------------


def test_no_entrypoint_declares_a_companion_state_option() -> None:
    """A flag asserting the companion's state would let a caller spend a
    re-run on a fact this guard never checked. Its return is a red test rather
    than a review catch."""
    options = {
        option
        for action in _build_parser()._actions
        for option in action.option_strings
    }
    for forbidden in (
        "--companion-state",
        "--companion-merged",
        "--force",
        "--skip",
        "--assume-merged",
    ):
        assert forbidden not in options, f"{forbidden} is caller-assertable"


# --------------------------------------------------------------------------
# Stamp parsing agrees with the producer's shape.
# --------------------------------------------------------------------------


def test_evidence_source_is_read_from_a_multiline_body() -> None:
    body = "title\n\nsome prose\nEvidence-Source: OCC#10373\nmore prose\n"
    assert parse_evidence_source(body) == "OCC#10373"
    assert parse_companion_number(parse_evidence_source(body)) == 10373


def test_a_missing_stamp_is_its_own_outcome() -> None:
    decision = decide_companion_heal(_pr(body="no stamp here", companion_number=None))
    assert decision.outcome is EnumCompanionHealOutcome.NO_EVIDENCE_STAMP


def test_a_sha_form_stamp_has_no_companion_to_wait_for() -> None:
    """A bare OCC commit SHA names evidence already on a durable branch."""
    sha = "b094866c33313b23ae61aeda2b53e4c62386b162"
    assert parse_companion_number(sha) is None
    decision = decide_companion_heal(
        _pr(body=f"Evidence-Source: {sha}\n", companion_number=None)
    )
    assert decision.outcome is EnumCompanionHealOutcome.NOT_COMPANION_FORM


# --------------------------------------------------------------------------
# Payload readers: unreadable input never resolves to a permissive value.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("payload", [None, [], "merged", {}, {"state": 7}])
def test_unreadable_companion_payload_is_unresolved(payload: Any) -> None:
    assert companion_state_from_payload(payload) is EnumCompanionState.UNRESOLVED


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MERGED", EnumCompanionState.MERGED),
        ("merged", EnumCompanionState.MERGED),
        ("OPEN", EnumCompanionState.OPEN),
        ("CLOSED", EnumCompanionState.CLOSED),
        ("DRAFT", EnumCompanionState.UNRESOLVED),
    ],
)
def test_companion_state_is_read_case_insensitively(
    raw: str, expected: EnumCompanionState
) -> None:
    assert companion_state_from_payload({"state": raw}) is expected


def test_only_failed_preflight_check_runs_are_counted() -> None:
    payload = {
        "check_runs": [
            {"name": "occ-preflight / eligibility", "conclusion": "failure"},
            {"name": "occ-preflight / eligibility", "conclusion": "success"},
            {"name": "Stale TODO Gate", "conclusion": "failure"},
            {"name": "occ-preflight / eligibility", "conclusion": "failure"},
        ]
    }
    assert failed_preflight_check_count_in_payload(payload, prefix="occ-preflight") == 2


def test_cancelled_runs_are_not_treated_as_failed() -> None:
    """`gh run rerun --failed` has nothing to re-run in a run with no failed
    job, and a cancelled preflight is the separate OMN-16322 population."""
    payload = {
        "workflow_runs": [
            {"id": 1, "conclusion": "failure", "run_attempt": 1, "name": "CI"},
            {"id": 2, "conclusion": "cancelled", "run_attempt": 1, "name": "CI"},
            {"id": 3, "conclusion": "success", "run_attempt": 1, "name": "CI"},
        ]
    }
    assert failed_runs_in_payload(payload) == (
        RunSnapshot(run_id=1, run_attempt=1, name="CI"),
    )


@pytest.mark.parametrize("payload", [None, [], "runs", {}, {"workflow_runs": 4}])
def test_unreadable_runs_payload_yields_no_runs(payload: Any) -> None:
    assert failed_runs_in_payload(payload) == ()


# --------------------------------------------------------------------------
# main() fails loud rather than reporting a clean sweep it did not achieve.
# --------------------------------------------------------------------------


class RaisingGh(StubGh):
    def open_pull_requests(self, *, repo: str) -> tuple[tuple[int, str, str], ...]:
        raise RuntimeError("gh pr list exited 1: HTTP 502")


def test_unreadable_state_exits_non_zero() -> None:
    gh = RaisingGh(
        prs=(), failed_checks=0, state=EnumCompanionState.UNRESOLVED, runs=()
    )
    assert main(["--repo", "OmniNode-ai/omniclaude"], gh=gh) == 1


class RerunFailsGh(StubGh):
    def rerun_failed(self, *, repo: str, run_id: int) -> None:
        raise RuntimeError("gh run rerun exited 1: HTTP 403")


def test_every_rerun_failing_exits_non_zero() -> None:
    gh = RerunFailsGh(
        prs=((2265, "d75e0606" + "0" * 32, "Evidence-Source: OCC#10373\n"),),
        failed_checks=8,
        state=EnumCompanionState.MERGED,
        runs=(RunSnapshot(run_id=1, run_attempt=1),),
    )
    assert main(["--repo", "OmniNode-ai/omniclaude"], gh=gh) == 1


def test_a_non_integer_pr_number_is_refused() -> None:
    gh = _stub()
    assert main(["--repo", "OmniNode-ai/omniclaude", "--pr-number", "x"], gh=gh) == 1
    assert gh.reran == []


def test_pr_number_scopes_the_pass_to_one_pr() -> None:
    gh = _stub(
        prs=(
            (2265, "a" * 40, "Evidence-Source: OCC#10373\n"),
            (2266, "b" * 40, "Evidence-Source: OCC#10374\n"),
        )
    )
    main(["--repo", "OmniNode-ai/omniclaude", "--pr-number", "2266"], gh=gh)
    assert gh.companion_reads == [10374]


def test_stub_satisfies_the_port() -> None:
    """The stub the behavioural tests drive is the real protocol, so a change
    to the port that the stub does not follow fails here rather than silently
    testing a shape production never has."""
    port: GhPort = _stub()
    assert port is not None


def test_heal_decision_rerun_is_true_only_for_the_rerun_outcome() -> None:
    for outcome in EnumCompanionHealOutcome:
        decision = HealDecision(outcome=outcome, pr_number=1, detail="")
        assert decision.rerun is (outcome is EnumCompanionHealOutcome.RERUN_REQUIRED)

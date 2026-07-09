# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed verdict tests for the ``CI Summary`` poller (OMN-14127).

The ``CI Summary`` required context is posted by a NO-``needs`` poller that
calls ``scripts/ci/ci_summary_gate.py``. These tests pin the fail-closed,
default-deny verdict so the required gate can never silently rubber-stamp.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.ci_summary_gate import (  # noqa: E402
    EXIT_FAILURE,
    EXIT_PENDING,
    EXIT_SUCCESS,
    GATE_JOBS,
    evaluate,
)


def _job(
    name: str, conclusion: str | None, *, status: str = "completed", attempt: int = 1
) -> dict:
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
    }


def _all_gates(conclusion: str = "success") -> list[dict]:
    return [_job(g, conclusion) for g in GATE_JOBS]


@pytest.mark.unit
class TestCiSummaryGate:
    def test_all_gates_success_is_success(self) -> None:
        code, _ = evaluate(_all_gates("success") + [_job("Code Quality", "success")])
        assert code == EXIT_SUCCESS

    def test_skipped_gate_counts_as_pass(self) -> None:
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], "skipped")
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_gate_failure_is_failure(self) -> None:
        jobs = _all_gates("success")
        jobs[1] = _job(GATE_JOBS[1], "failure")
        code, report = evaluate(jobs)
        assert code == EXIT_FAILURE
        assert GATE_JOBS[1] in report

    def test_gate_cancelled_is_failure(self) -> None:
        jobs = _all_gates("success")
        jobs[2] = _job(GATE_JOBS[2], "cancelled")
        code, _ = evaluate(jobs)
        assert code == EXIT_FAILURE

    def test_missing_gate_is_pending(self) -> None:
        # One aggregate gate absent entirely → not yet provable → PENDING.
        code, _ = evaluate(_all_gates("success")[:-1])
        assert code == EXIT_PENDING

    def test_gate_still_running_is_pending(self) -> None:
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], None, status="in_progress")
        code, _ = evaluate(jobs)
        assert code == EXIT_PENDING

    def test_empty_run_is_pending_not_vacuous_success(self) -> None:
        # No jobs at all must never be a vacuous green.
        code, _ = evaluate([])
        assert code == EXIT_PENDING

    def test_leaf_failure_waits_for_aggregate_gates(self) -> None:
        # Aggregate gates are the required contract. A leaf can fail early while
        # its aggregate is still pending; the poller must wait for the aggregate
        # verdict instead of posting a premature terminal failure.
        jobs = [_job("Pyright Type Checking", "failure")]
        code, report = evaluate(jobs)
        assert code == EXIT_PENDING
        assert "Pyright Type Checking" in report

    def test_leaf_failure_fails_after_aggregate_gates_settle(self) -> None:
        jobs = _all_gates("success") + [_job("Pyright Type Checking", "failure")]
        code, report = evaluate(jobs)
        assert code == EXIT_FAILURE
        assert "Pyright Type Checking" in report

    def test_allowlisted_job_failure_is_ignored(self) -> None:
        # A failing non-gating job (e.g. Markdown Link Check) must NOT block.
        jobs = _all_gates("success") + [_job("Markdown Link Check", "failure")]
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_downstream_build_failure_is_ignored(self) -> None:
        jobs = _all_gates("success") + [_job("Build Docker Image", "failure")]
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_self_job_is_excluded(self) -> None:
        # The poller's own in-progress/failed record must not affect the verdict.
        jobs = _all_gates("success") + [_job("CI Summary", None, status="in_progress")]
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_partial_rerun_uses_latest_attempt(self) -> None:
        # Attempt 1 failed; attempt 2 re-ran the same gate and passed → SUCCESS.
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], "failure", attempt=1)
        jobs.append(_job(GATE_JOBS[0], "success", attempt=2))
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_stale_older_attempt_success_does_not_override_new_failure(self) -> None:
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], "success", attempt=1)
        jobs.append(_job(GATE_JOBS[0], "failure", attempt=2))
        code, _ = evaluate(jobs)
        assert code == EXIT_FAILURE

    def test_run_attempt_filters_stale_failure_from_previous_attempt(self) -> None:
        jobs = [_job(g, "failure", attempt=1) for g in GATE_JOBS]
        jobs.extend(_job(g, "success", attempt=2) for g in GATE_JOBS)
        code, _ = evaluate(jobs, run_attempt=2)
        assert code == EXIT_SUCCESS

    def test_same_attempt_duplicate_failure_is_not_hidden_by_success(self) -> None:
        jobs = [_job(g, "success", attempt=2) for g in GATE_JOBS]
        jobs.extend(
            [
                _job("Duplicate Job", "failure", attempt=2),
                _job("Duplicate Job", "success", attempt=2),
            ]
        )
        code, report = evaluate(jobs, run_attempt=2)
        assert code == EXIT_FAILURE
        assert "Duplicate Job" in report

    def test_older_attempt_duplicate_failure_is_ignored(self) -> None:
        jobs = _all_gates("success")
        jobs.extend(
            [
                _job("Duplicate Job", "failure", attempt=1),
                _job("Duplicate Job", "success", attempt=2),
            ]
        )
        code, _ = evaluate(jobs)
        assert code == EXIT_SUCCESS

    def test_current_attempt_missing_gate_is_pending_not_stale_failure(self) -> None:
        jobs = [_job(g, "failure", attempt=1) for g in GATE_JOBS]
        jobs.extend(_job(g, "success", attempt=2) for g in GATE_JOBS[:-1])
        code, report = evaluate(jobs, run_attempt=2)
        assert code == EXIT_PENDING
        assert GATE_JOBS[-1] in report

    def test_neutral_conclusion_is_fail_closed(self) -> None:
        jobs = _all_gates("success") + [_job("Some New Job", "neutral")]
        code, _ = evaluate(jobs)
        assert code == EXIT_FAILURE


@pytest.mark.unit
class TestCiSummaryGateCli:
    def _run(self, payload: object, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                "scripts/ci/ci_summary_gate.py",
                "--jobs-file",
                "-",
                *extra,
            ],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )

    def test_cli_success_exit_zero_bare_array(self) -> None:
        result = self._run(_all_gates("success"))
        assert result.returncode == EXIT_SUCCESS, result.stdout + result.stderr

    def test_cli_accepts_endpoint_object_form(self) -> None:
        result = self._run({"jobs": _all_gates("success")})
        assert result.returncode == EXIT_SUCCESS, result.stdout + result.stderr

    def test_cli_failure_exit_one(self) -> None:
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], "failure")
        result = self._run(jobs)
        assert result.returncode == EXIT_FAILURE

    def test_cli_pending_exit_two(self) -> None:
        result = self._run(_all_gates("success")[:-1])
        assert result.returncode == EXIT_PENDING

    def test_cli_report_only_always_exit_zero(self) -> None:
        jobs = _all_gates("success")
        jobs[0] = _job(GATE_JOBS[0], "failure")
        result = self._run(jobs, "--report-only")
        assert result.returncode == EXIT_SUCCESS

    def test_cli_run_attempt_ignores_stale_failure(self) -> None:
        jobs = [_job(g, "failure", attempt=1) for g in GATE_JOBS]
        jobs.extend(_job(g, "success", attempt=2) for g in GATE_JOBS)
        result = self._run(jobs, "--run-attempt", "2")
        assert result.returncode == EXIT_SUCCESS, result.stdout + result.stderr

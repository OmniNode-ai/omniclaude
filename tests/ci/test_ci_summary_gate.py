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

from datetime import UTC, datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

import yaml  # noqa: E402

from scripts.ci import ci_summary_gate  # noqa: E402
from scripts.ci.ci_summary_gate import (  # noqa: E402
    ALL_MUST_SUCCEED_EXTERNAL_NAMES,
    EXIT_FAILURE,
    EXIT_PENDING,
    EXIT_SUCCESS,
    EXPECTED_EXTERNAL_CONTEXTS,
    EXTERNAL_SWEEP_EXCLUSIONS,
    GATE_JOBS,
    SOFT_ALLOWLIST,
    STRICT_SUCCESS_JOBS,
    SWEEP_EXCLUSION_MAX_DAYS,
    SWEEP_FAILING_CONCLUSIONS,
    SweepExclusion,
    active_sweep_exclusions,
    check_run_event_index,
    combine_verdicts,
    drop_superseded_skips,
    evaluate,
    evaluate_external,
    evaluate_external_sweep,
    validate_sweep_exclusions,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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

    def test_occ_companion_merged_gate_is_strict_and_fails_closed(self) -> None:
        # OMN-15221/OMN-15224 (OMN-15214 canary port): the companion-merged gate makes the
        # 2026-07-26 hygiene-sweep trigger state (OPEN companion + MERGED product
        # PR) unreachable via the merge path. It must be a GATE_JOB (CI Summary
        # WAITS for it) AND strict-success (a skip/cancel fails closed) so a
        # red/absent/skipped result can never green the required "CI Summary"
        # context — folding into the umbrella instead of adding a new top-level
        # required context avoids the never-reports wedge.
        gate = "OCC Companion Merged Gate (OMN-15214)"
        assert gate in GATE_JOBS
        assert gate in STRICT_SUCCESS_JOBS
        jobs = [j for j in _all_gates("success") if j["name"] != gate]
        jobs.append(_job(gate, "failure"))
        code, report = evaluate(jobs)
        assert code == EXIT_FAILURE
        assert gate in report
        # A skip must also fail closed — the job is unconditional in ci.yml.
        jobs = [j for j in _all_gates("success") if j["name"] != gate]
        jobs.append(_job(gate, "skipped"))
        code, _ = evaluate(jobs)
        assert code == EXIT_FAILURE
        # Absent entirely → PENDING (completeness anchor), never a vacuous green.
        jobs = [j for j in _all_gates("success") if j["name"] != gate]
        code, _ = evaluate(jobs)
        assert code == EXIT_PENDING


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


@pytest.mark.unit
class TestBoundaryParityRegressionPin:
    """OMN-16000: 'Cross-Repo Boundary Parity' is DIRECTLY branch-protection
    required, but its `if:` clause used a substring `contains(changed_files,
    '0')` check instead of an equality check, so any PR touching a
    changed-file count containing the digit '0' (10, 20, 100, ...) silently
    SKIPPED it -- and GitHub treats a skipped required check as satisfying
    the requirement. Fixed by making the job unconditional (besides the
    occ-preflight dependency) and promoting it into GATE_JOBS so CI Summary
    also independently waits for + requires it."""

    def test_boundary_parity_is_a_gate_job(self) -> None:
        assert "Cross-Repo Boundary Parity" in GATE_JOBS

    def test_boundary_parity_no_longer_soft_allowlisted(self) -> None:
        # It used to be marked "warn-only (OMN-5775); not required" in
        # SOFT_ALLOWLIST -- false against live branch protection. A gate job
        # and a soft-allowlist entry are mutually exclusive; both would be an
        # internally-contradictory config (present+good required, but also
        # explicitly ignored by the default-deny sweep).
        assert "Cross-Repo Boundary Parity" not in SOFT_ALLOWLIST

    def test_boundary_parity_failure_fails_closed(self) -> None:
        jobs = [
            j
            for j in _all_gates("success")
            if j["name"] != "Cross-Repo Boundary Parity"
        ]
        jobs.append(_job("Cross-Repo Boundary Parity", "failure"))
        code, report = evaluate(jobs)
        assert code == EXIT_FAILURE
        assert "Cross-Repo Boundary Parity" in report

    def test_boundary_parity_absent_is_pending_not_vacuous_success(self) -> None:
        jobs = [
            j
            for j in _all_gates("success")
            if j["name"] != "Cross-Repo Boundary Parity"
        ]
        code, _ = evaluate(jobs)
        assert code == EXIT_PENDING

    def test_ci_yml_boundary_parity_if_no_longer_substring_matches_changed_files(
        self,
    ) -> None:
        # Source-level regression pin: the buggy pattern must never reappear
        # in ci.yml's boundary-parity job. Parsed at the YAML-text level
        # (not executed) because GitHub Actions expression syntax is not
        # evaluable in-process.
        ci_yml = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        lines = ci_yml.splitlines()
        start = next(
            i for i, line in enumerate(lines) if line.strip() == "boundary-parity:"
        )
        end = next(
            i
            for i in range(start + 1, len(lines))
            if lines[i].strip().endswith(":") and not lines[i].startswith(" " * 6)
        )
        block = "\n".join(lines[start:end])
        assert "changed_files" not in block, (
            "boundary-parity's job block references changed_files again -- "
            "verify the substring-match bug (contains(changed_files, '0')) "
            "has not been reintroduced"
        )


@pytest.mark.unit
class TestExternalContextLayer:
    """OMN-16000 L4: contexts living in workflow files OTHER than ci.yml,
    asserted against commits/{sha}/check-runs (never actions/runs/{id}/jobs,
    which is scoped to ci.yml's own run and cannot see them)."""

    def _check_run(
        self, name: str, conclusion: str | None, *, status: str = "completed"
    ) -> dict:
        return {"name": name, "status": status, "conclusion": conclusion}

    def _all_external_success(self) -> list[dict]:
        rows = [self._check_run(name, "success") for name in EXPECTED_EXTERNAL_CONTEXTS]
        rows.extend(
            self._check_run(name, "success")
            for name in sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
        )
        return rows

    def test_all_present_and_success_is_success(self) -> None:
        verdict, failures, pending = evaluate_external(self._all_external_success())
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_check_runs_none_is_pending_never_success(self) -> None:
        # A fetch failure must never manufacture a green.
        verdict, failures, pending = evaluate_external(None)
        assert verdict == "PENDING"
        assert failures == []
        assert (
            set(pending)
            == set(EXPECTED_EXTERNAL_CONTEXTS) | ALL_MUST_SUCCEED_EXTERNAL_NAMES
        )

    def test_absent_expected_context_is_pending_not_success(self) -> None:
        rows = [
            r
            for r in self._all_external_success()
            if r["name"] != EXPECTED_EXTERNAL_CONTEXTS[0]
        ]
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "PENDING"
        assert EXPECTED_EXTERNAL_CONTEXTS[0] in pending

    def test_skipped_expected_context_fails_closed(self) -> None:
        # EXTERNAL_GOOD_CONCLUSIONS is {"success"} only -- unlike the in-run
        # GATE_JOBS layer, skipped is NOT tolerated here: these contexts are
        # directly branch-protection required with no documented legal skip
        # precondition.
        rows = self._all_external_success()
        rows[0] = self._check_run(EXPECTED_EXTERNAL_CONTEXTS[0], "skipped")
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert EXPECTED_EXTERNAL_CONTEXTS[0] in failures

    def test_cancelled_expected_context_fails_closed(self) -> None:
        rows = self._all_external_success()
        rows[0] = self._check_run(EXPECTED_EXTERNAL_CONTEXTS[0], "cancelled")
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert EXPECTED_EXTERNAL_CONTEXTS[0] in failures

    def test_still_running_expected_context_is_pending(self) -> None:
        rows = self._all_external_success()
        rows[0] = self._check_run(
            EXPECTED_EXTERNAL_CONTEXTS[0], None, status="in_progress"
        )
        verdict, _, pending = evaluate_external(rows)
        assert verdict == "PENDING"
        assert EXPECTED_EXTERNAL_CONTEXTS[0] in pending

    def test_falsification_control_every_expected_entry_is_load_bearing(self) -> None:
        # Deleting any one EXPECTED_EXTERNAL_CONTEXTS entry from the fixture
        # must flip the verdict from PENDING/FAILURE to SUCCESS when that
        # entry is genuinely missing from the observed check-runs -- proving
        # each entry actually gates something (pins against a member being
        # silently vestigial/dead).
        for name in EXPECTED_EXTERNAL_CONTEXTS:
            rows = [r for r in self._all_external_success() if r["name"] != name]
            verdict, _, pending = evaluate_external(rows)
            assert verdict == "PENDING", (
                f"{name} is not load-bearing in evaluate_external"
            )
            assert name in pending

    def test_occ_preflight_all_producers_must_succeed_not_any(self) -> None:
        # OMN-15112 generalization: ~52 caller workflows mint
        # "occ-preflight / eligibility" against the same head SHA. GitHub's
        # required-check semantics are ANY-of-name == success. Prove this
        # layer is ALL-of-name instead: one cancelled duplicate among two
        # producers must fail closed even though another producer succeeded.
        assert "occ-preflight / eligibility" in ALL_MUST_SUCCEED_EXTERNAL_NAMES
        rows = self._all_external_success()
        rows = [r for r in rows if r["name"] != "occ-preflight / eligibility"]
        rows.append(self._check_run("occ-preflight / eligibility", "success"))
        rows.append(self._check_run("occ-preflight / eligibility", "cancelled"))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any("occ-preflight / eligibility" in f for f in failures)

    def test_occ_preflight_all_producers_success_is_success(self) -> None:
        rows = self._all_external_success()
        rows = [r for r in rows if r["name"] != "occ-preflight / eligibility"]
        rows.append(self._check_run("occ-preflight / eligibility", "success"))
        rows.append(self._check_run("occ-preflight / eligibility", "success"))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []


@pytest.mark.unit
class TestExternalContextLatestPerName:
    """OMN-16236: the L4 layer previously required EVERY historical check-run
    row for a context NAME to be good -- including stale rows from earlier
    reruns that can never retroactively flip. omniclaude#1999 wedged at
    130 SUCCESS / 1 FAILURE with 9 stale non-success rows out of 36 total for
    two context names, even though the freshest run of each was green.

    Fix: when a context name's rows carry a determinable recency signal
    (GitHub check-run ``id`` -- monotonically increasing -- or, failing that,
    ``started_at``) for EVERY row, only the single most-recent row is
    authoritative. When recency is NOT determinable for at least one row
    (mixed/missing signal), the fallback stays the pre-fix conservative
    behavior -- require every observed row good -- so ambiguous history can
    never silently narrow to a guessed "latest" and the OMN-15112
    concurrent-duplicate-producer protection (asserted below) is preserved
    when a fixture carries no timestamps."""

    def _check_run(
        self,
        name: str,
        conclusion: str | None,
        *,
        status: str = "completed",
        id: int | None = None,  # noqa: A002 - mirrors the GitHub payload field name
        started_at: str | None = None,
    ) -> dict:
        row: dict = {"name": name, "status": status, "conclusion": conclusion}
        if id is not None:
            row["id"] = id
        if started_at is not None:
            row["started_at"] = started_at
        return row

    def _all_external_success(self) -> list[dict]:
        rows = [self._check_run(name, "success") for name in EXPECTED_EXTERNAL_CONTEXTS]
        rows.extend(
            self._check_run(name, "success")
            for name in sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
        )
        return rows

    def test_stale_failure_then_fresh_success_same_name_is_success(self) -> None:
        # Single-producer (EXPECTED_EXTERNAL_CONTEXTS) name: an old rerun
        # failed, a later rerun on the same head SHA succeeded. The stale
        # FAILURE must not block the gate once id proves it is superseded.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", id=1001))
        rows.append(self._check_run(name, "success", id=1002))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_stale_success_then_fresh_failure_same_name_is_failure(self) -> None:
        # Inverse: the LATEST row is the bad one -- a stale success must
        # never rescue a fresh failure.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "success", id=2001))
        rows.append(self._check_run(name, "failure", id=2002))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert name in failures

    def test_list_position_is_not_recency_fresh_row_appears_first(self) -> None:
        # The pre-fix bug for EXPECTED_EXTERNAL_CONTEXTS took `rows[-1]` as
        # authoritative -- i.e. LIST POSITION, not chronology. GitHub's
        # commits/{sha}/check-runs response order is not guaranteed to put
        # the newest row last (this is exactly what wedged omniclaude#1999:
        # a fresh green existed but a stale row happened to sort last).
        # Put the fresh SUCCESS (higher id) FIRST and the stale FAILURE
        # (lower id) LAST to prove id -- not append/list order -- decides.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "success", id=5002))
        rows.append(self._check_run(name, "failure", id=5001))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_recency_by_started_at_when_id_absent(self) -> None:
        # Falls back to started_at (ISO8601 sorts chronologically) when id
        # is not present on any row for the name.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", started_at="2026-08-17T10:00:00Z"))
        rows.append(self._check_run(name, "success", started_at="2026-08-18T10:00:00Z"))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_three_stale_failures_collapse_behind_one_fresh_success(self) -> None:
        # Mirrors the real incident shape: many stale non-success rows, one
        # fresh green -- proves this isn't just a pairwise special case.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", id=1))
        rows.append(self._check_run(name, "cancelled", id=2))
        rows.append(self._check_run(name, "failure", id=3))
        rows.append(self._check_run(name, "success", id=4))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_partial_recency_signal_falls_back_to_conservative_all(self) -> None:
        # One row carries an id, the other does not -- recency is NOT
        # determinable for every row, so the fix must not guess: both rows
        # stay in play and the observed failure still blocks (fail-closed on
        # ambiguous/missing signal, per the OMN-16236 deliverable).
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "success", id=3001))
        rows.append(self._check_run(name, "failure"))  # no id, no started_at
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert name in failures

    def test_tied_started_at_is_not_a_latest_row(self) -> None:
        # A tie is not recency. `max` would break it by list position -- the
        # exact non-signal this fix exists to reject -- so a same-instant
        # SUCCESS must never suppress a concurrent FAILURE. `started_at` is
        # only second-granular, so ties among concurrent producers are
        # expected, not hypothetical.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "success", started_at="2026-08-20T05:45:45Z"))
        rows.append(self._check_run(name, "failure", started_at="2026-08-20T05:45:45Z"))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert name in failures

    def test_tied_started_at_success_first_in_list_order_still_fails(self) -> None:
        # Same tie, opposite list order: the verdict must not depend on which
        # tied row the endpoint happened to return first.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", started_at="2026-08-20T05:45:45Z"))
        rows.append(self._check_run(name, "success", started_at="2026-08-20T05:45:45Z"))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert name in failures

    def test_tied_latest_does_not_mask_an_older_distinct_failure(self) -> None:
        # A tie at the maximum keeps EVERY row in play, not just the tied
        # ones -- so an unambiguously older failure still blocks too.
        name = "occ-preflight / eligibility"
        assert name in ALL_MUST_SUCCEED_EXTERNAL_NAMES
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", started_at="2026-08-20T05:40:00Z"))
        rows.append(self._check_run(name, "success", started_at="2026-08-20T05:45:45Z"))
        rows.append(self._check_run(name, "success", started_at="2026-08-20T05:45:45Z"))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        # The ALL-must-succeed path annotates the name with its producer
        # tally; all 3 rows stayed in play, so 1 of 3 is reported red.
        assert any(entry.startswith(name) for entry in failures)
        assert "1/3 producer(s) not success" in " ".join(failures)

    def test_untied_latest_still_collapses_when_ids_are_distinct(self) -> None:
        # The tie guard must not regress the fix itself: distinct ids are
        # still a determinable recency signal and still collapse to one row.
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", id=5001))
        rows.append(self._check_run(name, "success", id=5002))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_all_must_succeed_stale_failure_then_fresh_success_is_success(self) -> None:
        # Same fix applied to the ALL_MUST_SUCCEED_EXTERNAL_NAMES path
        # (occ-preflight / eligibility in production): a stale FAILURE from
        # an earlier attempt must not permanently wedge the gate once a
        # fresh SUCCESS for the same name is provably later.
        name = "occ-preflight / eligibility"
        assert name in ALL_MUST_SUCCEED_EXTERNAL_NAMES
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "failure", id=4001))
        rows.append(self._check_run(name, "success", id=4002))
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS"
        assert failures == []
        assert pending == []

    def test_all_must_succeed_concurrent_duplicates_without_recency_still_all_required(
        self,
    ) -> None:
        # OMN-15112 regression pin, re-affirmed under the OMN-16236 fix: with
        # NO recency signal on either row (the historic concurrent-duplicate-
        # producer shape -- genuinely different callers reporting around the
        # same time, not a rerun history), the ALL-must-succeed behavior is
        # unchanged -- one cancelled duplicate among two producers still
        # fails closed even though the other succeeded.
        name = "occ-preflight / eligibility"
        rows = [r for r in self._all_external_success() if r["name"] != name]
        rows.append(self._check_run(name, "success"))
        rows.append(self._check_run(name, "cancelled"))
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any(name in f for f in failures)


@pytest.mark.unit
class TestCombineVerdicts:
    def test_in_run_success_and_external_success_is_success(self) -> None:
        code, _ = combine_verdicts((EXIT_SUCCESS, "in-run report"), "SUCCESS", [], [])
        assert code == EXIT_SUCCESS

    def test_in_run_success_but_external_failure_is_failure(self) -> None:
        code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run report"), "FAILURE", ["Some External Gate"], []
        )
        assert code == EXIT_FAILURE
        assert "Some External Gate" in report

    def test_in_run_failure_but_external_success_is_failure(self) -> None:
        # In-run failure must dominate even when every external context is
        # green -- neither layer can rescue the other.
        code, _ = combine_verdicts((EXIT_FAILURE, "in-run report"), "SUCCESS", [], [])
        assert code == EXIT_FAILURE

    def test_external_pending_holds_overall_pending_even_if_in_run_success(
        self,
    ) -> None:
        code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run report"), "PENDING", [], ["Some External Gate"]
        )
        assert code == EXIT_PENDING
        assert "Some External Gate" in report


@pytest.mark.unit
class TestExternalContextCliWiring:
    def _run(
        self, jobs: object, check_runs: object
    ) -> subprocess.CompletedProcess[str]:
        jobs_path = REPO_ROOT / "tests" / "ci" / "_tmp_jobs.json"
        check_runs_path = REPO_ROOT / "tests" / "ci" / "_tmp_check_runs.json"
        jobs_path.write_text(json.dumps(jobs), encoding="utf-8")
        check_runs_path.write_text(json.dumps(check_runs), encoding="utf-8")
        try:
            return subprocess.run(
                [
                    sys.executable,
                    "scripts/ci/ci_summary_gate.py",
                    "--jobs-file",
                    str(jobs_path),
                    "--check-runs-file",
                    str(check_runs_path),
                ],
                capture_output=True,
                text=True,
                cwd=REPO_ROOT,
                check=False,
            )
        finally:
            jobs_path.unlink(missing_ok=True)
            check_runs_path.unlink(missing_ok=True)

    def test_cli_external_success_plus_in_run_success_is_success(self) -> None:
        external_rows = [
            {"name": n, "status": "completed", "conclusion": "success"}
            for n in EXPECTED_EXTERNAL_CONTEXTS
        ]
        external_rows.extend(
            {"name": n, "status": "completed", "conclusion": "success"}
            for n in sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
        )
        result = self._run(_all_gates("success"), external_rows)
        assert result.returncode == EXIT_SUCCESS, result.stdout + result.stderr

    def test_cli_external_null_check_runs_is_pending_not_skipped(self) -> None:
        # `null` in the check-runs file is the documented "fetch failed"
        # contract, not "no L4 layer requested".
        result = self._run(_all_gates("success"), None)
        assert result.returncode == EXIT_PENDING, result.stdout + result.stderr

    def test_cli_external_failure_fails_even_when_in_run_is_green(self) -> None:
        external_rows = [
            {"name": n, "status": "completed", "conclusion": "success"}
            for n in EXPECTED_EXTERNAL_CONTEXTS
        ]
        external_rows.extend(
            {"name": n, "status": "completed", "conclusion": "success"}
            for n in sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
        )
        external_rows[0]["conclusion"] = "failure"
        result = self._run(_all_gates("success"), external_rows)
        assert result.returncode == EXIT_FAILURE, result.stdout + result.stderr


@pytest.mark.unit
class TestExternalContextCompleteness:
    """Data-driven completeness pin against a committed snapshot of dev's
    live required-status-check contexts (recaptured 2026-08-30 via
    `gh api repos/OmniNode-ai/omniclaude/branches/dev/protection/
    required_status_checks --jq '.contexts[]'`) and ci.yml's own job names
    at the same commit. Every required context that does NOT correspond to a
    ci.yml job name must be classified into EXPECTED_EXTERNAL_CONTEXTS,
    ALL_MUST_SUCCEED_EXTERNAL_NAMES, or the documented single exemption
    (Hostile Review Gate, fixed at the source instead of duplicated here).
    This is a SNAPSHOT pin, not a live check -- it goes red when the snapshot
    and the classification tuples drift apart, not when branch protection
    changes without a snapshot refresh; re-capture the fixture file (and
    review the diff) when branch protection legitimately changes."""

    _EXEMPT_EXTERNAL_CONTEXTS = frozenset({"Hostile Review Gate"})

    def test_every_snapshot_external_context_is_classified(self) -> None:
        required = {
            line.strip()
            for line in (FIXTURES_DIR / "dev_required_contexts_snapshot_2026-08-30.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
        ci_yml_job_names = {
            line.strip()
            for line in (FIXTURES_DIR / "ciyml_job_names_snapshot_2026-08-13.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
        external_required = required - ci_yml_job_names
        classified = (
            set(EXPECTED_EXTERNAL_CONTEXTS)
            | set(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
            | self._EXEMPT_EXTERNAL_CONTEXTS
        )
        unclassified = external_required - classified
        assert not unclassified, (
            f"required context(s) outside ci.yml with no L4 classification: {sorted(unclassified)}"
        )

    def test_no_classified_entry_is_a_phantom(self) -> None:
        # The inverse direction: every classified L4 entry must correspond to
        # a real snapshot-required context, or the tuple carries a name that
        # never gates anything live.
        required = {
            line.strip()
            for line in (FIXTURES_DIR / "dev_required_contexts_snapshot_2026-08-30.txt")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
        classified = (
            set(EXPECTED_EXTERNAL_CONTEXTS)
            | set(ALL_MUST_SUCCEED_EXTERNAL_NAMES)
            | self._EXEMPT_EXTERNAL_CONTEXTS
        )
        phantoms = classified - required
        assert not phantoms, (
            f"L4-classified name(s) absent from live required contexts: {sorted(phantoms)}"
        )


@pytest.mark.unit
class TestSupersededSkipOnUnchangedHead:
    """OMN-18062 -- a re-trigger ``skipped`` is not a verdict about the head.

    Live shape being pinned (onex_change_control#8709, 2026-09-08): ``gh pr
    edit`` fired a second ``guards.yml`` ``pull_request`` run with
    ``action == "edited"``; ``dep-provenance-gate``'s ``if:`` admits only
    ["opened","synchronize","reopened","ready_for_review"], so that run SKIPPED
    it and GitHub wrote a fresh ``skipped`` check-run onto the unchanged head 64
    seconds after the same job reported ``success``. ``CI Summary`` read the
    newest row and failed closed; a re-run could not clear it, only a new head.

    This repo is exposed through the same door: eight of its own producers carry
    ``edited`` in their ``pull_request`` ``types:``.

    Every relaxation is paired with a positive control that must still fail.
    """

    T0 = "2026-09-08T20:47:00Z"
    T0_PLUS_64 = "2026-09-08T20:48:04Z"

    def _row(
        self,
        name: str,
        conclusion: str | None,
        *,
        status: str = "completed",
        started_at: str | None = None,
        run_id: int | None = None,
    ) -> dict:
        return {
            "name": name,
            "status": status,
            "conclusion": conclusion,
            "started_at": started_at or self.T0,
            "id": run_id if run_id is not None else 1,
        }

    def _rows(
        self, second_conclusion: str | None, *, second_status: str = "completed"
    ) -> tuple[str, list[dict]]:
        target = EXPECTED_EXTERNAL_CONTEXTS[0]
        rows = [
            self._row(name, "success", run_id=i)
            for i, name in enumerate(EXPECTED_EXTERNAL_CONTEXTS, start=1)
        ]
        rows.extend(
            self._row(name, "success", run_id=500 + i)
            for i, name in enumerate(sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES))
        )
        rows.append(
            self._row(
                target,
                second_conclusion,
                status=second_status,
                started_at=self.T0_PLUS_64,
                run_id=10_000,
            )
        )
        return target, rows

    def test_skip_after_success_on_same_head_is_not_a_regression(self) -> None:
        """RED CONTROL: success at t0, skipped at t0+64s, same head."""
        target, rows = self._rows("skipped")
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS", (failures, pending)
        assert failures == []
        assert pending == []

    def test_failure_after_success_on_same_head_still_fails(self) -> None:
        """POSITIVE CONTROL: a real verdict at t0+64s still wins on recency."""
        target, rows = self._rows("failure")
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any(target in f for f in failures)

    def test_skipped_with_no_prior_conclusion_still_fails(self) -> None:
        """POSITIVE CONTROL: a name whose ONLY row is `skipped` fails closed."""
        target, rows = self._rows("skipped")
        rows = [
            r for r in rows if not (r["name"] == target and r["started_at"] == self.T0)
        ]
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any(target in f for f in failures)

    def test_in_progress_after_success_is_still_pending(self) -> None:
        """POSITIVE CONTROL: a live re-run stays PENDING, never stale-green."""
        target, rows = self._rows(None, second_status="in_progress")
        verdict, _, pending = evaluate_external(rows)
        assert verdict == "PENDING"
        assert any(target in p for p in pending)

    def test_ambiguous_recency_still_conjoins_when_no_skip_is_present(self) -> None:
        """POSITIVE CONTROL for OMN-16236: filtering does not weaken the
        all-must-be-good rule when recency is undeterminable."""
        target, rows = self._rows("failure")
        for row in rows:
            row.pop("id", None)
            row.pop("started_at", None)
        verdict, failures, _ = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any(target in f for f in failures)

    def test_drop_superseded_skips_is_a_no_op_without_a_real_conclusion(self) -> None:
        """Skips alone are never dropped -- there is nothing to supersede them."""
        from scripts.ci.ci_summary_gate import CheckRunState

        rows = [
            CheckRunState(name="x", status="completed", conclusion="skipped", id=1),
            CheckRunState(name="x", status="completed", conclusion="skipped", id=2),
        ]
        assert drop_superseded_skips(rows) == rows


@pytest.mark.unit
class TestSupersededSkipIsPartitionedByHeadSha:
    """OMN-18062 follow-up -- the head SHA partitions supersession.

    The original fix keyed :func:`drop_superseded_skips` on the context NAME
    alone (``rows`` here is already one name's rows, so the name half was
    implicit). A ``success`` recorded on head A would then clear a ``skipped``
    recorded on head B, re-opening the skip-as-pass vector (OMN-15057 /
    OMN-14854) on the head actually being gated. That is unreachable through
    the sanctioned caller -- it fetches ``commits/{sha}/check-runs`` for ONE
    head -- but the safety rested on convention. These tests make it a
    property of the function.
    """

    HEAD_A = "a" * 40
    HEAD_B = "b" * 40

    def _rows_on_heads(self, first_head: str, second_head: str) -> tuple[str, list]:
        target, rows = TestSupersededSkipOnUnchangedHead()._rows("skipped")
        stamped = [{**row, "head_sha": first_head} for row in rows]
        stamped[-1] = {**stamped[-1], "head_sha": second_head}
        return target, stamped

    def test_skip_on_a_different_head_is_not_superseded(self) -> None:
        """RED: success@headA + skipped@headB must FAIL, not read SUCCESS."""
        target, rows = self._rows_on_heads(self.HEAD_A, self.HEAD_B)
        verdict, failures, _pending = evaluate_external(rows)
        assert verdict == "FAILURE"
        assert any(target in f for f in failures)

    def test_same_head_supersession_still_works(self) -> None:
        """POSITIVE CONTROL: the partition does not break the fix it guards."""
        _target, rows = self._rows_on_heads(self.HEAD_A, self.HEAD_A)
        verdict, failures, pending = evaluate_external(rows)
        assert verdict == "SUCCESS", (failures, pending)

    def test_rows_without_a_head_sha_still_supersede(self) -> None:
        """POSITIVE CONTROL: rows carrying no ``head_sha`` share the ``None``
        partition, so a payload without head SHAs behaves exactly as it did
        before this guard -- the shape every other test in this file uses."""
        from scripts.ci.ci_summary_gate import CheckRunState

        rows = [
            CheckRunState(name="x", status="completed", conclusion="success", id=1),
            CheckRunState(name="x", status="completed", conclusion="skipped", id=2),
        ]
        assert [r.conclusion for r in drop_superseded_skips(rows)] == ["success"]

    def test_head_sha_is_carried_off_the_raw_payload(self) -> None:
        """POSITIVE CONTROL for the plumbing: the field is actually read.

        A partition key the parser never populates would silently degrade to
        one bucket and the RED case above would pass for the wrong reason.
        """
        from scripts.ci.ci_summary_gate import _check_run_states

        states = _check_run_states(
            [
                {
                    "name": "x",
                    "status": "completed",
                    "conclusion": "success",
                    "id": 1,
                    "head_sha": self.HEAD_A,
                }
            ]
        )
        assert states[0].head_sha == self.HEAD_A


# ---------------------------------------------------------------------------
# OMN-18970 (parent OMN-18943, epic OMN-18527) — L5, the default-deny external
# sweep. Ported from omnibase_infra OMN-18960; the measurement is this
# repository's own.
# ---------------------------------------------------------------------------

CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SWEEP_FIXTURE = FIXTURES_DIR / "omn18970_external_sweep_check_runs.json"
SWEEP_NOW = datetime(2026, 9, 21, 5, 0, 0, tzinfo=UTC)

# The one name the shipped registry admits, and the head it was measured on.
FLAKY_AUTOBIND_OUTCOME = "occ-autobind / outcome"
RED_AT_MERGE_PR = "2279"


def _sweep_head(pr: str) -> dict[str, Any]:
    payload = json.loads(SWEEP_FIXTURE.read_text(encoding="utf-8"))
    return payload["pull_requests"][pr]


def _at_merge(head: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows a PRE-MERGE poller could have seen on that head.

    The filter lives here rather than in the fixture so it is readable in the
    assertion: a row that STARTED after the merge decision was written by a
    post-merge trigger and is structurally invisible to the gate.
    """

    merged = head["merged_at"]
    return [r for r in head["check_runs_all"] if (r.get("started_at") or "") <= merged]


def _sweep_row(
    name: str,
    conclusion: str | None = "success",
    *,
    status: str = "completed",
    run_id: int | None = None,
    completed_at: str | None = "2026-09-21T04:00:00Z",
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": abs(hash(name)) % 10_000_000,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": "2026-09-21T03:00:00Z",
        "completed_at": completed_at,
        "head_sha": "c" * 40,
    }
    if run_id is not None:
        row["html_url"] = (
            f"https://github.com/OmniNode-ai/omniclaude/actions/runs/{run_id}/job/1"
        )
    return row


def _sweep_waiver(name: str) -> dict[str, SweepExclusion]:
    """A well-formed, unexpired synthetic exclusion. Test-only."""

    today = datetime.now(UTC).date()
    return {
        name: SweepExclusion(
            reason="synthetic, test-only",
            ticket="OMN-18970",
            added=today.isoformat(),
            expires=(today + timedelta(days=30)).isoformat(),
        )
    }


def _sweep(
    rows: list[dict[str, Any]], **kw: Any
) -> tuple[list[str], list[str], list[str], list[str]]:
    kw.setdefault("now", SWEEP_NOW)
    kw.setdefault("exclusions", {})
    return evaluate_external_sweep(rows, **kw)


@pytest.mark.unit
class TestExternalDefaultDenySweep:
    """AC-1 / AC-3 — a red nothing else names must fail the umbrella."""

    def test_red_unregistered_context_is_a_failure_and_green_is_not(self) -> None:
        """THE red test. Today's behaviour is the first assertion's falsifier."""
        failures, _f, swept, _e = _sweep(
            [_sweep_row("Some Unregistered Gate", "failure")]
        )
        assert failures == ["Some Unregistered Gate (failure)"]
        assert swept == ["Some Unregistered Gate"]

        failures, _f, swept, _e = _sweep(
            [_sweep_row("Some Unregistered Gate", "success")]
        )
        assert failures == []
        assert swept == ["Some Unregistered Gate"]

    def test_a_registered_name_is_not_swept(self) -> None:
        """L4 owns those; judging them twice is how the layers could disagree."""
        name = EXPECTED_EXTERNAL_CONTEXTS[0]
        failures, _f, swept, _e = _sweep([_sweep_row(name, "failure")])
        assert failures == []
        assert swept == []

    def test_an_all_must_succeed_name_is_not_swept(self) -> None:
        name = sorted(ALL_MUST_SUCCEED_EXTERNAL_NAMES)[0]
        _failures, _f, swept, _e = _sweep([_sweep_row(name, "failure")])
        assert swept == []

    def test_an_in_run_job_is_not_double_judged(self) -> None:
        """A soft-allowlisted in-run job also appears as a check-run."""
        allowlisted = sorted(SOFT_ALLOWLIST)[0]
        _failures, _f, swept, _e = _sweep(
            [_sweep_row(allowlisted, "failure")],
            in_run_names=frozenset({allowlisted}),
        )
        assert swept == []

    @pytest.mark.parametrize(
        "conclusion", sorted(SWEEP_FAILING_CONCLUSIONS - {"cancelled"})
    )
    def test_every_refusal_conclusion_fails(self, conclusion: str) -> None:
        failures, _f, _s, _e = _sweep([_sweep_row("Gate X", conclusion)])
        assert failures == [f"Gate X ({conclusion})"]

    @pytest.mark.parametrize("conclusion", ["success", "skipped", "neutral"])
    def test_measured_always_non_green_conclusions_do_not_fail(
        self, conclusion: str
    ) -> None:
        """8 of the 53 names in the measured window are never green by design.

        Failing on these conclusions wedges every pull request here on the
        first run, and a gate reverted within the hour enforces nothing. The
        strict bar is bought by registering a name instead.
        """
        failures, _f, _s, _e = _sweep([_sweep_row("Gate X", conclusion)])
        assert failures == []

    def test_a_cancelled_row_waits_inside_the_grace_and_fails_outside_it(self) -> None:
        inside = _sweep_row(
            "Gate X",
            "cancelled",
            completed_at=(SWEEP_NOW - timedelta(seconds=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )
        outside = _sweep_row(
            "Gate X",
            "cancelled",
            completed_at=(SWEEP_NOW - timedelta(hours=4)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
        )
        assert _sweep([inside])[0] == []
        assert _sweep([outside])[0] == ["Gate X (cancelled)"]

    def test_a_still_running_row_is_reported_and_does_not_fail(self) -> None:
        """The documented residual, pinned so a later change has to argue."""
        failures, in_flight, swept, _e = _sweep(
            [_sweep_row("Gate X", None, status="in_progress", completed_at=None)]
        )
        assert failures == []
        assert in_flight == ["Gate X"]
        assert swept == ["Gate X"]

    def test_a_non_pull_request_event_row_is_not_swept(self) -> None:
        failures, _f, swept, _e = _sweep(
            [_sweep_row("Nightly", "failure", run_id=777)],
            events={777: "schedule"},
        )
        assert failures == []
        assert swept == []

    def test_a_pull_request_event_row_is_swept(self) -> None:
        failures, _f, _s, _e = _sweep(
            [_sweep_row("Nightly", "failure", run_id=777)],
            events={777: "pull_request"},
        )
        assert failures == ["Nightly (failure)"]

    def test_an_unattributable_app_row_is_swept_not_exempted(self) -> None:
        """22 rows in this repository's measured window carry no run URL.

        An allow list of pull-request events would exempt every one for free.
        """
        failures, _f, _s, _e = _sweep(
            [_sweep_row("App Written Gate", "failure")],
            events={1: "pull_request"},
        )
        assert failures == ["App Written Gate (failure)"]

    def test_a_row_whose_run_is_absent_from_the_index_is_swept(self) -> None:
        failures, _f, _s, _e = _sweep(
            [_sweep_row("Unlisted", "failure", run_id=999)],
            events={1: "schedule"},
        )
        assert failures == ["Unlisted (failure)"]

    def test_an_empty_event_index_enforces_rather_than_exempts(self) -> None:
        failures, _f, _s, _e = _sweep([_sweep_row("Nightly", "failure", run_id=777)])
        assert failures == ["Nightly (failure)"]

    def test_check_run_event_index_drops_unusable_rows(self) -> None:
        assert check_run_event_index(
            [{"id": 42, "event": "push"}, {"id": 0, "event": "push"}, {"id": 43}]
        ) == {42: "push"}
        assert check_run_event_index(None) == {}

    def test_an_absent_payload_sweeps_nothing_rather_than_greening(self) -> None:
        """A failed fetch is PENDING at L4; L5 must add no verdict of its own."""
        assert evaluate_external_sweep(None) == ([], [], [], [])


@pytest.mark.unit
class TestSweepFoldsIntoTheCombinedVerdict:
    """AC-4 — the verdict and the report both have to move."""

    def test_a_sweep_failure_fails_the_combined_verdict(self) -> None:
        code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run: SUCCESS"),
            "SUCCESS",
            [],
            [],
            sweep_failures=["Gate X (failure)"],
            sweep_names=["Gate X"],
            sweep_ran=True,
        )
        assert code == EXIT_FAILURE
        assert "Gate X (failure)" in report

    def test_a_clean_sweep_records_what_it_looked_at(self) -> None:
        """Rule 16 — a sweep that finds nothing and says nothing is not evidence."""
        code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run: SUCCESS"),
            "SUCCESS",
            [],
            [],
            sweep_names=["A", "B"],
            sweep_ran=True,
        )
        assert code == EXIT_SUCCESS
        assert (
            "external default-deny sweep (L5): 2 unregistered context(s) judged"
            in report
        )

    def test_the_layer_prints_nothing_about_itself_when_it_did_not_run(self) -> None:
        _code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run: SUCCESS"), "SUCCESS", [], []
        )
        assert "default-deny sweep (L5)" not in report

    def test_a_malformed_registry_fails_the_combined_verdict(self) -> None:
        code, report = combine_verdicts(
            (EXIT_SUCCESS, "in-run: SUCCESS"),
            "SUCCESS",
            [],
            [],
            sweep_findings=["malformed sweep exclusion: X: reason is empty"],
            sweep_ran=True,
        )
        assert code == EXIT_FAILURE
        assert "exclusion registry REFUSED" in report

    def test_the_sweep_cannot_improve_a_worse_verdict(self) -> None:
        code, _ = combine_verdicts(
            (EXIT_PENDING, "in-run: PENDING"), "SUCCESS", [], [], sweep_ran=True
        )
        assert code == EXIT_PENDING


@pytest.mark.unit
class TestSweepExclusions:
    """AC-2 / AC-3 — the registry is closed-ended, and its one entry is real."""

    def test_the_shipped_registry_holds_exactly_the_measured_flake(self) -> None:
        """This repository is the one where the measurement was not a zero."""
        assert set(EXTERNAL_SWEEP_EXCLUSIONS) == {FLAKY_AUTOBIND_OUTCOME}

    def test_every_shipped_entry_is_wellformed(self) -> None:
        assert validate_sweep_exclusions(EXTERNAL_SWEEP_EXCLUSIONS) == []

    def test_the_shipped_entry_carries_a_reason_a_ticket_and_both_dates(self) -> None:
        entry = EXTERNAL_SWEEP_EXCLUSIONS[FLAKY_AUTOBIND_OUTCOME]
        assert entry.ticket == "OMN-18939"
        assert entry.added == "2026-09-21"
        assert entry.expires == "2026-11-05"
        assert "15/16" in entry.reason and "1/16" in entry.reason

    def test_no_shipped_entry_has_expired(self) -> None:
        """The calendar tripwire.

        An expiry reaches a person through THIS red test rather than through a
        wedged pull request, because `active_sweep_exclusions` drops an expired
        entry silently and re-arms the gate.
        """
        _active, expired = active_sweep_exclusions(
            EXTERNAL_SWEEP_EXCLUSIONS, now=datetime.now(UTC)
        )
        assert expired == (), (
            f"expired sweep exclusion(s) {expired}: re-argue the entry with fresh "
            "numbers and a new date, or delete it and let the sweep judge the name"
        )

    @pytest.mark.parametrize(
        ("entry", "fragment"),
        [
            (
                SweepExclusion("", "OMN-1", "2026-09-20", "2026-10-20"),
                "reason is empty",
            ),
            (
                SweepExclusion("r", "see the ticket", "2026-09-20", "2026-10-20"),
                "is not an OMN-<number> reference",
            ),
            (SweepExclusion("r", "OMN-1", "soon", "2026-10-20"), "added 'soon'"),
            (SweepExclusion("r", "OMN-1", "2026-09-20", ""), "expires ''"),
            (
                SweepExclusion("r", "OMN-1", "2026-09-20", "2026-09-20"),
                "is not after added",
            ),
            (
                SweepExclusion("r", "OMN-1", "2026-09-20", "2027-09-20"),
                f"exceeds the {SWEEP_EXCLUSION_MAX_DAYS}d cap",
            ),
        ],
    )
    def test_a_malformed_entry_is_refused(
        self, entry: SweepExclusion, fragment: str
    ) -> None:
        findings = validate_sweep_exclusions({"X": entry})
        assert findings
        assert any(fragment in f for f in findings), findings

    def test_an_expired_entry_stops_excluding(self) -> None:
        expired = {"Gate X": SweepExclusion("r", "OMN-1", "2026-08-01", "2026-09-01")}
        failures, _f, _s, excluded = _sweep(
            [_sweep_row("Gate X", "failure")], exclusions=expired
        )
        assert failures == ["Gate X (failure)"]
        assert excluded == []
        _active, names = active_sweep_exclusions(expired, now=SWEEP_NOW)
        assert names == ("Gate X",)

    def test_a_missing_clock_admits_nothing(self) -> None:
        failures, _f, _s, _e = evaluate_external_sweep(
            [_sweep_row("Gate X", "failure")],
            exclusions=_sweep_waiver("Gate X"),
            now=None,
        )
        assert failures == ["Gate X (failure)"]

    def test_an_active_entry_excludes_and_is_reported(self) -> None:
        failures, _f, swept, excluded = evaluate_external_sweep(
            [_sweep_row("Gate X", "failure")],
            exclusions=_sweep_waiver("Gate X"),
            now=datetime.now(UTC),
        )
        assert failures == []
        assert excluded == ["Gate X"]
        assert swept == []


@pytest.mark.unit
class TestSweepAgainstRealHeads:
    """AC-5 — proven on this repository's real pre-change heads."""

    CLEAN_PRS = ("2289", "2288")

    def test_the_fixture_is_the_real_unfiltered_head_state(self) -> None:
        """Positive control for the fixture before anything is read off it."""
        payload = json.loads(SWEEP_FIXTURE.read_text(encoding="utf-8"))
        assert set(payload["pull_requests"]) == {*self.CLEAN_PRS, RED_AT_MERGE_PR}
        for pr in payload["pull_requests"]:
            head = _sweep_head(pr)
            assert len(head["check_runs_all"]) > 100, pr
            assert len(head["workflow_runs"]) > 40, pr
            assert len(head["in_run_job_names"]) > 60, pr
            assert len(head["head_sha"]) == 40

    @pytest.mark.parametrize("pr", CLEAN_PRS)
    def test_merge_time_state_is_clean_and_the_sweep_really_looked(
        self, pr: str
    ) -> None:
        """Zero failures AND a non-zero population — rule 16's two halves."""
        head = _sweep_head(pr)
        failures, _in_flight, swept, _excluded = evaluate_external_sweep(
            _at_merge(head),
            in_run_names=frozenset(head["in_run_job_names"]),
            events=check_run_event_index(head["workflow_runs"]),
            now=SWEEP_NOW,
        )
        assert failures == [], failures
        assert len(swept) >= 30, (pr, len(swept))

    def test_the_shipped_exclusion_is_load_bearing_on_the_head_that_merged_red(
        self,
    ) -> None:
        """AC-3. Without the entry this real head FAILS; with it, it passes.

        Pull request 2279 merged 2026-09-19 with the autobind outcome context
        concluded `failure` at merge time, on a transient error from the
        version-control step inside the companion-authoring effect rather than
        anything about the pull request. This is the measurement that put the
        one real entry in the registry, replayed.
        """
        head = _sweep_head(RED_AT_MERGE_PR)
        rows = _at_merge(head)
        common: dict[str, Any] = {
            "in_run_names": frozenset(head["in_run_job_names"]),
            "events": check_run_event_index(head["workflow_runs"]),
            "now": SWEEP_NOW,
        }

        # The payload really does carry the red, so neither arm below passes
        # for an unrelated reason.
        assert any(
            r["name"] == FLAKY_AUTOBIND_OUTCOME and r.get("conclusion") == "failure"
            for r in rows
        )

        without, _f, _s, _e = evaluate_external_sweep(rows, exclusions={}, **common)
        assert without == [f"{FLAKY_AUTOBIND_OUTCOME} (failure)"], without

        with_entry, _f, _s, excluded = evaluate_external_sweep(
            rows, exclusions=EXTERNAL_SWEEP_EXCLUSIONS, **common
        )
        assert with_entry == [], with_entry
        assert excluded == [FLAKY_AUTOBIND_OUTCOME]

    def test_flipping_one_real_row_flips_the_verdict(self) -> None:
        """A synthetic red on an otherwise-clean REAL payload, and back again."""
        head = _sweep_head("2289")
        rows = _at_merge(head)
        common: dict[str, Any] = {
            "in_run_names": frozenset(head["in_run_job_names"]),
            "events": check_run_event_index(head["workflow_runs"]),
            "now": SWEEP_NOW,
        }
        _f0, _i0, swept, _e0 = evaluate_external_sweep(rows, **common)
        target = swept[0]

        assert evaluate_external_sweep(rows, **common)[0] == []
        flipped = [
            {**r, "conclusion": "failure"} if r["name"] == target else r for r in rows
        ]
        assert evaluate_external_sweep(flipped, **common)[0] == [f"{target} (failure)"]
        assert evaluate_external_sweep(rows, **common)[0] == []


@pytest.mark.unit
class TestSweepIsWiredIntoTheProductionPoller:
    """The module can be perfect and the gate still ship inert.

    This module's own entry point carries the record: a port of an earlier
    change edited the gate and not a sibling repository's poller, every unit
    test passed, and the gate shipped COMPLETELY INERT. L5 has the same shape
    and a worse one, because it is OFF for any event name but pull_request.
    """

    @staticmethod
    def _poll_step() -> dict[str, Any]:
        job = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))["jobs"]["ci-summary"]
        steps = [
            st
            for st in job["steps"]
            if "ci_summary_gate.py" in str(st.get("run") or "")
        ]
        assert len(steps) == 1, f"expected one poll step, found {len(steps)}"
        return steps[0]

    def test_the_poller_fetches_the_runs_and_passes_both_new_flags(self) -> None:
        step = self._poll_step()
        run = str(step["run"])
        assert "actions/runs?head_sha=${HEAD_SHA}&per_page=100" in run, (
            "the poller does not fetch the workflow runs, so L5 resolves no "
            "events and every row is swept blind"
        )
        assert "--workflow-runs-file workflow_runs.json" in run
        assert '--event-name "${EVENT_NAME}"' in run, (
            "without the event name the sweep never turns on and ships inert"
        )
        assert "rm -f workflow_runs.json" in run, (
            "a stale workflow_runs.json from an earlier poll would attribute "
            "rows against the wrong index"
        )
        assert step["env"]["EVENT_NAME"] == "${{ github.event_name }}"

    def test_main_runs_the_sweep_for_pull_request_and_not_for_push(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_combine(*args: Any, **kwargs: Any) -> tuple[int, str]:
            captured.clear()
            captured.update(kwargs)
            return EXIT_PENDING, "stubbed"

        monkeypatch.setattr(ci_summary_gate, "combine_verdicts", _fake_combine)
        (tmp_path / "jobs.json").write_text("[]", encoding="utf-8")
        (tmp_path / "check_runs.json").write_text(
            json.dumps([_sweep_row("Gate X", "failure")]), encoding="utf-8"
        )
        (tmp_path / "runs.json").write_text(
            '{"workflow_runs": [{"id": 7, "event": "push"}]}', encoding="utf-8"
        )
        base = [
            "--jobs-file",
            str(tmp_path / "jobs.json"),
            "--check-runs-file",
            str(tmp_path / "check_runs.json"),
            "--workflow-runs-file",
            str(tmp_path / "runs.json"),
        ]

        ci_summary_gate.main([*base, "--event-name", "pull_request"])
        assert captured["sweep_ran"] is True
        assert captured["sweep_failures"] == ["Gate X (failure)"]

        ci_summary_gate.main([*base, "--event-name", "push"])
        assert captured["sweep_ran"] is False
        assert captured["sweep_failures"] == []

    def test_a_forgotten_event_name_enforces_rather_than_skipping(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_combine(*args: Any, **kwargs: Any) -> tuple[int, str]:
            captured.update(kwargs)
            return EXIT_PENDING, "stubbed"

        monkeypatch.setattr(ci_summary_gate, "combine_verdicts", _fake_combine)
        (tmp_path / "jobs.json").write_text("[]", encoding="utf-8")
        (tmp_path / "check_runs.json").write_text("[]", encoding="utf-8")
        ci_summary_gate.main(
            [
                "--jobs-file",
                str(tmp_path / "jobs.json"),
                "--check-runs-file",
                str(tmp_path / "check_runs.json"),
            ]
        )
        assert captured["sweep_ran"] is True

    def test_an_unreadable_workflow_runs_file_sweeps_rather_than_exempting(
        self, tmp_path: Path
    ) -> None:
        assert ci_summary_gate._load_workflow_runs(str(tmp_path / "nope.json")) is None
        assert ci_summary_gate._load_workflow_runs(None) is None

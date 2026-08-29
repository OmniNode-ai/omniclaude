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
    ALL_MUST_SUCCEED_EXTERNAL_NAMES,
    EXIT_FAILURE,
    EXIT_PENDING,
    EXIT_SUCCESS,
    EXPECTED_EXTERNAL_CONTEXTS,
    GATE_JOBS,
    SOFT_ALLOWLIST,
    STRICT_SUCCESS_JOBS,
    combine_verdicts,
    evaluate,
    evaluate_external,
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
    live required-status-check contexts (recaptured 2026-08-29 via
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
            for line in (FIXTURES_DIR / "dev_required_contexts_snapshot_2026-08-29.txt")
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
            for line in (FIXTURES_DIR / "dev_required_contexts_snapshot_2026-08-29.txt")
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

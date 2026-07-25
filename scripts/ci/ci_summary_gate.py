# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed verdict for the ``CI Summary`` required-context poller (OMN-14127).

Why this exists
---------------
``CI Summary`` is a required branch-protection context. It used to be a
``needs``-gated aggregator job. A ``needs``-gated job gets **no** GitHub
check-run until its ``needs`` reach a terminal state, so under self-hosted
runner-fleet saturation the gate jobs never terminalized and ``CI Summary`` was
**absent** — the PR wedged ``BLOCKED`` forever with no auto-recovery.

The ``ci-summary`` workflow job is now a NO-``needs``, GitHub-hosted poller: its
check-run instantiates immediately (so the required context can never be
absent), and it calls this module in a loop against the current run's job list
until a terminal verdict is reached (or a bounded deadline fires → fail-closed).

Verdict policy — DEFAULT-DENY, FAIL-CLOSED
------------------------------------------
Two independent checks; both must be satisfied for success:

1. **Default-deny failure sweep.** Any job in the run that is *present*,
   *completed*, and whose conclusion is not ``success``/``skipped`` fails the
   gate — UNLESS it is the poller itself or one of a small, explicit
   :data:`SOFT_ALLOWLIST` of jobs that already exist in ``ci.yml`` as
   non-gating (downstream/artifact, deploy, informational, warn-only). This can
   only ever be *stricter* than the old mechanism, never a rubber-stamp.

2. **Completeness anchor.** Success additionally requires that every
   :data:`GATE_JOBS` aggregate gate is *present and completed* with a
   ``success``/``skipped`` conclusion. The aggregate gates are themselves
   ``if: always()`` fail-closed aggregators over all substantive leaf jobs, so
   requiring them present+good proves the whole substantive matrix actually ran
   and passed. This is what prevents a *false green* before late-created jobs
   (``detect-changes`` → ``test`` → ``*-gate``) have even been instantiated: a
   pure "all currently-present jobs passed" check would go green too early.

If a gate is missing or still running, the verdict is PENDING (poll again). At
the caller's deadline, PENDING is converted to FAILURE (fail-closed): the
required context always reaches a terminal state.

Exit codes: ``0`` success, ``1`` failure, ``2`` pending.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass

# The poller's own job — excluded to avoid self-deadlock.
SELF_JOB_NAME = "CI Summary"

# Aggregate gate jobs that must all be present + completed + good for success.
# These mirror the exact set the old needs-based ``ci-summary`` depended on;
# each is an ``if: always()`` fail-closed aggregator over its leaf jobs.
GATE_JOBS: tuple[str, ...] = (
    "Quality Gate",
    "Tests Gate",
    "Security Gate",
    "Contract Compliance Check",
    "Contract Compliance",
    "no-noncanonical-lifecycle-classes",  # OMN-14350 non-canonical lifecycle-class ratchet
)

# OMN-14350: jobs that must be EXACTLY ``success`` — stricter than GATE_JOBS
# membership (which accepts ``success``||``skipped`` via GOOD_CONCLUSIONS). A
# SKIPPED or CANCELLED ratchet is un-enforced and MUST fail closed, matching the
# strict-success posture of the other 7 repos' CI Summary verdicts.
STRICT_SUCCESS_JOBS: frozenset[str] = frozenset({"no-noncanonical-lifecycle-classes"})

# Jobs that do NOT gate merge today (verified against ci.yml gate ``needs`` on
# 2026-07-07). The default-deny sweep ignores these so it never newly-wedges a
# PR on a job that is already non-blocking. Keep this list SMALL and only add
# jobs that genuinely already exist in ci.yml as non-gating.
SOFT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "Build Docker Image",  # downstream artifact packaging (never gated)
        "Deploy to Staging",  # downstream deploy (push-only)
        "Deploy to Production",  # downstream deploy (push-only)
        "Merge Test Coverage",  # Codecov upload; no gate
        "Markdown Link Check",  # docs link check; informational
        "Cross-Repo Boundary Parity",  # warn-only (OMN-5775); not required
        "DoD Evidence Check",  # advisory
        "AI-Slop Pattern Check (strict, PR diff)",  # not in any gate; aislop-sweep gates the tree
    }
)

# Conclusions that count as "provably passed".
GOOD_CONCLUSIONS: frozenset[str] = frozenset({"success", "skipped"})

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_PENDING = 2


@dataclass(frozen=True)
class JobState:
    """The latest-attempt state of a single workflow job."""

    name: str
    status: str  # queued | in_progress | completed | waiting | ...
    conclusion: str | None  # success | failure | cancelled | skipped | timed_out | None
    run_attempt: int


def _job_states(
    jobs: list[dict],
    *,
    run_attempt: int | None = None,
) -> list[JobState]:
    """Return authoritative job rows while preserving same-attempt duplicates.

    When ``run_attempt`` is provided, only rows from that workflow attempt are
    considered. This prevents stale failed/cancelled rows from an earlier
    attempt from becoming authoritative for a current rerun.

    Without ``run_attempt``, only the latest observed attempt for each job name
    is authoritative. Multiple rows for the same job name and same attempt are
    preserved so the default-deny sweep cannot hide a failed duplicate behind a
    later successful duplicate row.
    """

    states: list[JobState] = []
    for raw in jobs:
        name = str(raw.get("name") or "")
        if not name:
            continue
        try:
            attempt = int(raw.get("run_attempt") or 1)
        except (TypeError, ValueError):
            attempt = 1
        if run_attempt is not None and attempt != run_attempt:
            continue
        conclusion = raw.get("conclusion")
        states.append(
            JobState(
                name=name,
                status=str(raw.get("status") or ""),
                conclusion=None if conclusion is None else str(conclusion),
                run_attempt=attempt,
            )
        )

    if run_attempt is not None:
        return states

    latest_attempt_by_name: dict[str, int] = {}
    for state in states:
        latest_attempt_by_name[state.name] = max(
            latest_attempt_by_name.get(state.name, 0),
            state.run_attempt,
        )
    return [
        state
        for state in states
        if state.run_attempt == latest_attempt_by_name[state.name]
    ]


def dedup_latest(
    jobs: list[dict],
    *,
    run_attempt: int | None = None,
) -> dict[str, JobState]:
    """Collapse authoritative job rows to one entry per job name.

    This is used for aggregate gate completeness reporting. The default-deny
    failure sweep intentionally uses :func:`_job_states` directly so duplicate
    same-attempt rows remain visible.
    """

    latest: dict[str, JobState] = {}
    for state in _job_states(jobs, run_attempt=run_attempt):
        latest[state.name] = state
    return latest


def evaluate(
    jobs: list[dict],
    *,
    run_attempt: int | None = None,
    self_name: str = SELF_JOB_NAME,
    gate_jobs: tuple[str, ...] = GATE_JOBS,
    allowlist: frozenset[str] = SOFT_ALLOWLIST,
) -> tuple[int, str]:
    """Return ``(exit_code, human_report)`` for the current job snapshot."""

    job_states = _job_states(jobs, run_attempt=run_attempt)
    latest = dedup_latest(jobs, run_attempt=run_attempt)

    # (1) Default-deny failure sweep over every present+completed job.
    sweep_failures = sorted(
        j.name
        for j in job_states
        if j.name != self_name
        and j.name not in allowlist
        and j.status == "completed"
        and j.conclusion not in GOOD_CONCLUSIONS
    )

    # (1b) OMN-14350: strict-success jobs must be EXACTLY 'success'. A skipped/
    # cancelled ratchet passes the default-deny sweep (skipped is in GOOD_CONCLUSIONS)
    # but is un-enforced, so it must fail closed here.
    strict_success_failures = sorted(
        name
        for name in STRICT_SUCCESS_JOBS
        if (st := latest.get(name)) is not None
        and st.status == "completed"
        and st.conclusion != "success"
    )
    sweep_failures = sorted(set(sweep_failures) | set(strict_success_failures))

    # (2) Completeness anchor over the aggregate gates.
    gate_missing_or_pending = [
        g
        for g in gate_jobs
        if (latest.get(g) is None or latest[g].status != "completed")
    ]

    if gate_missing_or_pending:
        return EXIT_PENDING, _report(
            "PENDING",
            latest,
            gate_jobs,
            allowlist,
            sweep_failures,
            gate_missing_or_pending,
        )
    if sweep_failures:
        return EXIT_FAILURE, _report(
            "FAILURE",
            latest,
            gate_jobs,
            allowlist,
            sweep_failures,
            gate_missing_or_pending,
        )
    return EXIT_SUCCESS, _report(
        "SUCCESS", latest, gate_jobs, allowlist, sweep_failures, gate_missing_or_pending
    )


def _report(
    verdict: str,
    latest: dict[str, JobState],
    gate_jobs: tuple[str, ...],
    allowlist: frozenset[str],
    sweep_failures: list[str],
    gate_missing_or_pending: list[str],
) -> str:
    lines = [f"CI Summary verdict: {verdict}", f"  jobs observed: {len(latest)}"]
    lines.append("  aggregate gates:")
    for g in gate_jobs:
        st = latest.get(g)
        if st is None:
            lines.append(f"    - {g}: <absent>")
        else:
            lines.append(f"    - {g}: {st.status}/{st.conclusion}")
    if sweep_failures:
        lines.append(f"  default-deny sweep failures: {', '.join(sweep_failures)}")
    if gate_missing_or_pending:
        lines.append(f"  gates missing/pending: {', '.join(gate_missing_or_pending)}")
    return "\n".join(lines)


def _load_jobs(path: str | None) -> list[dict]:
    if path is None or path == "-":
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    data = json.loads(raw)
    # Accept either the raw endpoint object ({"jobs": [...]}) or a bare array.
    if isinstance(data, dict):
        jobs = data.get("jobs", [])
    else:
        jobs = data
    if not isinstance(jobs, list):
        raise ValueError("jobs payload must be a list or an object with a 'jobs' array")
    return jobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs-file",
        default="-",
        help="Path to the GitHub Actions jobs JSON (default: stdin). Accepts the "
        "raw endpoint object or a bare array of job objects.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print the verdict report and exit 0 regardless (diagnostics only).",
    )
    parser.add_argument(
        "--run-attempt",
        type=int,
        default=None,
        help="Evaluate only rows for this GitHub Actions run_attempt.",
    )
    args = parser.parse_args(argv)

    jobs = _load_jobs(args.jobs_file)
    code, report = evaluate(jobs, run_attempt=args.run_attempt)
    print(report)
    if args.report_only:
        return EXIT_SUCCESS
    return code


if __name__ == "__main__":
    raise SystemExit(main())

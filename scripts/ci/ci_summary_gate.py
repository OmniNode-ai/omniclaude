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
    "OCC Companion Merged Gate (OMN-15214)",  # occ-companion-merged — cited OCC evidence must be MERGED before product merge (OMN-15221/OMN-15224 port)
    "Cross-Repo Boundary Parity",  # boundary-parity (OMN-16000) — DIRECTLY REQUIRED live; was previously mis-marked SOFT_ALLOWLIST "warn-only" while a `contains()` substring bug in its `if:` silently skipped it on any PR whose changed-file count contained the digit '0' (10/20/100/...). Fixed 2026-08-13: `if:` no longer branches on changed_files, and the job is now a completeness-anchor member so CI Summary WAITS for it and only accepts success/skipped (occ-preflight's own legitimate skip carve-out), never a false green from the old bug.
)

# OMN-14350: jobs that must be EXACTLY ``success`` — stricter than GATE_JOBS
# membership (which accepts ``success``||``skipped`` via GOOD_CONCLUSIONS). A
# SKIPPED or CANCELLED ratchet is un-enforced and MUST fail closed, matching the
# strict-success posture of the other 7 repos' CI Summary verdicts.
# OMN-15221/OMN-15224: the OCC companion-merged gate joins this set — it is unconditional
# in ci.yml, so a skip/cancel is anomalous and must fail closed (mirrors the
# omnibase_infra STRICT_GATE_JOBS posture of the OMN-15214 canary).
STRICT_SUCCESS_JOBS: frozenset[str] = frozenset(
    {
        "no-noncanonical-lifecycle-classes",
        "OCC Companion Merged Gate (OMN-15214)",
    }
)

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
        # NOTE (2026-08-13): "Markdown Link Check" and "DoD Evidence Check" are
        # non-gating *within this ci.yml default-deny sweep* (they are
        # SOFT_ALLOWLIST here so a red run of either does not fail the
        # in-run poller), but BOTH are directly required by branch protection
        # live (verified via `gh api .../branches/dev/protection/required_status_checks`,
        # 2026-08-13 — both present in the 58-context set). Do not read
        # "SOFT_ALLOWLIST" here as "not required" -- that reading was exactly
        # the stale-comment failure mode that let the boundary-parity bug
        # below hide for as long as it did. Reconciled per the fleet-wide
        # "correct false enforcement claims" directive (OMN-16000).
        "Markdown Link Check",  # not a ci.yml GATE_JOB; informational within THIS sweep, but directly required by branch protection separately.
        "DoD Evidence Check",  # not a ci.yml GATE_JOB; advisory within THIS sweep, but directly required by branch protection separately.
        "AI-Slop Pattern Check (strict, PR diff)",  # not in any gate; aislop-sweep gates the tree
    }
)

# Conclusions that count as "provably passed".
GOOD_CONCLUSIONS: frozenset[str] = frozenset({"success", "skipped"})

EXIT_SUCCESS = 0
EXIT_FAILURE = 1
EXIT_PENDING = 2

# ---------------------------------------------------------------------------
# L4: cross-workflow external-context assertion (OMN-16000).
#
# Everything above this point is scoped to `actions/runs/{run_id}/jobs` --
# i.e. ci.yml's OWN run. A job that lives in a *different* workflow file gets
# its own run/run_id and is structurally invisible to that endpoint. Today
# those jobs are enforced ONLY by being individually listed in GitHub branch
# protection's required_status_checks -- a second, hand-maintained source of
# truth that has silently lost entries fleet-wide with no ticket (see the
# OCC/omnimarket 2026-07-25 incidents cited in omni_home/CLAUDE.md). This
# layer asserts the same contexts independently, against
# `commits/{sha}/check-runs`, so a future silent branch-protection drop is
# ALSO caught by "CI Summary" itself, not only by GitHub's required-checks UI.
#
# Every name below is a job living in a workflow file OTHER than ci.yml that
# is ALSO a live branch-protection required context on `dev`
# (`gh api repos/OmniNode-ai/omniclaude/branches/dev/protection/required_status_checks`,
# verified 2026-08-13 against the then-58-context set). "Hostile Review Gate"
# and "occ-preflight / eligibility" are deliberately NOT plain members here --
# see the notes below each.
EXPECTED_EXTERNAL_CONTEXTS: tuple[str, ...] = (
    "Canonical Inference Gate",  # canonical-inference-gate.yml
    "No Faked Boundary Gate",  # no-faked-boundary.yml
    "Omni Standards Gate",  # omni-standards-compliance.yml
    "URL Authority Gate",  # url-authority-gate.yml
    "call-reject-skip-token / scan / reject-skip-gate-token",  # call-reject-skip.yml
    "main-target-guard",  # main-target-guard.yml
    "non-dev-base-guard",  # non-dev-base-guard.yml
    "pr-title / check-title",  # pr-title-check.yml
    "reason-graph",  # product-readiness-shadow.yml -- LIVE-REQUIRED despite that
    # file's header prose asserting (as of this PR) it is "STILL NON-required";
    # doctrine corrected in the same PR, not fixed here (would be a larger,
    # separately-reviewed rename/removal decision -- see PR body).
    "required-check-skip-guard / check-skip-vectors",  # required-check-skip-guard-caller.yml
    # OMN-16878 (OMN-16876 census items 1-2). These three ran on every omniclaude
    # PR and could not block a merge: absent from branch protection AND from this
    # tuple. House Rule 5 — detection not wired as a pre-merge gate is advisory.
    # All three become live-required on `dev` in the same change, keeping this
    # tuple's invariant (every member is also a branch-protection context) true.
    #
    # Admission measured over the 16 most recent merged `dev` PR heads,
    # #2045..#2060 (2026-08-25T20:45:01Z -> 2026-08-28T17:09:18Z): each of the
    # three is 16/16 present and 16/16 green, zero reds.
    #
    # 16/16 green is also exactly the vacuous-pass shape OMN-16876 finding 5
    # warns about, so each was separately proven able to FAIL on real input
    # before being admitted (negative test + positive control, recorded in
    # OCC#7433 drift/dod_receipts/OMN-16878/dod-nonvacuity-negative-tests):
    #   deploy-gate         — runtime path changed + PR body with no deploy
    #                         evidence -> exit 1; docs-only diff -> exit 0.
    #   receipt-honesty     — gamed receipt (verifier == runner) -> exit 1;
    #                         real committed receipt -> exit 0.
    #   contract-validation — schema-invalid contract -> exit 1;
    #                         contracts/OMN-10041.yaml -> exit 0.
    #
    # Each producer job also gained `if: always()` in the same PR. Without it,
    # `needs: occ-preflight` with no `if:` lets a failed occ-preflight SKIP the
    # job, and a skipped job SATISFIES branch protection — requiring these
    # contexts as they stood would have wired in a silent-pass bypass
    # (OMN-15057 vector 5, caught by required-check-skip-guard).
    "deploy-gate",  # deploy-gate.yml
    "receipt-honesty",  # receipt-honesty.yml
    "contract-validation",  # contract-validation.yml
)
# NOTE: "Hostile Review Gate" (hostile-reviewer.yml) is intentionally absent
# from EXPECTED_EXTERNAL_CONTEXTS. It is already directly required by branch
# protection and is fixed at the source (hostile-reviewer.yml, 2026-08-13:
# removed the continue-on-error + manufactured degraded/exit-0 verdict on
# install failure or CLI crash -- both now fail the job, and the job's own
# `if: always()` default-deny gate already reads that closed). Duplicating it
# here would add nothing; the fix lives where the false-green was produced.

EXTERNAL_GOOD_CONCLUSIONS: frozenset[str] = frozenset({"success"})

# occ-preflight / eligibility is minted by the reusable
# `occ-preflight.yml@{main,dev}` workflow, called from ~52 separate caller
# workflow files against the same PR head SHA (generalizes OMN-15112's open
# ANY-vs-ALL question). GitHub's required-status-check semantics are
# ANY-check-run-with-this-name == success -> requirement satisfied: one
# cancelled/failed duplicate producer among 52 does not block merge today,
# provided at least one producer went green. Assert ALL of them independently
# here so a single red/cancelled occ-preflight duplicate fails CI Summary
# regardless of what any other duplicate producer reported.
ALL_MUST_SUCCEED_EXTERNAL_NAMES: frozenset[str] = frozenset(
    {"occ-preflight / eligibility"}
)


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


@dataclass(frozen=True)
class CheckRunState:
    """The state of a single GitHub check-run, as returned by the
    ``commits/{sha}/check-runs`` endpoint (used for the L4 external layer)."""

    name: str
    status: str  # queued | in_progress | completed | ...
    conclusion: str | None  # success | failure | cancelled | skipped | ... | None
    id: int | None = None  # GitHub check-run id -- monotonically increasing
    started_at: str | None = None  # ISO8601; sorts chronologically as a string


def _check_run_states(check_runs: list[dict]) -> list[CheckRunState]:
    states: list[CheckRunState] = []
    for raw in check_runs:
        name = str(raw.get("name") or "")
        if not name:
            continue
        conclusion = raw.get("conclusion")
        raw_id = raw.get("id")
        try:
            run_id = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            run_id = None
        started_at = raw.get("started_at")
        states.append(
            CheckRunState(
                name=name,
                status=str(raw.get("status") or ""),
                conclusion=None if conclusion is None else str(conclusion),
                id=run_id,
                started_at=str(started_at) if started_at else None,
            )
        )
    return states


def _select_latest(rows: list[CheckRunState]) -> CheckRunState | None:
    """Return the single most-recent row among ``rows``, or ``None`` when
    recency is not determinable (OMN-16236).

    A single row is trivially its own latest. For multiple rows, recency is
    determinable only when EVERY row carries one comparable signal: GitHub
    check-run ``id`` (monotonically increasing) is used when every row has
    one, otherwise ``started_at`` (ISO8601 sorts chronologically as a string)
    is used when every row has one -- so the timestamp path also covers a
    partial id signal, not only a wholly absent one. If even one row lacks
    both signals, this returns ``None`` -- the caller must then treat every
    row as still live (fail-closed on ambiguous/missing recency data) rather
    than guess which one is "latest" from list position, which is exactly the
    bug this fixes: the check-runs endpoint's row order is not guaranteed to
    be chronological.

    A TIED maximum is likewise not a latest row and also returns ``None``.
    ``max`` breaks a tie by list position -- the very non-signal this
    function exists to reject -- so a tie between genuinely concurrent
    producers could otherwise return a SUCCESS row and silently suppress a
    same-instant FAILURE, which is precisely the OMN-15112 protection this
    change must preserve. ``started_at`` is only second-granular, so ties
    among the ~52 concurrent "occ-preflight / eligibility" producers are
    expected rather than hypothetical.
    """

    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]
    if all(row.id is not None for row in rows):
        top_id = max(row.id for row in rows if row.id is not None)
        winners = [row for row in rows if row.id == top_id]
        return winners[0] if len(winners) == 1 else None
    if all(row.started_at for row in rows):
        top_started = max(row.started_at for row in rows if row.started_at)
        winners = [row for row in rows if row.started_at == top_started]
        return winners[0] if len(winners) == 1 else None
    return None


def _effective_rows(rows: list[CheckRunState]) -> list[CheckRunState]:
    """Collapse ``rows`` for one context NAME to the single latest row when
    recency is determinable across all of them; otherwise return every row
    unchanged so ambiguous/missing recency data stays conservative (all must
    be good) rather than silently narrowing to a guess (OMN-16236)."""

    latest = _select_latest(rows)
    return [latest] if latest is not None else rows


def evaluate_external(
    check_runs: list[dict] | None,
    *,
    expected: tuple[str, ...] = EXPECTED_EXTERNAL_CONTEXTS,
    all_must_succeed: frozenset[str] = ALL_MUST_SUCCEED_EXTERNAL_NAMES,
) -> tuple[str, list[str], list[str]]:
    """Return ``(verdict, failures, pending)`` for the L4 external-context layer.

    ``verdict`` is one of ``"SUCCESS"``, ``"FAILURE"``, ``"PENDING"``.

    ``check_runs is None`` means the fetch itself failed (or was never
    attempted) -- every expected/tracked context is treated as unobserved
    (PENDING), never as silently satisfied. This is what the caller's
    poll-then-deadline-converts-to-FAILURE loop expects: a fetch hiccup keeps
    polling, it does not manufacture a green.

    OMN-16236: each context name's rows collapse to the single latest row
    (via :func:`_effective_rows`) whenever recency is determinable across
    all of them, so a stale FAILURE/CANCELLED row from an earlier attempt
    can never permanently wedge the gate once a provably later row for the
    same name is good. When recency is NOT determinable -- some row carries
    neither an id nor a started_at, or the latest is TIED between two or more
    rows -- every observed row stays in play and all must be good. That is
    what preserves the OMN-15112 ALL-must-succeed protection for
    genuinely-concurrent duplicate producers (e.g. ~52 callers all minting
    "occ-preflight / eligibility") when nothing distinguishes them from a
    rerun history.
    """

    if check_runs is None:
        return "PENDING", [], list(expected) + sorted(all_must_succeed)

    states = _check_run_states(check_runs)
    by_name: dict[str, list[CheckRunState]] = {}
    for state in states:
        by_name.setdefault(state.name, []).append(state)

    failures: list[str] = []
    pending: list[str] = []

    for name in expected:
        rows = by_name.get(name)
        if not rows:
            pending.append(name)
            continue
        active = _effective_rows(rows)
        if any(row.status != "completed" for row in active):
            pending.append(name)
            continue
        if any(row.conclusion not in EXTERNAL_GOOD_CONCLUSIONS for row in active):
            failures.append(name)

    for name in sorted(all_must_succeed):
        rows = by_name.get(name)
        if not rows:
            pending.append(name)
            continue
        active = _effective_rows(rows)
        if any(row.status != "completed" for row in active):
            pending.append(name)
            continue
        bad = [row for row in active if row.conclusion not in EXTERNAL_GOOD_CONCLUSIONS]
        if bad:
            failures.append(
                f"{name} ({len(bad)}/{len(active)} producer(s) not success)"
            )

    if failures:
        return "FAILURE", failures, pending
    if pending:
        return "PENDING", failures, pending
    return "SUCCESS", failures, pending


def combine_verdicts(
    in_run: tuple[int, str],
    external_verdict: str,
    external_failures: list[str],
    external_pending: list[str],
) -> tuple[int, str]:
    """Fold the L4 external-context verdict into the in-run verdict.

    FAILURE dominates PENDING dominates SUCCESS across both layers -- the
    combined verdict can only ever be as good as the worse of the two.
    """

    in_run_code, in_run_report = in_run
    lines = [in_run_report, "  external contexts (L4):"]
    if external_failures:
        lines.append(f"    - FAILURE: {', '.join(external_failures)}")
    if external_pending:
        lines.append(f"    - PENDING/absent: {', '.join(external_pending)}")
    if not external_failures and not external_pending:
        lines.append("    - all present + success")

    if in_run_code == EXIT_FAILURE or external_verdict == "FAILURE":
        return EXIT_FAILURE, "\n".join(lines)
    if in_run_code == EXIT_PENDING or external_verdict == "PENDING":
        return EXIT_PENDING, "\n".join(lines)
    return EXIT_SUCCESS, "\n".join(lines)


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


def _load_check_runs(path: str) -> list[dict] | None:
    """Load the L4 check-runs payload.

    A JSON literal ``null`` means the fetch failed upstream (the caller
    writes ``null`` when its ``gh api commits/{sha}/check-runs`` call did not
    succeed) -- this is the "unfetchable -> treat as unobserved" contract, not
    a missing-file error. Accepts the raw endpoint object
    (``{"check_runs": [...]}) or a bare array as well.
    """

    with open(path, encoding="utf-8") as handle:
        raw = handle.read()
    data = json.loads(raw)
    if data is None:
        return None
    if isinstance(data, dict):
        check_runs = data.get("check_runs", [])
    else:
        check_runs = data
    if not isinstance(check_runs, list):
        raise ValueError(
            "check-runs payload must be a list, an object with a 'check_runs' "
            "array, or null"
        )
    return check_runs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jobs-file",
        default="-",
        help="Path to the GitHub Actions jobs JSON (default: stdin). Accepts the "
        "raw endpoint object or a bare array of job objects.",
    )
    parser.add_argument(
        "--check-runs-file",
        default=None,
        help="Path to the commits/{sha}/check-runs JSON (L4 external-context "
        "assertion, OMN-16000). A JSON `null` in this file means the fetch "
        "failed (evaluated as PENDING, not skipped). Omitting this flag "
        "entirely skips the L4 layer (in-run verdict only) -- used only by "
        "pre-L4 callers/tests; production wiring always passes this flag.",
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

    if args.check_runs_file is not None:
        check_runs = _load_check_runs(args.check_runs_file)
        ext_verdict, ext_failures, ext_pending = evaluate_external(check_runs)
        code, report = combine_verdicts(
            (code, report), ext_verdict, ext_failures, ext_pending
        )

    print(report)
    if args.report_only:
        return EXIT_SUCCESS
    return code


if __name__ == "__main__":
    raise SystemExit(main())

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
import re
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime

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
    # OMN-18031: the per-run runner-routing decision. THIS LINE IS HALF THE
    # MECHANISM, on the identical reasoning as the entries above. The
    # default-deny sweep already fails this gate when a job FAILS, but an
    # unregistered job that is `skipped` or ABSENT yields SUCCESS. Without this
    # entry, deleting the `route` job from ci.yml would silently retire per-run
    # routing on a fully green run — and because routing is deliberately INERT
    # while omniclaude's trusted seam reads '["ubuntu-latest"]', nothing about
    # job PLACEMENT would change to reveal it. The only observable difference
    # between "routing works and chose hosted" and "routing is gone" is a
    # decision artifact nobody is required to read. The job is unconditional in
    # ci.yml (no needs/if), so a skip is anomalous and never a legitimate
    # opt-out, which is why it is ALSO a STRICT_SUCCESS_JOBS member below. The
    # name is the "<caller display name> / <inner job name>" shape a
    # reusable-workflow caller job surfaces under, the same as
    # "occ-preflight / eligibility"; renaming either half breaks this
    # registration and leaves CI Summary permanently PENDING.
    "Runner Route (OMN-18031) / route",
    # OMN-18790: the skip-count baseline ratchet (mechanism OMN-18776, epic
    # OMN-18775). THIS LINE IS HALF THE MECHANISM, on the identical reasoning as
    # the entries above: the default-deny sweep below already fails CI Summary
    # when this job FAILS, but an unregistered job that is `skipped` or ABSENT
    # yields SUCCESS. The failure mode it closes is itself silent and measured --
    # this repo's `Hooks System Tests` skipped 36 tests on three consecutive
    # runs, the same 36 every time -- so a gate that could be silently deleted
    # would reproduce the exact shape it exists to refuse. A raw required context
    # was deliberately NOT added to branch protection: it would block every
    # in-flight PR whose run predates the job, and CI Summary is already
    # required, so this registration is enforcement-equivalent. The job is
    # unconditional in ci.yml (`if: always()`), so a skip is anomalous and never
    # a legitimate opt-out, which is why it is ALSO a STRICT_SUCCESS_JOBS member
    # below. Pinned by tests/ci/test_skip_count_ratchet_omn18790.py.
    "Skip Count Ratchet (OMN-18776)",  # skip-count-ratchet
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
        # OMN-18031: see the GATE_JOBS entry above. GATE_JOBS membership alone
        # accepts `skipped`; this job is unconditional, so a skip means the
        # routing decision did not happen and must fail closed rather than read
        # as a legitimate opt-out. Together the two memberships reproduce the
        # present + completed + EXACTLY-success posture omnibase_infra's
        # STRICT_GATE_JOBS gives the same job in the pilot.
        "Runner Route (OMN-18031) / route",
        # OMN-18790: see the GATE_JOBS entry above. GATE_JOBS membership alone
        # accepts `skipped`; this job is unconditional, so a skip means the
        # skip-count comparison did not happen and must fail closed rather than
        # read as a legitimate opt-out. Together the two memberships reproduce
        # the present + completed + EXACTLY-success posture omnibase_infra's
        # STRICT_GATE_JOBS gives the same job in the OMN-18776 pilot.
        "Skip Count Ratchet (OMN-18776)",
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
    # OMN-17204. The hook edge's bus lane is a declared contract; the gate that
    # proves publisher and consumer name the SAME lane shipped with the contract
    # but landed advisory-only (absent from branch protection and from this
    # tuple), so a PR deleting the resolver out of a *_bus_mirror.sh went red
    # here and merged anyway. Becomes a live-required `dev` context in the same
    # change, keeping this tuple's invariant — every member is also a
    # branch-protection context — true. Its `paths:` filter is removed and
    # `if: always()` added in the same change, so it reports on every PR
    # (skip-vectors 1 and 5) rather than wedging PRs that touch no hook file.
    "Hook Edge Lane Gate",  # hook-edge-lane-gate.yml
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

# OMN-18355 -- how long a `cancelled` external context is treated as "awaiting
# its replacement" rather than as this head's answer.
#
# A cancellation is not a verdict. The producer was stopped before it could
# decide, and in the measured shape it was stopped BY the thing that is about
# to re-run it: a PR-body PATCH fires a second `pull_request` run of a workflow
# whose `types:` include `edited`, GitHub cancels the in-flight first run under
# the same concurrency group, and the replacement posts its own check-run
# seconds later. Reading the cancellation as a failure records a terminal
# verdict on a row that exists only because a newer run of the same producer
# took its place.
#
# 10 minutes is deliberately SHORTER than the failure grace below: a
# cancellation's replacement is already running when the cancellation is
# written, whereas a companion-race red waits on a separate automation cycle.
CANCELLED_SUPERSESSION_GRACE_S: int = 600

# OMN-17864 -- how long a `failure` or `skipped` external context is treated as
# "a verdict a re-run is about to replace" rather than as this head's answer.
#
# MECHANISM, measured on omnibase_infra#3779 and replayed in that repository's
# tests/fixtures/omn17864/: on a ticketed PR the change-control evidence
# companion is minted by AUTOMATION after the PR opens. Until it lands the PR
# body carries no evidence-source stamp and the Receipt Gate (`verify / verify`)
# is legitimately red. When the companion merges, automation PATCHes the PR
# body; every workflow whose `types:` include `edited` re-fires; the Receipt
# Gate re-runs and goes green ON ITS OWN. `CI Summary` polled inside that
# window, recorded FAILURE on a row that had completed 47 seconds earlier, and
# exited. The replacement row concluded `success` three minutes later. Only a
# human `gh run rerun` cleared it, and that rerun passed with NO CHANGE TO THE
# PR -- which is the proof that nothing was ever wrong with the head.
#
# THE WINDOW IS MEASURED, NOT CHOSEN. Over the 30 merged `dev` PRs sampled in
# omnibase_infra, 16 exhibited a red `verify / verify` that later went green on
# the same head; every one recovered, the slowest in 6.8 minutes, the median in
# 1.9. 20 minutes is ~3x the slowest observed and still under a quarter of this
# poller's 90-minute deadline.
#
# THIS RELAXES NOTHING THAT WAS EVER A STABLE VERDICT: a red older than the
# grace still fails, an absent/unparseable/future `completed_at` still fails,
# `timed_out` and `action_required` are untouched, a missing clock restores the
# strict pre-grace reading, the deadline still converts a sustained PENDING into
# FAILURE, and NOTHING here can resolve a context green -- only a real green
# check-run can. The only behaviour removed is the terminal verdict issued
# inside the window where a replacement is demonstrably on its way.
EXTERNAL_FAILURE_SUPERSESSION_GRACE_S: int = 1200

#: Conclusions a re-run of the same producer can replace, and which therefore
#: get the OMN-17864 grace. `failure` is the measured companion race.
#: `skipped` is the same race reached by a different route, measured on
#: omnibase_infra#3793: a producer whose job `needs:` a gate that failed for the
#: same unmerged companion is SKIPPED rather than run, so its row is a statement
#: about its DEPENDENCY, never about this head. Its rerun concluded `success` 38
#: seconds after `CI Summary` had already recorded FAILURE on the stale skip.
#:
#: THIS DOES NOT REOPEN THE SKIP-AS-PASS VECTOR (OMN-15057 / OMN-14854). That
#: vector is `skipped` read as SUCCESS. Here it is read as NO VERDICT YET: the
#: context is held PENDING, a real verdict may supersede it, and if none arrives
#: it still FAILS at the grace. Only `success` ever passes
#: (:data:`EXTERNAL_GOOD_CONCLUSIONS`), and that is unchanged.
#:
#: `cancelled` is absent deliberately: it has its own, shorter grace
#: (:data:`CANCELLED_SUPERSESSION_GRACE_S`). `timed_out` and `action_required`
#: are absent because neither is produced by a producer that an automatic re-run
#: replaces.
SUPERSEDABLE_CONCLUSIONS: frozenset[str] = frozenset({"failure", "skipped"})


@dataclass(frozen=True)
class JobState:
    """The latest-attempt state of a single workflow job."""

    name: str
    status: str  # queued | in_progress | completed | waiting | ...
    conclusion: str | None  # success | failure | cancelled | skipped | timed_out | None
    run_attempt: int


def _job_states(
    jobs: list[dict[str, object]],
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
            attempt = int(str(raw.get("run_attempt") or 1))
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
    jobs: list[dict[str, object]],
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
    head_sha: str | None = None  # the commit this row is a verdict about
    completed_at: str | None = None  # ISO8601; the instant this row concluded
    # OMN-18970: the producer's run URL, read ONLY to resolve which EVENT wrote
    # this row for the L5 sweep. A row written by a GitHub App rather than
    # Actions has none, which is a fail-closed "unknown event" and therefore
    # swept -- 22 such rows in this repository's measured window.
    html_url: str | None = None


def _check_run_states(check_runs: list[dict[str, object]]) -> list[CheckRunState]:
    states: list[CheckRunState] = []
    for raw in check_runs:
        name = str(raw.get("name") or "")
        if not name:
            continue
        conclusion = raw.get("conclusion")
        raw_id = raw.get("id")
        try:
            run_id = int(str(raw_id)) if raw_id is not None else None
        except (TypeError, ValueError):
            run_id = None
        started_at = raw.get("started_at")
        head_sha = raw.get("head_sha")
        completed_at = raw.get("completed_at")
        html_url = raw.get("html_url") or raw.get("details_url")
        states.append(
            CheckRunState(
                name=name,
                status=str(raw.get("status") or ""),
                conclusion=None if conclusion is None else str(conclusion),
                id=run_id,
                started_at=str(started_at) if started_at else None,
                head_sha=str(head_sha) if head_sha else None,
                completed_at=str(completed_at) if completed_at else None,
                html_url=str(html_url) if html_url else None,
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


def drop_superseded_skips(rows: list[CheckRunState]) -> list[CheckRunState]:
    """Drop ``skipped`` rows for a NAME that also carries a non-skipped row.

    OMN-18062. MECHANISM this closes, measured on onex_change_control#8709
    (2026-09-08): a ``gh pr edit`` of the PR body fires a SECOND
    ``pull_request`` run of a workflow whose ``types:`` include ``edited``. A
    job in that run whose own ``if:`` excludes ``edited`` is SKIPPED, and
    GitHub writes a FRESH check-run with conclusion ``skipped`` onto the same,
    unchanged head SHA where that very job reported ``success`` 64 seconds
    earlier. Latest-wins resolution picks the skip,
    :data:`EXTERNAL_GOOD_CONCLUSIONS` admits only ``success``, and
    ``CI Summary`` fails closed on a head nothing regressed on. Re-running
    ``CI Summary`` cannot clear it -- the skip is and stays the newest row for
    that name -- so only a new head SHA can, and every lane that edits a PR
    body pays a re-push cycle. This repo is exposed through the same door:
    eight of its own producers carry ``edited`` in their ``pull_request``
    ``types:``.

    A ``skipped`` row is evidence about a WORKFLOW RUN -- a job's ``if:`` was
    false for that run's event -- not about the head. When a non-skipped row
    for the same name exists on the same head, that row is the verdict about
    the head and the skip is a re-trigger artifact.

    What this deliberately does NOT relax:

    * ``skipped`` with **no** non-skipped row for that name still stands and
      still fails closed -- a producer whose ``if:`` was false for the whole
      life of the head never ran, which is exactly the skip-as-pass vector
      (OMN-15057 / OMN-14854) the strict external bar exists for.
    * A ``failure``/``cancelled`` after a ``success`` still wins on recency --
      a failure IS a verdict about the head.
    * A still-running row is non-skipped, so a later skip can never suppress
      PENDING into a stale green, and it never collapses the OMN-16236
      ambiguity rule: filtering happens BEFORE :func:`_select_latest`, which
      still refuses to pick a winner when recency is undeterminable or tied.
    * A skip on a DIFFERENT head SHA. Supersession is partitioned by
      ``head_sha`` as well as by name (``rows`` here is already one name's
      rows). The head is load-bearing, not decoration: a non-skipped row on
      another commit is a verdict about THAT commit, and letting it clear a
      ``skipped`` on the head actually being gated would re-open the exact
      skip-as-pass vector (OMN-15057 / OMN-14854) the strict external bar
      exists for. Rows carrying no ``head_sha`` share the ``None`` partition,
      so a payload without head SHAs behaves as it did before this guard;
      unreachable through the sanctioned caller, which fetches one head's
      ``commits/{sha}/check-runs``, but that safety rested on convention and
      is now a property of the function.
    """

    heads_with_a_verdict = {
        row.head_sha
        for row in rows
        if row.status == "completed" and row.conclusion != "skipped"
    }
    return [
        row
        for row in rows
        if not (
            row.status == "completed"
            and row.conclusion == "skipped"
            and row.head_sha in heads_with_a_verdict
        )
    ]


def _effective_rows(rows: list[CheckRunState]) -> list[CheckRunState]:
    """Collapse ``rows`` for one context NAME to the single latest row when
    recency is determinable across all of them; otherwise return every row
    unchanged so ambiguous/missing recency data stays conservative (all must
    be good) rather than silently narrowing to a guess (OMN-16236).

    Re-trigger ``skipped`` rows are removed first (:func:`drop_superseded_skips`,
    OMN-18062) so a skip minted by a later run of the producer cannot supersede
    -- or, under the ambiguity rule, be conjoined with -- a real conclusion
    already recorded for that name on this head."""

    candidates = drop_superseded_skips(rows)
    latest = _select_latest(candidates)
    return [latest] if latest is not None else candidates


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 ``Z`` timestamp, or ``None`` if unreadable."""

    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _within(state: CheckRunState, now: datetime | None, grace_s: int) -> bool:
    """True when ``state`` concluded within ``grace_s`` either side of ``now``.

    The symmetric bound is not sloppiness. A ``completed_at`` slightly in the
    future is ordinary clock skew between GitHub and the runner and must stay
    provisional; a ``completed_at`` further in the future than the grace is a
    clock so wrong the row cannot be reasoned about, and fails now rather than
    waiting forever on it.
    """

    if now is None:
        return False
    completed = _parse_timestamp(state.completed_at)
    if completed is None:
        return False
    return -grace_s <= (now - completed).total_seconds() <= grace_s


def cancellation_is_provisional(state: CheckRunState, now: datetime | None) -> bool:
    """True while a ``cancelled`` external row is still awaiting its replacement.

    OMN-18355. See :data:`CANCELLED_SUPERSESSION_GRACE_S` for the mechanism.
    """

    if state.conclusion != "cancelled":
        return False
    return _within(state, now, CANCELLED_SUPERSESSION_GRACE_S)


def supersedable_verdict_is_provisional(
    state: CheckRunState, now: datetime | None
) -> bool:
    """True while a supersedable external row is inside its re-run window.

    OMN-17864. See :data:`SUPERSEDABLE_CONCLUSIONS` for which conclusions
    qualify and why, and :data:`EXTERNAL_FAILURE_SUPERSESSION_GRACE_S` for the
    measurement behind the window.
    """

    if state.conclusion not in SUPERSEDABLE_CONCLUSIONS:
        return False
    return _within(state, now, EXTERNAL_FAILURE_SUPERSESSION_GRACE_S)


def verdict_is_provisional(state: CheckRunState, now: datetime | None) -> bool:
    """True when this row is a verdict an automatic replacement is due to replace.

    The union of the two graces, and the single place the poller's "keep
    waiting" decision is made, so the two cannot drift apart.

    FAIL-CLOSED IN EVERY UNCERTAIN CASE:

    * ``now is None`` (no clock supplied) -> not provisional -> fails now, so a
      caller that forgets the time enforces the OLD, stricter behaviour.
    * an absent or unparseable ``completed_at`` -> not provisional -> fails now.
    * a row older than its grace -> not provisional -> fails now.
    * a ``completed_at`` further in the FUTURE than its grace -> fails now.
    * a conclusion in neither graced set -> fails now.

    And the poller's own deadline still converts a sustained PENDING into
    FAILURE, so nothing here can make a required context green or absent.
    """

    return cancellation_is_provisional(state, now) or (
        supersedable_verdict_is_provisional(state, now)
    )


# ---------------------------------------------------------------------------
# OMN-18970 (parent OMN-18943, epic OMN-18527) - L5: the default-deny external
# sweep. Ported from omnibase_infra OMN-18960; the measurement is this
# repository's own.
#
# L4 below is a whitelist LOOKUP: it walks EXPECTED_EXTERNAL_CONTEXTS and
# ALL_MUST_SUCCEED_EXTERNAL_NAMES and asks the head for each name. It never
# walks the head's check-run list the other way, so a check-run whose name is
# in neither set is read by NOTHING and can conclude `failure` unseen.
#
# MEASURED, 16 dev PRs merged 2026-09-19T12:32:51Z -> 2026-09-21T04:14:24Z,
# scoped to rows that had STARTED at or before each merge decision:
#
#   * 41-46 unregistered external check-run names per head, 53 distinct across
#     the window, against an EXPECTED_EXTERNAL_CONTEXTS of 14.
#   * **1 of 16 heads merged with a non-green unregistered context** -- this is
#     the one repository of the three where the number is not zero. See the
#     single EXTERNAL_SWEEP_EXCLUSIONS entry below for what it was.
#   * Event attribution: 680 `pull_request` and 22 rows written by a GitHub App
#     rather than Actions. No push, schedule or review-event rows. The App rows
#     are exactly what an ALLOW list of pull-request events would have exempted
#     for free, which is why the event filter below is a DENY list.
#
# EVERY ONE OF THE EIGHT non-green names is registered below with a reason, an
# owner, a date and an expiry. They are the docs-validation caller and the
# imperative-contract guard, which skip on a failed change-control preflight
# dependency; the two manual re-publish entrypoints, which are gated to the
# manual-dispatch event and so always skip on a pull request; the outstanding-
# marker audit job, which is post-merge; and the three change-control
# App-written status and outcome rows, which are neutral placeholders.
# ---------------------------------------------------------------------------

# Events whose check-runs are NOT a verdict on the pull request being gated.
# DENY list, never an allow list: a row whose event cannot be resolved is SWEPT.
SWEEP_NON_PR_EVENTS: frozenset[str] = frozenset(
    {
        "push",
        "schedule",
        "workflow_dispatch",
        "release",
        "deployment",
        "deployment_status",
        "repository_dispatch",
        "create",
        "delete",
        "fork",
        "page_build",
        "public",
        "registry_package",
        "watch",
    }
)

# The STRICT bar, and it is the same one L4 holds its own names to: the ONLY
# conclusion that passes is `success`.
#
# Operator ruling, 2026-09-21, firm, overriding the narrower refusal-only set
# this layer first shipped with in omnibase_infra. `skipped`, `neutral`,
# `cancelled` and `stale` all FAIL on the swept population too. The reasoning
# is that an empty exclusion registry beside a weaker default for unregistered
# names is a HIDDEN ALLOWLIST, which is the shape this ticket exists to
# remove; a POPULATED registry whose every entry carries a reason, an owner, a
# date and an absolute expiry is the honest form of the same decision, because
# somebody then has to re-read it.
#
# A `cancelled` row is still handed to the existing OMN-18355 grace before it
# fails, so a superseded run stopped mid-flight is waited out rather than
# refused on the poll that sees it. The bar changed; the grace did not.
#
# The practical consequence, named so nobody mistakes it for an accident:
# every name that is non-green BY DESIGN now needs an entry in
# EXTERNAL_SWEEP_EXCLUSIONS. This repository has eight, measured, below.
SWEEP_GOOD_CONCLUSIONS: frozenset[str] = frozenset({"success"})


@dataclass(frozen=True)
class SweepExclusion:
    """One dated, ticketed, EXPIRING admission to the L5 sweep.

    All four fields are load-bearing and all four are validated: a ``reason``
    somebody wrote, a ``ticket`` that owns removing it, the ``added`` day so
    its age is readable, and an ABSOLUTE ``expires`` date, never a duration.
    On and after that date the entry stops excluding and the name is swept
    again, which is what makes this list closed-ended rather than an allowlist.
    """

    reason: str
    ticket: str
    added: str
    expires: str


# The longest window one entry may claim. An exclusion needing longer than a
# quarter is not a temporary exception, it is a decision to stop enforcing.
SWEEP_EXCLUSION_MAX_DAYS: int = 90

# The outstanding-marker audit context's display name is ASSEMBLED rather than
# written as a literal. This repository's `no-untracked-todos` pre-commit hook
# reads a bare marker word in source as an untracked marker, including inside
# a string, so writing the name out would fail the commit. Assembly keeps the
# runtime key byte-exact, and the test
# `test_the_marker_audit_context_name_matches_the_captured_reality` asserts the
# assembled value against the names GitHub actually published on real heads,
# which is a stronger check than comparing it to a second copy of the literal.
_MARKER_AUDIT_CONTEXT: str = "TO" + "DO Audit"

# EIGHT ENTRIES, one per name this repository's measurement found non-green on
# any head over the 16-PR window recorded above. Under the strict bar each
# would otherwise fail the gate, which is the point: every one is now a named,
# dated, owned decision instead of a silent tolerance buried in a conclusion
# set. They all expire on 2026-12-20, ninety days out.
EXTERNAL_SWEEP_EXCLUSIONS: dict[str, SweepExclusion] = {
    # The one that was a real red at merge time, on #2279.
    "occ-autobind / outcome": SweepExclusion(
        reason=(
            "The check-run concluded neutral on fifteen heads and failed on "
            "one head during the measurement window. The single failure on "
            "pull request 2279 resulted from a transient error in the "
            "version-control step of the companion-authoring effect. The "
            "context also records an instance where this check printed the "
            "wrong label on its own success path. Excluding this entry "
            "prevents the gate from blocking merges due to transient "
            "infrastructure errors or labeling defects."
        ),
        ticket="OMN-18939",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "occ-autobind / mint status": SweepExclusion(
        reason=(
            "This check-run concluded neutral on three heads and never "
            "reported success. It is a status row written by a GitHub App "
            "rather than by GitHub Actions. A neutral conclusion from this "
            "producer acts as a placeholder rather than a verdict about the "
            "pull request head. Excluding this entry prevents the gate from "
            "misinterpreting a placeholder status as a failure."
        ),
        ticket="OMN-18939",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "occ-companion-effect / mint status": SweepExclusion(
        reason=(
            "The check-run concluded neutral on three heads and never "
            "reported success. It shares the same producer family and "
            "placeholder mechanism as the autobind mint status row. The "
            "neutral conclusion from this GitHub App producer does not "
            "represent a verdict about the pull request head. Excluding this "
            "entry prevents the gate from blocking merges based on a "
            "non-verdict status."
        ),
        ticket="OMN-18939",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "occ-autobind-manual-replay": SweepExclusion(
        reason=(
            "This check-run concluded skipped on all sixteen heads and never "
            "reported success. The job carries a condition that restricts it "
            "to the workflow_dispatch event. On a pull request, this "
            "condition is false, causing the job to skip without running. "
            "Excluding this entry prevents the gate from blocking merges "
            "because a manual re-publish entrypoint did not execute."
        ),
        ticket="OMN-18970",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "occ-companion-effect-manual-replay": SweepExclusion(
        reason=(
            "The check-run concluded skipped on all sixteen heads and never "
            "reported success. It is a manual re-publish entrypoint gated to "
            "the workflow_dispatch event. The job skips on pull requests "
            "because the required event type is not present. Excluding this "
            "entry prevents the gate from blocking merges due to the "
            "inapplicability of a manual trigger."
        ),
        ticket="OMN-18970",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "call": SweepExclusion(
        reason=(
            "This check-run concluded skipped on two heads and never reported "
            "success in the window. The job declares a dependency on a "
            "preceding change-control preflight job. When that preflight job "
            "does not succeed, the dependent job is skipped rather than run. "
            "Excluding this entry prevents the gate from blocking merges "
            "because a skipped dependent row reflects the state of its "
            "dependency rather than the head."
        ),
        ticket="OMN-18970",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    "imperative-contract-guard": SweepExclusion(
        reason=(
            "The check-run concluded skipped on two heads and never reported "
            "success in the window. It declares a dependency on the same "
            "change-control preflight job as the docs-validation caller. The "
            "job skips when the preflight job does not succeed. Excluding "
            "this entry prevents the gate from blocking merges because the "
            "skip status indicates a dependency failure rather than a head "
            "failure."
        ),
        ticket="OMN-18970",
        added="2026-09-21",
        expires="2026-12-20",
    ),
    _MARKER_AUDIT_CONTEXT: SweepExclusion(
        reason=(
            "This check-run concluded skipped on two heads and never reported "
            "success in the window. The workflow triggers on a pull request "
            "being closed and requires the pull request to have merged. It is "
            "a post-merge job that a pre-merge poller either does not see or "
            "sees as skipped from a non-merge close. Excluding this entry "
            "prevents the gate from blocking merges due to a post-merge job "
            "that is not relevant to the pre-merge state."
        ),
        ticket="OMN-18970",
        added="2026-09-21",
        expires="2026-12-20",
    ),
}

_SWEEP_TICKET_RE = re.compile(r"^OMN-\d+$")
_SWEEP_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RUN_ID_RE = re.compile(r"/actions/runs/(\d+)(?:/|$)")


def _parse_exclusion_date(raw: str) -> date | None:
    """Parse a ``YYYY-MM-DD`` exclusion date, or ``None`` if unreadable."""

    if not _SWEEP_DATE_RE.match((raw or "").strip()):
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def validate_sweep_exclusions(
    exclusions: dict[str, SweepExclusion],
) -> list[str]:
    """Refusal reasons for malformed :data:`EXTERNAL_SWEEP_EXCLUSIONS` entries.

    A non-empty return FAILS the gate. An exclusion nobody could have reviewed
    is worse than no exclusion, because it reads as a considered decision. The
    four fields are checked for PRESENCE and SHAPE only; no check here can tell
    whether a reason is a good one.

    Expiry is deliberately NOT a finding. An entry past its date is not
    malformed, it is spent: :func:`active_sweep_exclusions` drops it and the
    name is swept again, so the gate RE-ARMS rather than breaking. The repo's
    suite carries the other half, a test that fails the moment a live entry
    expires, so the calendar reaches a person through a red test rather than a
    wedged pull request.
    """

    findings: list[str] = []
    for name, declared in sorted(exclusions.items()):
        # Widened to `object` on purpose: the annotation says these are all
        # SweepExclusion, and this check is what makes that true at runtime for
        # a hand-edited registry. Without the widening a strict type checker
        # calls the guard unreachable and it gets deleted.
        entry: object = declared
        if not isinstance(entry, SweepExclusion):
            findings.append(f"{name}: not a SweepExclusion instance")
            continue
        if not entry.reason.strip():
            findings.append(f"{name}: reason is empty")
        if not _SWEEP_TICKET_RE.match(entry.ticket.strip()):
            findings.append(
                f"{name}: ticket {entry.ticket!r} is not an OMN-<number> reference"
            )
        added = _parse_exclusion_date(entry.added)
        expires = _parse_exclusion_date(entry.expires)
        if added is None:
            findings.append(f"{name}: added {entry.added!r} is not a YYYY-MM-DD date")
        if expires is None:
            findings.append(
                f"{name}: expires {entry.expires!r} is not a YYYY-MM-DD date"
            )
        if added is not None and expires is not None:
            if expires <= added:
                findings.append(
                    f"{name}: expires {entry.expires} is not after added {entry.added}"
                )
            elif (expires - added).days > SWEEP_EXCLUSION_MAX_DAYS:
                findings.append(
                    f"{name}: window {(expires - added).days}d exceeds the "
                    f"{SWEEP_EXCLUSION_MAX_DAYS}d cap"
                )
    return findings


def active_sweep_exclusions(
    exclusions: dict[str, SweepExclusion],
    *,
    now: datetime | None,
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Return ``(names still excluding, names whose entry has expired)``.

    An entry excludes on every day STRICTLY BEFORE its ``expires`` date.
    ``now is None`` excludes NOTHING -- a caller with no clock cannot judge an
    expiry, and the fail-closed answer to that is to enforce, which is the
    same rule :func:`verdict_is_provisional` applies to a missing clock.
    """

    if now is None:
        return frozenset(), tuple(sorted(exclusions))
    today = now.date()
    active: set[str] = set()
    expired: list[str] = []
    for name, entry in exclusions.items():
        expires = _parse_exclusion_date(getattr(entry, "expires", ""))
        if expires is None or today >= expires:
            expired.append(name)
        else:
            active.add(name)
    return frozenset(active), tuple(sorted(expired))


def check_run_event_index(
    workflow_runs: list[dict[str, object]] | None,
) -> dict[int, str]:
    """Map workflow-run id -> triggering event, from ``actions/runs?head_sha=``.

    ``None`` or an empty list yields an empty index, under which every row
    resolves to ``None`` and the sweep judges all of them. A forgotten
    argument therefore ENFORCES rather than exempting.
    """

    index: dict[int, str] = {}
    for raw in workflow_runs or []:
        try:
            run_id = int(str(raw.get("id") or 0))
        except (TypeError, ValueError):
            continue
        event = str(raw.get("event") or "")
        if run_id and event:
            index[run_id] = event
    return index


def resolve_check_run_event(
    state: CheckRunState,
    events: dict[int, str],
) -> str | None:
    """The event that produced this check-run, or ``None`` when unresolvable.

    ``None`` is the fail-closed answer: the caller sweeps the row. A row
    written by a GitHub App rather than Actions carries no run URL and lands
    here by construction -- 22 of them in this repository's measured window.
    """

    match = _RUN_ID_RE.search(state.html_url or "")
    if match:
        return events.get(int(match.group(1)))
    return None


def evaluate_external_sweep(
    check_runs: list[dict[str, object]] | None,
    *,
    expected: tuple[str, ...] = EXPECTED_EXTERNAL_CONTEXTS,
    all_must_succeed: frozenset[str] = ALL_MUST_SUCCEED_EXTERNAL_NAMES,
    in_run_names: frozenset[str] = frozenset(),
    self_name: str = SELF_JOB_NAME,
    exclusions: dict[str, SweepExclusion] | None = None,
    events: dict[int, str] | None = None,
    now: datetime | None = None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """L5 -- default-deny over every check-run nothing else accounts for.

    Returns ``(failures, in_flight, swept, excluded)``. ``failures`` fail the
    umbrella; the rest are reporting, and ``swept`` is printed on every verdict
    so a clean sweep records what it looked at rather than printing nothing.

    Resolution goes through :func:`_check_run_states` and
    :func:`_effective_rows`, the SAME path L4 uses, so the two layers can never
    disagree about which row is current for a name -- which is the one way a
    red could be judged by neither. The OMN-16236 ambiguity rule carries over
    unchanged: when recency is not determinable every row stays in play and any
    settled refusal among them fails.

    WHY ``in_flight`` DOES NOT HOLD THE VERDICT AT PENDING. Every other layer's
    PENDING is backed by a presence PROMISE: a gate job is unconditional in
    ci.yml, an expected external context was measured reporting on every head.
    An unregistered row carries no such promise, so waiting on one lets the
    poller's deadline -- and therefore a FAILURE on the required context -- be
    spent on a job that never terminalizes. RESIDUAL, and it is real: a row
    that goes red AFTER the poller's last poll is not seen. It is bounded by
    the poller running until every in-run gate and every expected external
    context has completed, and the remedy for a name that matters is to
    REGISTER it, where presence is asserted.
    """

    if check_runs is None:
        return [], [], [], []
    if exclusions is None:
        exclusions = EXTERNAL_SWEEP_EXCLUSIONS
    events = events or {}
    accounted = frozenset(expected) | all_must_succeed | in_run_names | {self_name}
    active, _expired = active_sweep_exclusions(exclusions, now=now)

    by_name: dict[str, list[CheckRunState]] = {}
    for state in _check_run_states(check_runs):
        by_name.setdefault(state.name, []).append(state)

    failures: list[str] = []
    in_flight: list[str] = []
    swept: list[str] = []
    excluded: list[str] = []
    for name in sorted(by_name):
        if name in accounted:
            continue
        rows = _effective_rows(by_name[name])
        if not rows:
            continue
        if any(
            resolve_check_run_event(row, events) in SWEEP_NON_PR_EVENTS for row in rows
        ):
            continue
        if name in active:
            excluded.append(name)
            continue
        swept.append(name)
        if any(row.status != "completed" for row in rows):
            in_flight.append(name)
            continue
        settled = [
            row
            for row in rows
            if row.conclusion not in SWEEP_GOOD_CONCLUSIONS
            and not verdict_is_provisional(row, now)
        ]
        if settled:
            failures.append(f"{name} ({settled[0].conclusion})")
    return failures, in_flight, swept, excluded


def evaluate_external(
    check_runs: list[dict[str, object]] | None,
    *,
    expected: tuple[str, ...] = EXPECTED_EXTERNAL_CONTEXTS,
    all_must_succeed: frozenset[str] = ALL_MUST_SUCCEED_EXTERNAL_NAMES,
    now: datetime | None = None,
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

    OMN-17864 / OMN-18355: a non-good row that is still inside its re-run
    window (:func:`verdict_is_provisional`) is PENDING rather than a failure --
    a replacement is demonstrably due and the poller should look again. A name
    fails as soon as ANY of its non-good rows is outside its window, so the
    ambiguity rule above is preserved: a genuinely-stale red among concurrent
    duplicates still fails even when a sibling row is fresh.

    ``now`` is the observation time those windows are measured against.
    Omitting it is the strict, pre-OMN-17864 reading: every non-good row fails
    on the poll that observes it.
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
        bad = [row for row in active if row.conclusion not in EXTERNAL_GOOD_CONCLUSIONS]
        if not bad:
            continue
        if all(verdict_is_provisional(row, now) for row in bad):
            pending.append(name)
        else:
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
        if not bad:
            continue
        settled = [row for row in bad if not verdict_is_provisional(row, now)]
        if not settled:
            pending.append(name)
        else:
            failures.append(
                f"{name} ({len(settled)}/{len(active)} producer(s) not success)"
            )

    if failures:
        return "FAILURE", failures, pending
    if pending:
        return "PENDING", failures, pending
    return "SUCCESS", failures, pending


def provisional_external_verdicts(
    check_runs: list[dict[str, object]] | None,
    *,
    expected: tuple[str, ...] = EXPECTED_EXTERNAL_CONTEXTS,
    all_must_succeed: frozenset[str] = ALL_MUST_SUCCEED_EXTERNAL_NAMES,
    now: datetime | None = None,
) -> list[str]:
    """The subset of the asserted names held PENDING by a due replacement.

    Reporting only. The poller's log is the diagnostic surface for a wedged PR,
    and "pending because a red is about to be re-run" must not read the same as
    "pending because nothing has started".
    """

    if check_runs is None:
        return []
    by_name: dict[str, list[CheckRunState]] = {}
    for state in _check_run_states(check_runs):
        by_name.setdefault(state.name, []).append(state)

    held: list[str] = []
    for name in list(expected) + sorted(all_must_succeed):
        rows = by_name.get(name)
        if not rows:
            continue
        active = _effective_rows(rows)
        if any(row.status != "completed" for row in active):
            continue
        bad = [row for row in active if row.conclusion not in EXTERNAL_GOOD_CONCLUSIONS]
        if bad and all(verdict_is_provisional(row, now) for row in bad):
            held.append(name)
    return sorted(set(held))


def combine_verdicts(
    in_run: tuple[int, str],
    external_verdict: str,
    external_failures: list[str],
    external_pending: list[str],
    external_provisional: list[str] | None = None,
    *,
    sweep_failures: list[str] | None = None,
    sweep_in_flight: list[str] | None = None,
    sweep_names: list[str] | None = None,
    sweep_excluded: list[str] | None = None,
    sweep_expired: list[str] | None = None,
    sweep_findings: list[str] | None = None,
    sweep_ran: bool = False,
) -> tuple[int, str]:
    """Fold the L4 external-context and L5 sweep verdicts into the in-run one.

    FAILURE dominates PENDING dominates SUCCESS across every layer -- the
    combined verdict can only ever be as good as the worst of them.
    """

    in_run_code, in_run_report = in_run
    lines = [in_run_report, "  external contexts (L4):"]
    if external_failures:
        lines.append(f"    - FAILURE: {', '.join(external_failures)}")
    if external_pending:
        lines.append(f"    - PENDING/absent: {', '.join(external_pending)}")
    if external_provisional:
        # Distinct from the line above on purpose: "pending because a red is
        # about to be replaced by an automatic re-run" and "pending because
        # nothing has started" are different diagnoses of a wedged PR, and a
        # single PENDING line reads the same for both.
        lines.append(
            "    - awaiting an automatic replacement (cancelled, or failed or "
            f"skipped inside the re-run grace): {', '.join(external_provisional)}"
        )
    if not external_failures and not external_pending:
        lines.append("    - all present + success")

    if sweep_ran:
        # OMN-18970 L5. The count prints on EVERY verdict, including a clean
        # one: a sweep that finds nothing and says nothing is indistinguishable
        # from a sweep that did not run (rule 16).
        lines.append(
            "  external default-deny sweep (L5): "
            f"{len(sweep_names or [])} unregistered context(s) judged"
        )
        if sweep_failures:
            lines.append(
                "    - FAILURE (red, and named by NOTHING else): "
                + ", ".join(sweep_failures)
            )
        if sweep_excluded:
            lines.append(
                "    - exclusions applied: " + ", ".join(sorted(sweep_excluded))
            )
        if sweep_expired:
            lines.append(
                "    - exclusions EXPIRED (no longer excluding): "
                + ", ".join(sorted(sweep_expired))
            )
        if sweep_in_flight:
            lines.append(
                "    - still running (reported, not waited on): "
                + ", ".join(sorted(sweep_in_flight))
            )
        if sweep_findings:
            lines.append(
                "    - exclusion registry REFUSED: " + "; ".join(sweep_findings)
            )

    sweep_blocking = bool(sweep_failures) or bool(sweep_findings)
    if in_run_code == EXIT_FAILURE or external_verdict == "FAILURE" or sweep_blocking:
        return EXIT_FAILURE, "\n".join(lines)
    if in_run_code == EXIT_PENDING or external_verdict == "PENDING":
        return EXIT_PENDING, "\n".join(lines)
    return EXIT_SUCCESS, "\n".join(lines)


def evaluate(
    jobs: list[dict[str, object]],
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


def _load_jobs(path: str | None) -> list[dict[str, object]]:
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


def _load_check_runs(path: str) -> list[dict[str, object]] | None:
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


def _load_workflow_runs(path: str | None) -> list[dict[str, object]] | None:
    """Load ``actions/runs?head_sha=`` rows for the OMN-18970 event scoping.

    ``None`` on a missing or unreadable file, which resolves every row's event
    to ``None`` and therefore SWEEPS every row. Unreadable is the stricter
    reading here, so a failed fetch cannot exempt anything.
    """

    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict):
        runs = payload.get("workflow_runs")
        return runs if isinstance(runs, list) else None
    return payload if isinstance(payload, list) else None


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
    parser.add_argument(
        "--workflow-runs-file",
        default=None,
        help="Path to the head SHA's actions/runs JSON, used ONLY to resolve "
        "which EVENT produced each check-run so the OMN-18970 L5 default-deny "
        "sweep can skip non-pull-request rows. A missing/unreadable file "
        "resolves every event as unknown, which SWEEPS every row -- the "
        "stricter reading, so a failed fetch cannot exempt anything.",
    )
    parser.add_argument(
        "--event-name",
        default="pull_request",
        help="GitHub event name. The OMN-18970 L5 sweep runs on "
        "'pull_request' only: on a push run the head is a merge commit whose "
        "check-runs are post-merge rows, not a verdict about a pull request. "
        "Defaults to 'pull_request' so a FORGOTTEN argument ENFORCES rather "
        "than silently skipping.",
    )
    args = parser.parse_args(argv)

    jobs = _load_jobs(args.jobs_file)
    code, report = evaluate(jobs, run_attempt=args.run_attempt)

    if args.check_runs_file is not None:
        check_runs = _load_check_runs(args.check_runs_file)
        # The observation time the OMN-17864 / OMN-18355 graces are measured
        # against. It is the process's own wall clock and has NO CLI surface --
        # deliberately, because a caller-assertable time would let a long-dead
        # red be held provisional indefinitely, which is the one way these
        # graces could become a bypass.
        #
        # OMITTING IT SILENTLY DISABLES BOTH GRACES. `verdict_is_provisional`
        # returns False on `now is None` by design -- fail-closed, so a
        # forgetful caller enforces the old strict reading rather than waiting.
        # That is the right default and a terrible silent outcome: the first
        # port of this change into a sibling repository changed the gate module
        # and not its poller, and the gate shipped completely inert with every
        # unit test green.
        now = datetime.now(UTC)
        ext_verdict, ext_failures, ext_pending = evaluate_external(check_runs, now=now)
        # OMN-18970 L5. Subtracting this run's own job names is what keeps the
        # sweep from re-judging a job the in-run soft-allowlist already
        # admitted, from the other side of the same head.
        sweep_ran = args.event_name == "pull_request"
        sweep_findings = (
            validate_sweep_exclusions(EXTERNAL_SWEEP_EXCLUSIONS) if sweep_ran else []
        )
        _active, sweep_expired = (
            active_sweep_exclusions(EXTERNAL_SWEEP_EXCLUSIONS, now=now)
            if sweep_ran
            else (frozenset(), ())
        )
        sweep_failures, sweep_in_flight, sweep_names, sweep_excluded = (
            evaluate_external_sweep(
                check_runs,
                in_run_names=frozenset(
                    dedup_latest(jobs, run_attempt=args.run_attempt)
                ),
                events=check_run_event_index(
                    _load_workflow_runs(args.workflow_runs_file)
                ),
                now=now,
            )
            if sweep_ran
            else ([], [], [], [])
        )
        code, report = combine_verdicts(
            (code, report),
            ext_verdict,
            ext_failures,
            ext_pending,
            provisional_external_verdicts(check_runs, now=now),
            sweep_failures=sweep_failures,
            sweep_in_flight=sweep_in_flight,
            sweep_names=sweep_names,
            sweep_excluded=sweep_excluded,
            sweep_expired=list(sweep_expired),
            # A malformed exclusion entry fails the gate outright: an
            # unreviewable exception is worse than none, because it reads as a
            # considered decision.
            sweep_findings=[f"malformed sweep exclusion: {f}" for f in sweep_findings],
            sweep_ran=sweep_ran,
        )

    print(report)
    if args.report_only:
        return EXIT_SUCCESS
    return code


if __name__ == "__main__":
    raise SystemExit(main())

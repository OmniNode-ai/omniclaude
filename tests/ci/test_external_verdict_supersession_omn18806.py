# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CI Summary waits out a red an automatic re-run is due to replace (OMN-18806).

WHAT IS UNDER TEST
    The REAL external-context resolution in ``scripts/ci/ci_summary_gate.py``,
    imported as the module CI runs.

THE INCIDENT
    ``CI Summary`` records a terminal FAILURE on an external context that is
    red only because the change-control evidence companion has not been minted
    yet, and then never re-polls. On a ticketed PR the companion is minted by
    AUTOMATION after the PR opens; until it lands the PR body carries no
    evidence-source stamp and the Receipt Gate is legitimately red. When the
    companion merges, automation PATCHes the PR body, the body edit re-fires
    every workflow whose ``types:`` include ``edited``, and the Receipt Gate
    re-runs and goes green ON ITS OWN. By then ``CI Summary`` has already
    recorded FAILURE and exited, and the armed auto-merge is held by a verdict
    no longer true of the head. Only a human rerun cleared it, and that rerun
    passed with NO CHANGE TO THE PR.

    Measured in ``omnibase_infra`` over 30 merged ``dev`` PRs: 16 exhibited the
    shape, every one recovered, the slowest in 6.8 minutes, the median in 1.9.
    Landed there as ``#3793`` (squash ``69ba4fc5``); this is the port into this
    repository's own copy of the module, which had none of it.

THREE CONCLUSIONS, TWO WINDOWS, AND WHY
    ``cancelled`` (OMN-18355, 600s) is a producer stopped BY the run that is
    about to replace it, so its replacement is already running. ``failure`` and
    ``skipped`` (OMN-17864, 1200s) wait on a separate automation cycle. A
    ``skipped`` row belongs with ``failure`` rather than with a real verdict
    because a producer whose job ``needs:`` a gate that failed for the unmerged
    companion is skipped, not run: its row is a statement about its DEPENDENCY.

THIS DOES NOT REOPEN THE SKIP-AS-PASS VECTOR (OMN-15057 / OMN-14854)
    That vector is ``skipped`` read as SUCCESS.
    :class:`TestSkippedIsNeverSuccess` is the control: a skip is held PENDING,
    a real verdict may supersede it, and if none arrives it FAILS at the grace.

WHAT THIS DOES NOT TOUCH
    The OMN-16236 recency rules and the OMN-15112 ALL-must-succeed protection
    are preserved and pinned here, in :class:`TestNewestAttemptSelection` and
    :class:`TestTheAmbiguityRuleSurvivesTheGrace`. Every case in the first runs
    with the graces deliberately EXPIRED, so it proves attempt selection on its
    own rather than riding on a window.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest

from scripts.ci import ci_summary_gate as gate
from scripts.ci.ci_summary_gate import (
    CANCELLED_SUPERSESSION_GRACE_S,
    EXTERNAL_FAILURE_SUPERSESSION_GRACE_S,
    SUPERSEDABLE_CONCLUSIONS,
    CheckRunState,
    cancellation_is_provisional,
    combine_verdicts,
    evaluate_external,
    provisional_external_verdicts,
    supersedable_verdict_is_provisional,
    verdict_is_provisional,
)

pytestmark = pytest.mark.unit

CONTEXT = "verify / verify"
DUPLICATED = "occ-preflight / eligibility"
HEAD = "e" * 40
NOW = datetime(2026, 9, 19, 3, 5, 36, tzinfo=UTC)

#: Far enough past every window that no case in a class using it can pass
#: because of a grace rather than because of the property under test.
EXPIRED_S = EXTERNAL_FAILURE_SUPERSESSION_GRACE_S + 3600


def _z(when: datetime) -> str:
    return when.isoformat().replace("+00:00", "Z")


def _row(
    conclusion: str | None,
    *,
    age_s: float,
    name: str = CONTEXT,
    run_id: int = 1,
    status: str = "completed",
    head_sha: str | None = HEAD,
    completed_at: str | None | object = ...,
) -> dict[str, object]:
    """One check-run row that concluded ``age_s`` seconds before :data:`NOW`."""

    completed = NOW - timedelta(seconds=age_s)
    row: dict[str, object] = {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "id": run_id,
        "head_sha": head_sha,
        "started_at": _z(completed - timedelta(seconds=30)),
        "completed_at": _z(completed) if completed_at is ... else completed_at,
    }
    if status != "completed":
        row["conclusion"] = None
        row["completed_at"] = None
    return row


def _state(
    conclusion: str | None, *, age_s: float, completed_at: str | None | object = ...
) -> CheckRunState:
    completed = NOW - timedelta(seconds=age_s)
    return CheckRunState(
        name=CONTEXT,
        status="completed",
        conclusion=conclusion,
        id=1,
        started_at=_z(completed - timedelta(seconds=30)),
        head_sha=HEAD,
        completed_at=_z(completed) if completed_at is ... else completed_at,
    )


def _external(
    rows: list[dict[str, object]],
    *,
    now: datetime | None = NOW,
    expected: tuple[str, ...] = (CONTEXT,),
    all_must_succeed: frozenset[str] = frozenset(),
) -> tuple[str, list[str], list[str]]:
    return evaluate_external(
        rows, expected=expected, all_must_succeed=all_must_succeed, now=now
    )


class TestAFreshRedIsPendingNotFailed:
    """AC1 -- the behaviour the ticket exists for."""

    @pytest.mark.parametrize("conclusion", ["failure", "skipped", "cancelled"])
    def test_inside_its_window_the_context_is_pending(self, conclusion: str) -> None:
        verdict, failures, pending = _external([_row(conclusion, age_s=38)])
        assert failures == []
        assert pending == [CONTEXT]
        assert verdict == "PENDING"

    @pytest.mark.parametrize("conclusion", ["failure", "skipped", "cancelled"])
    def test_outside_its_window_it_still_fails(self, conclusion: str) -> None:
        verdict, failures, pending = _external([_row(conclusion, age_s=EXPIRED_S)])
        assert failures == [CONTEXT]
        assert verdict == "FAILURE"

    def test_the_two_windows_are_separate_and_the_cancelled_one_is_shorter(
        self,
    ) -> None:
        assert CANCELLED_SUPERSESSION_GRACE_S < EXTERNAL_FAILURE_SUPERSESSION_GRACE_S
        between = CANCELLED_SUPERSESSION_GRACE_S + 60
        assert not cancellation_is_provisional(_state("cancelled", age_s=between), NOW)
        assert supersedable_verdict_is_provisional(
            _state("failure", age_s=between), NOW
        )

    def test_the_supersedable_set_is_failure_and_skipped_only(self) -> None:
        assert frozenset({"failure", "skipped"}) == SUPERSEDABLE_CONCLUSIONS

    def test_the_pending_reason_is_reported_distinctly(self) -> None:
        held = provisional_external_verdicts(
            [_row("failure", age_s=38)], expected=(CONTEXT,), now=NOW
        )
        assert held == [CONTEXT]
        _code, report = combine_verdicts(
            (gate.EXIT_SUCCESS, "in-run"), "PENDING", [], [CONTEXT], held
        )
        assert "awaiting an automatic replacement" in report

    def test_a_settled_red_is_not_reported_as_awaiting_anything(self) -> None:
        assert (
            provisional_external_verdicts(
                [_row("failure", age_s=EXPIRED_S)], expected=(CONTEXT,), now=NOW
            )
            == []
        )


class TestUngracedConclusionsStayTerminal:
    """``timed_out`` and ``action_required`` are not a re-run shape."""

    @pytest.mark.parametrize("conclusion", ["timed_out", "action_required"])
    @pytest.mark.parametrize("age_s", [0, 38, 601, 1201])
    def test_they_fail_on_the_poll_that_observes_them(
        self, conclusion: str, age_s: float
    ) -> None:
        assert not verdict_is_provisional(_state(conclusion, age_s=age_s), NOW)
        _verdict, failures, _pending = _external([_row(conclusion, age_s=age_s)])
        assert failures == [CONTEXT]


class TestFailClosedOnUncertainty:
    """AC4 -- every uncertain input restores the strict pre-grace reading."""

    @pytest.mark.parametrize("conclusion", ["failure", "skipped", "cancelled"])
    def test_no_clock_fails_now(self, conclusion: str) -> None:
        assert not verdict_is_provisional(_state(conclusion, age_s=38), None)
        _verdict, failures, _pending = _external([_row(conclusion, age_s=38)], now=None)
        assert failures == [CONTEXT]

    @pytest.mark.parametrize("completed_at", [None, "", "not-a-timestamp"])
    def test_an_unreadable_completion_time_fails_now(
        self, completed_at: str | None
    ) -> None:
        assert not verdict_is_provisional(
            _state("failure", age_s=38, completed_at=completed_at), NOW
        )
        _verdict, failures, _pending = _external(
            [_row("failure", age_s=38, completed_at=completed_at)]
        )
        assert failures == [CONTEXT]

    def test_a_completion_far_in_the_future_fails_now(self) -> None:
        skewed = -(EXTERNAL_FAILURE_SUPERSESSION_GRACE_S + 60)
        assert not verdict_is_provisional(_state("failure", age_s=skewed), NOW)
        _verdict, failures, _pending = _external([_row("failure", age_s=skewed)])
        assert failures == [CONTEXT]

    def test_ordinary_clock_skew_stays_provisional(self) -> None:
        """A ``completed_at`` seconds in the future is skew, not a wrong clock."""
        assert verdict_is_provisional(_state("failure", age_s=-5), NOW)

    def test_an_absent_context_is_pending_never_green(self) -> None:
        verdict, failures, pending = _external([])
        assert failures == []
        assert pending == [CONTEXT]
        assert verdict == "PENDING"

    def test_an_unfetchable_payload_is_pending_never_green(self) -> None:
        verdict, failures, pending = _external(None)  # type: ignore[arg-type]
        assert failures == []
        assert pending == [CONTEXT]
        assert verdict == "PENDING"


class TestSkippedIsNeverSuccess:
    """AC3 -- the control on the skip-as-pass vector (OMN-15057 / OMN-14854)."""

    @pytest.mark.parametrize(
        ("age_s", "now"),
        [(38, None), (38, NOW), (EXPIRED_S, NOW)],
        ids=["no-clock", "inside-grace", "past-grace"],
    )
    def test_a_lone_skip_never_resolves_the_context(
        self, age_s: float, now: datetime | None
    ) -> None:
        verdict, _failures, _pending = _external(
            [_row("skipped", age_s=age_s)], now=now
        )
        assert verdict != "SUCCESS"

    def test_a_lone_skip_fails_once_the_grace_expires(self) -> None:
        verdict, failures, _pending = _external([_row("skipped", age_s=EXPIRED_S)])
        assert failures == [CONTEXT]
        assert verdict == "FAILURE"

    def test_a_real_success_supersedes_a_fresh_skip(self) -> None:
        verdict, failures, pending = _external(
            [_row("skipped", age_s=38, run_id=1), _row("success", age_s=0, run_id=2)]
        )
        assert (failures, pending, verdict) == ([], [], "SUCCESS")


class TestNewestAttemptSelection:
    """AC2 -- attempt selection, proved with every grace EXPIRED.

    Nothing in this class can pass because a window held a row provisional:
    every row is older than :data:`EXPIRED_S`.
    """

    def test_a_newer_success_beats_a_stale_failure(self) -> None:
        verdict, failures, pending = _external(
            [
                _row("failure", age_s=EXPIRED_S + 600, run_id=1),
                _row("success", age_s=EXPIRED_S, run_id=2),
            ]
        )
        assert (failures, pending, verdict) == ([], [], "SUCCESS")

    def test_payload_row_order_does_not_decide(self) -> None:
        rows = [
            _row("success", age_s=EXPIRED_S, run_id=2),
            _row("failure", age_s=EXPIRED_S + 600, run_id=1),
        ]
        verdict, failures, _pending = _external(rows)
        assert (failures, verdict) == ([], "SUCCESS")

    def test_a_newer_running_attempt_is_pending_not_a_stale_failure(self) -> None:
        verdict, failures, pending = _external(
            [
                _row("failure", age_s=EXPIRED_S + 600, run_id=1),
                _row(None, age_s=EXPIRED_S, run_id=2, status="in_progress"),
            ]
        )
        assert failures == []
        assert pending == [CONTEXT]
        assert verdict == "PENDING"

    def test_three_attempts_resolve_on_the_newest_not_the_worst(self) -> None:
        verdict, failures, _pending = _external(
            [
                _row("success", age_s=EXPIRED_S + 1200, run_id=1),
                _row("failure", age_s=EXPIRED_S + 600, run_id=2),
                _row("success", age_s=EXPIRED_S, run_id=3),
            ]
        )
        assert (failures, verdict) == ([], "SUCCESS")

    def test_a_newer_failure_after_a_success_still_fails(self) -> None:
        verdict, failures, _pending = _external(
            [
                _row("success", age_s=EXPIRED_S + 600, run_id=1),
                _row("failure", age_s=EXPIRED_S, run_id=2),
            ]
        )
        assert (failures, verdict) == ([CONTEXT], "FAILURE")


class TestTheAmbiguityRuleSurvivesTheGrace:
    """OMN-16236 / OMN-15112 -- undeterminable recency stays conservative."""

    def _ambiguous(self, first: str, second: str, *, age_s: float) -> list[dict]:
        """Two rows for one name carrying NEITHER an id nor a started_at.

        :func:`_select_latest` cannot order these, so every row stays in play
        and all must be good -- the protection for ~52 concurrent producers of
        one context name.
        """

        completed = _z(NOW - timedelta(seconds=age_s))
        return [
            {
                "name": DUPLICATED,
                "status": "completed",
                "conclusion": conclusion,
                "head_sha": HEAD,
                "completed_at": completed,
            }
            for conclusion in (first, second)
        ]

    def test_a_settled_red_among_ambiguous_duplicates_still_fails(self) -> None:
        verdict, failures, _pending = _external(
            self._ambiguous("success", "failure", age_s=EXPIRED_S),
            expected=(DUPLICATED,),
        )
        assert (failures, verdict) == ([DUPLICATED], "FAILURE")

    def test_a_fresh_red_among_ambiguous_duplicates_is_pending(self) -> None:
        verdict, failures, pending = _external(
            self._ambiguous("success", "failure", age_s=38), expected=(DUPLICATED,)
        )
        assert failures == []
        assert pending == [DUPLICATED]
        assert verdict == "PENDING"

    def test_one_fresh_and_one_settled_red_fails(self) -> None:
        """A name fails as soon as ANY of its bad rows is outside its window."""

        rows = [
            {
                "name": DUPLICATED,
                "status": "completed",
                "conclusion": "failure",
                "head_sha": HEAD,
                "completed_at": _z(NOW - timedelta(seconds=age_s)),
            }
            for age_s in (38, EXPIRED_S)
        ]
        verdict, failures, _pending = _external(rows, expected=(DUPLICATED,))
        assert (failures, verdict) == ([DUPLICATED], "FAILURE")

    def _concurrent(self, *ages: float) -> list[dict[str, object]]:
        """One failed row per age, all ordering signals absent.

        Without an id or a ``started_at`` on every row, :func:`_select_latest`
        refuses to pick a winner, so all of them stay in play -- the shape the
        ALL-must-succeed layer exists for.
        """

        return [
            {
                "name": DUPLICATED,
                "status": "completed",
                "conclusion": "failure",
                "head_sha": HEAD,
                "completed_at": _z(NOW - timedelta(seconds=age_s)),
            }
            for age_s in ages
        ]

    def test_the_all_must_succeed_layer_counts_only_settled_producers(self) -> None:
        _verdict, failures, _pending = _external(
            self._concurrent(38, EXPIRED_S),
            expected=(),
            all_must_succeed=frozenset({DUPLICATED}),
        )
        assert failures == [f"{DUPLICATED} (1/2 producer(s) not success)"]

    def test_the_all_must_succeed_layer_waits_when_every_producer_is_fresh(
        self,
    ) -> None:
        verdict, failures, pending = _external(
            self._concurrent(38, 60),
            expected=(),
            all_must_succeed=frozenset({DUPLICATED}),
        )
        assert failures == []
        assert pending == [DUPLICATED]
        assert verdict == "PENDING"

    def test_a_collapsible_pair_resolves_on_the_newest_row_alone(self) -> None:
        """Ids present -> one active row, so the count is out of 1, not 2.

        Stated rather than left implicit: the ALL-must-succeed count is over
        the rows that survive recency resolution, not over every row GitHub
        ever wrote for that name.
        """

        rows = [
            _row("failure", age_s=EXPIRED_S + 600, name=DUPLICATED, run_id=1),
            _row("failure", age_s=EXPIRED_S, name=DUPLICATED, run_id=2),
        ]
        _verdict, failures, _pending = _external(
            rows, expected=(), all_must_succeed=frozenset({DUPLICATED})
        )
        assert failures == [f"{DUPLICATED} (1/1 producer(s) not success)"]


class TestTheCliHandsTheGateAClock:
    """AC5 -- the un-forgeability of both windows rests on this.

    Both graces return ``False`` when ``now`` is ``None`` -- deliberate and
    fail-closed, so a caller that forgets the time enforces the old strict
    reading rather than waiting on a red forever. That is the right default and
    a terrible SILENT outcome: the first port of this change into a sibling
    repository changed the gate module and not its poller, and the gate shipped
    completely inert with every unit test green and mypy clean.

    No flag is the load-bearing half. A caller-assertable observation time
    would let a long-dead red be held provisional indefinitely, which is the
    one way these graces could become a bypass. It is asserted BEHAVIOURALLY --
    by invoking the CLI with each candidate flag and requiring a parse error --
    so an option added by any route is caught, not only one spelled the way
    this file guesses.
    """

    FLAGS = ("--now", "--observed-at", "--clock", "--as-of", "--at")

    @pytest.mark.parametrize("flag", FLAGS)
    def test_no_cli_option_supplies_the_observation_time(
        self, flag: str, tmp_path: object, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises((SystemExit, argparse.ArgumentError)):
            gate.main(["--jobs-file", "-", flag, _z(NOW)])
        captured = capsys.readouterr()
        assert "unrecognized arguments" in captured.err or "invalid" in captured.err

    def test_main_reaches_the_external_layer_with_a_current_aware_clock(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jobs = tmp_path / "jobs.json"
        jobs.write_text(json.dumps([]), encoding="utf-8")
        runs = tmp_path / "check_runs.json"
        runs.write_text(json.dumps([]), encoding="utf-8")

        seen: list[datetime | None] = []
        real = gate.evaluate_external

        def _spy(*args: object, **kwargs: object):
            seen.append(kwargs.get("now"))
            return real(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(gate, "evaluate_external", _spy)
        before = datetime.now(UTC)
        gate.main(
            [
                "--jobs-file",
                str(jobs),
                "--check-runs-file",
                str(runs),
                "--report-only",
            ]
        )
        after = datetime.now(UTC)

        assert len(seen) == 1
        now = seen[0]
        assert isinstance(now, datetime)
        assert now.tzinfo is not None, "a naive clock cannot be compared to GitHub's"
        assert before <= now <= after, "the clock must be read at call time"

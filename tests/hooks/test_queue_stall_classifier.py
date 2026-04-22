# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for queue_stall_classifier — merge-queue stall classifier [OMN-9065].

Covers:
    * classify_queue_entry verdicts: HEALTHY / STALL / BROKEN / ESCALATE
    * has_orphaned_check time-window logic
    * has_failed_required_check only triggers on required contexts
    * Repeat-offender escalation after 3 unsticks in 1 hour
    * Persistence round-trip via record_unstick + load_unstick_history
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from queue_stall_classifier import (  # noqa: E402
    EnumQueueStallVerdict,
    classify_queue_entry,
    has_failed_required_check,
    has_orphaned_check,
    load_unstick_history,
    record_unstick,
)

pytestmark = pytest.mark.unit


NOW = datetime(2026, 4, 17, 16, 0, 0, tzinfo=UTC)


def _entry(
    *,
    position: int = 1,
    state: str = "AWAITING_CHECKS",
    enqueued_minutes_ago: int = 45,
) -> dict:
    ts = (
        (NOW - timedelta(minutes=enqueued_minutes_ago))
        .isoformat()
        .replace("+00:00", "Z")
    )
    return {"position": position, "state": state, "enqueuedAt": ts}


def _orphaned_check(minutes_ago: int = 25) -> dict:
    started = (NOW - timedelta(minutes=minutes_ago)).isoformat().replace("+00:00", "Z")
    return {
        "name": "CodeRabbit",
        "status": "IN_PROGRESS",
        "conclusion": None,
        "startedAt": started,
    }


def _passing_check(name: str = "quality") -> dict:
    return {
        "name": name,
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "startedAt": (NOW - timedelta(minutes=40)).isoformat().replace("+00:00", "Z"),
    }


def _failing_required(name: str = "Quality Gate") -> dict:
    return {
        "name": name,
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "startedAt": (NOW - timedelta(minutes=40)).isoformat().replace("+00:00", "Z"),
    }


# --- classify_queue_entry core verdicts ------------------------------------


def test_not_queue_head_returns_healthy() -> None:
    verdict = classify_queue_entry(
        entry=_entry(position=3),
        status_check_rollup=[_orphaned_check()],
        required_contexts=set(),
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.HEALTHY


def test_fresh_queue_head_returns_healthy() -> None:
    # Only 10 min in queue — well below 30-min stall threshold
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=10),
        status_check_rollup=[_orphaned_check()],
        required_contexts=set(),
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.HEALTHY


def test_old_queue_head_with_orphan_is_stall() -> None:
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_orphaned_check(minutes_ago=25), _passing_check()],
        required_contexts={"Quality Gate"},
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.STALL


def test_failed_required_check_returns_broken_not_stall() -> None:
    # Even with an orphaned check present, a genuine failure wins — we do
    # NOT unstick broken PRs (DoD non-goal: do not admin-bypass failures).
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_orphaned_check(), _failing_required("Quality Gate")],
        required_contexts={"Quality Gate"},
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.BROKEN


def test_failure_in_non_required_check_does_not_trigger_broken() -> None:
    # A failing bot check that is not in required_contexts is orthogonal to
    # BROKEN — we still treat the PR as STALL if the orphan rule fires.
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[
            _orphaned_check(),
            _failing_required("some-optional-bot"),
        ],
        required_contexts={"Quality Gate"},
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.STALL


def test_no_orphan_and_no_failure_is_healthy() -> None:
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_passing_check()],
        required_contexts={"Quality Gate"},
        now=NOW,
    )
    assert verdict == EnumQueueStallVerdict.HEALTHY


# --- repeat-offender escalation --------------------------------------------


def test_repeat_offender_after_three_unsticks_in_hour_escalates() -> None:
    prior = [
        NOW - timedelta(minutes=10),
        NOW - timedelta(minutes=25),
        NOW - timedelta(minutes=50),
    ]
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_orphaned_check()],
        required_contexts=set(),
        now=NOW,
        prior_unsticks=prior,
    )
    assert verdict == EnumQueueStallVerdict.ESCALATE


def test_old_unsticks_outside_window_do_not_escalate() -> None:
    # Three unsticks all >1h ago — should still STALL, not ESCALATE
    prior = [
        NOW - timedelta(minutes=70),
        NOW - timedelta(minutes=90),
        NOW - timedelta(minutes=120),
    ]
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_orphaned_check()],
        required_contexts=set(),
        now=NOW,
        prior_unsticks=prior,
    )
    assert verdict == EnumQueueStallVerdict.STALL


def test_two_unsticks_in_window_still_stalls() -> None:
    # Two recent unsticks — below the threshold (>=3) so still auto-heal
    prior = [NOW - timedelta(minutes=10), NOW - timedelta(minutes=40)]
    verdict = classify_queue_entry(
        entry=_entry(enqueued_minutes_ago=45),
        status_check_rollup=[_orphaned_check()],
        required_contexts=set(),
        now=NOW,
        prior_unsticks=prior,
    )
    assert verdict == EnumQueueStallVerdict.STALL


# --- helper predicates -----------------------------------------------------


def test_has_orphaned_check_respects_threshold() -> None:
    # Check only 10 min in progress — below 20-min orphan threshold
    fresh = {
        "status": "IN_PROGRESS",
        "conclusion": None,
        "startedAt": (NOW - timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
    }
    assert has_orphaned_check([fresh], NOW) is False


def test_has_orphaned_check_missing_started_at_is_not_orphaned() -> None:
    # No startedAt timestamp → cannot prove orphaned, err on healthy side
    ambiguous = {"status": "IN_PROGRESS", "conclusion": None, "startedAt": None}
    assert has_orphaned_check([ambiguous], NOW) is False


def test_has_orphaned_check_queued_status_not_orphaned() -> None:
    # QUEUED checks have not yet started running — not an orphan candidate.
    # Accepting QUEUED would trigger unstick on legitimately-pending checks.
    queued = {
        "status": "QUEUED",
        "conclusion": None,
        "startedAt": (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    assert has_orphaned_check([queued], NOW) is False


def test_has_orphaned_check_null_status_not_orphaned() -> None:
    # status=None is how StatusContext nodes are normalised in run-unstick-queue.py
    # for PENDING/EXPECTED states.  They are not in-progress check-runs.
    null_status = {
        "status": None,
        "conclusion": None,
        "startedAt": (NOW - timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    }
    assert has_orphaned_check([null_status], NOW) is False


def test_has_failed_required_check_ignores_non_required() -> None:
    rollup = [_failing_required("CodeRabbit")]
    assert has_failed_required_check(rollup, {"Quality Gate"}) is False
    assert has_failed_required_check(rollup, {"CodeRabbit"}) is True


# --- persistence round-trip ------------------------------------------------


def test_record_and_load_unstick_history_roundtrip(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    t1 = NOW - timedelta(minutes=30)
    t2 = NOW - timedelta(minutes=10)

    record_unstick("omninode-ai/omnibase_infra", 1330, t1)
    record_unstick("omninode-ai/omnibase_infra", 1330, t2)

    loaded = load_unstick_history("omninode-ai/omnibase_infra", 1330)
    assert len(loaded) == 2
    assert loaded[0].replace(microsecond=0) == t1.replace(microsecond=0)
    assert loaded[1].replace(microsecond=0) == t2.replace(microsecond=0)


def test_load_unstick_history_missing_state_dir_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Callers use classification in dry-run contexts where ONEX_STATE_DIR may
    # not be exported — must degrade gracefully to empty history.
    monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
    assert load_unstick_history("any/repo", 1) == []


def test_load_unstick_history_missing_file_returns_empty(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    assert load_unstick_history("fresh/repo", 42) == []


def test_record_unstick_requires_state_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
    with pytest.raises(KeyError):
        record_unstick("any/repo", 1, NOW)

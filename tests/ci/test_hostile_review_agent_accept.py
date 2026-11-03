# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22293: the Hostile Review job accepts an agent receipt only through ``pass_agent``.

One test per decision of the gate-accept node. Each runs the workflow's own review,
accept and enforcement steps and its gate job (see ``hostile_review_job``), with the
node faked to answer the decision under test, across the recorded reviewer outcomes, and
asserts the conclusion of every required context of the repository:

* a lost-voters result (cli_review exit 2 or 1, or a degraded quorum parsed from its
  document) is green only with ``pass_agent``;
* a ``passed`` voter result is green whatever the node answers short of a failure;
* a ``blocked`` voter result is red whatever the node answers, ``pass_agent`` included;
* a receipt bound to another head is refused, so the context stays red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ci.hostile_review_job import (
    DEGRADED_CASES,
    HEAD_SHA,
    OTHER_HEAD_SHA,
    Run,
    required_context_names,
    simulate,
)

pytestmark = pytest.mark.unit


def _run(
    tmp_path: Path,
    case: str,
    decision: str,
    *,
    receipt_head: str = HEAD_SHA,
) -> Run:
    work = tmp_path / f"{case}-{decision}-{receipt_head[:1]}"
    work.mkdir()
    return simulate(work, case=case, decision=decision, receipt_head=receipt_head)


def _assert_contexts(run: Run, *, green: bool, case: str) -> None:
    required = required_context_names()
    assert "Hostile Review Gate" in required, required
    for context in required:
        assert run.green(context) is green, (
            f"{case}: required context {context!r} should be "
            f"{'green' if green else 'red'}; steps={run.exits} skipped={run.skipped}"
        )


def test_unchanged_leaves_the_voters_verdict_to_decide(tmp_path: Path) -> None:
    passed = _run(tmp_path, "passed", "unchanged")
    _assert_contexts(passed, green=True, case="passed voters, unchanged")
    for case in DEGRADED_CASES:
        lost = _run(tmp_path, case, "unchanged")
        _assert_contexts(lost, green=False, case=f"{case}, unchanged")
        assert "enforce" in lost.exits, "the enforcement step runs on unchanged"
    blocked = _run(tmp_path, "blocked", "unchanged")
    _assert_contexts(blocked, green=False, case="blocked voters, unchanged")
    pilot = _run(tmp_path, "lost_all", "unchanged")
    _assert_contexts(
        pilot, green=True, case="every voter lost at exit 0 stays as it was"
    )


def test_pass_agent_replaces_lost_voters_and_nothing_else(tmp_path: Path) -> None:
    for case in DEGRADED_CASES:
        lost = _run(tmp_path, case, "pass_agent")
        _assert_contexts(lost, green=True, case=f"{case}, pass_agent")
        assert "enforce" in lost.skipped, "pass_agent skips the enforcement step"
        assert lost.outputs["accept"]["decision"] == "pass_agent"
        assert [
            call["argv"] for call in lost.node_calls if "--head-sha" in call["argv"]
        ]
        flags = lost.node_calls[0]["argv"]
        assert flags[flags.index("--head-sha") + 1] == HEAD_SHA, "the exact head"
    passed = _run(tmp_path, "passed", "pass_agent")
    _assert_contexts(passed, green=True, case="passed voters, pass_agent")
    blocked = _run(tmp_path, "blocked", "pass_agent")
    _assert_contexts(blocked, green=False, case="blocked voters, pass_agent")


def test_refuse_leaves_a_lost_or_blocked_verdict_red(tmp_path: Path) -> None:
    for case in DEGRADED_CASES:
        lost = _run(tmp_path, case, "refuse")
        _assert_contexts(lost, green=False, case=f"{case}, refuse")
        assert "enforce" in lost.exits, "the enforcement step runs on refuse"
    blocked = _run(tmp_path, "blocked", "refuse")
    _assert_contexts(blocked, green=False, case="blocked voters, refuse")
    passed = _run(tmp_path, "passed", "refuse")
    _assert_contexts(passed, green=True, case="passed voters, refuse")
    for case in DEGRADED_CASES:
        other = _run(tmp_path, case, "pass_agent", receipt_head=OTHER_HEAD_SHA)
        assert other.outputs["accept"]["decision"] == "refuse", (
            "another head is refused"
        )
        _assert_contexts(other, green=False, case=f"{case}, receipt for another head")

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the SubagentStop lane-termination guard and registry [OMN-16471].

RED-first coverage of the exact defect friction F-09 documents
(``omni_home/docs/tracking/2026-08-24-system-friction-report.md``, lines
224-246): a lane that dies produces the same observable shape as one that
completed, so the orchestrator scores a death as a finished stage.

``tests/hooks/fixtures/lane_verify_build_drive_death.jsonl`` is the P0
instance, hermetic: workflow ``wf_49e3ed80-aab``'s ``verify-build-drive``
lane -- the mandated adversarial verify of a 2.47M-token, 7-agent build
drive -- receiving its brief and terminating 285 ms later at the weekly
usage-limit wall with **zero tool calls**. The RED anchor is
``test_old_surface_silently_accepts_the_zero_work_death``: the surface
that existed before this ticket (the OMN-15213 report-contract guard, the
strictest registered SubagentStop hook) returns ALLOW on that fixture,
because its documented fail posture on a lane with no extractable final
message is ``no_message_extracted`` -> PASS. The GREEN anchor is the same
fixture through this guard: a failure terminal state and a durable
record.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import lane_reconcile  # noqa: E402
from lane_registry import (  # noqa: E402
    EnumLaneStatus,
    EnumLaneTerminalState,
    ModelLaneRecord,
    ModelLaneResolution,
    append_resolution,
    close_lane,
    load_records,
    load_resolutions,
    open_lane,
    reconcile,
)
from lane_termination_guard import (  # noqa: E402
    _RE_AUTH_FAILED,
    MIN_LANE_DURATION_MS,
    TAIL_LINES_SCANNED,
    _harness_error_text,
    _hook_output,
    classify_lane_termination,
    harness_death_text,
    record_termination,
    transcript_metrics,
)
from subagent_report_contract_guard import (  # noqa: E402
    EnumReportContractVerdict,
    scan_stop_event,
)

pytestmark = pytest.mark.unit

_FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "lane_verify_build_drive_death.jsonl"
)

#: The 40-entry tail of lane ``omn18691-ci-bus-phase2-bringup-2015`` on
#: 2026-09-18, reproduced: a healthy lane that took the wrong-password
#: negative control CLAUDE.md rule 16 mandates, and carried the refusal
#: string back through all three re-injection paths -- the tool result,
#: ``hook_success`` attachments echoing the command, and a
#: ``hook_additional_context`` attachment holding this guard's own prior
#: verdict. That lane merged two PRs and stood a broker up while being
#: scored dead three times [OMN-17421].
_FALSE_DEATH = (
    pathlib.Path(__file__).parent / "fixtures" / "lane_auth_control_false_death.jsonl"
)

#: The same lane, same window, with one entry changed: the harness's own
#: synthetic error frame appended last. The positive control.
_HARNESS_DEATH = (
    pathlib.Path(__file__).parent / "fixtures" / "lane_harness_auth_death.jsonl"
)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ONEX_STATE_DIR at a per-test tmp dir so records never leak."""

    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))


def _write_transcript(
    tmp_path: pathlib.Path,
    entries: list[dict[str, object]],
    name: str = "transcript.jsonl",
) -> str:
    path = tmp_path / name
    path.write_text(
        "\n".join(json.dumps(entry) for entry in entries) + "\n", encoding="utf-8"
    )
    return str(path)


def _entry(
    offset_ms: int,
    *,
    role: str = "assistant",
    text: str = "working",
    tool_uses: int = 0,
) -> dict[str, object]:
    stamp = datetime(2026, 8, 24, 3, 0, 0, tzinfo=UTC) + timedelta(
        milliseconds=offset_ms
    )
    content: list[dict[str, object]] = [{"type": "text", "text": text}]
    for index in range(tool_uses):
        content.append(
            {"type": "tool_use", "id": f"tu_{index}", "name": "Bash", "input": {}}
        )
    return {
        "type": role,
        "timestamp": stamp.isoformat().replace("+00:00", "Z"),
        "message": {"role": role, "content": content},
    }


def _harness_error(offset_ms: int, text: str) -> dict[str, object]:
    """The harness's own synthetic error frame [OMN-17421].

    Measured shape, not a guess: an ``isApiErrorMessage`` assistant entry
    whose ``message.model`` is ``"<synthetic>"``. 592 of these across the
    25 most recent session transcripts on this host on 2026-09-18.
    """

    stamp = datetime(2026, 8, 24, 3, 0, 0, tzinfo=UTC) + timedelta(
        milliseconds=offset_ms
    )
    return {
        "type": "assistant",
        "isApiErrorMessage": True,
        "timestamp": stamp.isoformat().replace("+00:00", "Z"),
        "message": {
            "role": "assistant",
            "model": "<synthetic>",
            "content": [{"type": "text", "text": text}],
        },
    }


def _stop_event(transcript_path: str, **extra: object) -> dict[str, object]:
    event: dict[str, object] = {
        "session_id": "sess-f09",
        "transcript_path": transcript_path,
        "agent_name": "verify-build-drive",
    }
    event.update(extra)
    return event


class TestRedAnchorTheOldSurfaceAcceptsADeath:
    """The pre-OMN-16471 SubagentStop surface scores the P0 death as PASS."""

    def test_old_surface_silently_accepts_the_zero_work_death(self) -> None:
        """OMN-15213's guard returns PASS on the verify-build-drive death.

        This is the hole, stated mechanically. The report-contract guard
        is the strictest registered SubagentStop hook, and its documented
        fail posture is ALLOW when no final assistant message can be
        extracted -- correct for a report-shape gate, and exactly why a
        lane that produced no message at all sails through it.
        """

        result = scan_stop_event({"transcript_path": str(_FIXTURE)})

        assert result.verdict is EnumReportContractVerdict.PASSED
        assert not result.blocking

    def test_new_guard_fails_the_same_transcript(self) -> None:
        """GREEN: the lane-termination guard calls the same lane a failure."""

        result = classify_lane_termination(_stop_event(str(_FIXTURE)))

        assert result.is_failure
        assert result.terminal_state is EnumLaneTerminalState.DIED_USAGE_LIMIT
        assert result.metrics.tool_calls == 0

    def test_new_guard_measures_the_285ms_death(self) -> None:
        """The observed 285 ms / 0 tool calls are read off the transcript."""

        metrics = transcript_metrics({"transcript_path": str(_FIXTURE)})

        assert metrics.tool_calls == 0
        assert metrics.duration_ms == 285
        assert metrics.entries == 2


class TestZeroWorkClassification:
    """A lane that did nothing is a hard failure, never a completed stage."""

    def test_sub_second_zero_tool_call_lane_is_died_zero_work(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The silent variant: no death signature, just a 285ms no-op."""

        path = _write_transcript(
            tmp_path, [_entry(0, role="user", text="brief"), _entry(285)]
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.DIED_ZERO_WORK
        assert result.is_failure
        assert result.blocking, "a lane that did nothing gets one forced retry"

    def test_a_fast_lane_that_used_tools_completed(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Speed alone is not death — tool calls are proof of work."""

        path = _write_transcript(
            tmp_path,
            [_entry(0, role="user", text="brief"), _entry(300, tool_uses=2)],
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED
        assert result.metrics.tool_calls == 2

    def test_a_long_reasoning_only_lane_completed(self, tmp_path: pathlib.Path) -> None:
        """Zero tool calls alone is not death — a lane may reason and answer."""

        path = _write_transcript(
            tmp_path,
            [
                _entry(0, role="user", text="brief"),
                _entry(MIN_LANE_DURATION_MS * 90, text="a long considered answer"),
            ],
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED

    def test_harness_supplied_duration_beats_transcript_timestamps(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A payload duration is authoritative when the harness sends one."""

        path = _write_transcript(tmp_path, [_entry(0, role="user", text="brief")])

        result = classify_lane_termination(_stop_event(path, duration_ms=285))

        assert result.metrics.duration_ms == 285
        assert result.terminal_state is EnumLaneTerminalState.DIED_ZERO_WORK


class TestDeathSignatures:
    """Each resume/death class F-09 enumerates gets its own terminal state."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            (
                "You've hit your weekly limit · resets Aug 26 at 11pm",
                EnumLaneTerminalState.DIED_USAGE_LIMIT,
            ),
            (
                "Not logged in · Please run /login",
                EnumLaneTerminalState.DIED_AUTH_FAILED,
            ),
            (
                'API Error: {"type":"api_error"} Server error mid-response',
                EnumLaneTerminalState.DIED_API_ERROR,
            ),
            (
                "No transcript found for agent ID a02d3bbccb8e222f1",
                EnumLaneTerminalState.NOT_RESUMABLE,
            ),
        ],
    )
    def test_signature_maps_to_terminal_state(
        self,
        tmp_path: pathlib.Path,
        text: str,
        expected: EnumLaneTerminalState,
    ) -> None:
        path = _write_transcript(
            tmp_path,
            [
                _entry(0, role="user", text="brief"),
                _entry(120_000, tool_uses=3),
                _harness_error(180_000, text),
            ],
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is expected
        assert result.is_failure

    def test_not_resumable_is_distinct_from_a_live_lane(
        self, tmp_path: pathlib.Path
    ) -> None:
        """The 11 dead agent ids need their own state, not a generic retry.

        F-09 records 11 agent ids that answer "No transcript found for
        agent ID" forever. Reporting that as a plain failure invites the
        same doomed resume; a distinct state lets a coordinator stop.
        """

        path = _write_transcript(
            tmp_path,
            [
                _entry(0, role="user", text="resume a6cba21e2af066c56"),
                _harness_error(
                    200, "No transcript found for agent ID a6cba21e2af066c56"
                ),
            ],
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.NOT_RESUMABLE
        assert result.terminal_state is not EnumLaneTerminalState.DIED_ZERO_WORK

    def test_an_explicit_signature_outranks_the_zero_work_heuristic(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A usage-limit death is reported as one, not as an unexplained no-op."""

        path = _write_transcript(
            tmp_path,
            [
                _entry(0, role="user", text="brief"),
                _harness_error(285, "Claude usage limit reached"),
            ],
        )

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.DIED_USAGE_LIMIT

    def test_discussing_a_limit_mid_run_is_not_a_death(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Only the transcript tail is scanned, so prose cannot fake a death."""

        entries = [_entry(0, role="user", text="what happens at a usage limit?")]
        entries.extend(_entry(1_000 * index, tool_uses=1) for index in range(1, 60))
        path = _write_transcript(tmp_path, entries)

        result = classify_lane_termination(_stop_event(path))

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED


def _entries(path: pathlib.Path) -> list[dict[str, object]]:
    """Parse a fixture transcript into entries."""

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestHarnessScopedDeathSignaturesOmn17421:
    """A death signature may only be read from a harness-authored frame.

    RED at the parent commit in BOTH directions:
    ``test_a_mandated_wrong_password_control_is_not_a_lane_death``
    returned ``DIED_AUTH_FAILED`` on the raw-text scan, and
    ``test_a_genuine_harness_auth_death_is_still_classified`` is the
    positive control that keeps the narrowing from being a deletion.
    """

    _BROKER_REFUSAL = "SASL_AUTHENTICATION_FAILED"

    def test_a_mandated_wrong_password_control_is_not_a_lane_death(self) -> None:
        """The control that proves a broker authenticates is not a death.

        A broker that merely LISTENS and a broker that AUTHENTICATES are
        told apart by presenting a wrong password and getting refused.
        Producing that refusal is the proof; scoring the lane dead for
        producing it makes the mandated control unsurvivable.
        """

        result = classify_lane_termination(_stop_event(str(_FALSE_DEATH)))

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED
        assert not result.is_failure

    def test_the_green_verdict_is_the_scoping_not_an_empty_window(self) -> None:
        """Positive control on the FIXTURE: the triggers really are in the tail.

        Without this, a fixture that simply carried no trigger would pass
        the test above and prove nothing.
        """

        tail = "\n".join(
            _FALSE_DEATH.read_text(encoding="utf-8").splitlines()[-TAIL_LINES_SCANNED:]
        )

        assert _RE_AUTH_FAILED.search(tail) is not None
        assert harness_death_text(_stop_event(str(_FALSE_DEATH))) == ""

    def test_the_guards_own_prior_verdict_is_excluded_by_structure(self) -> None:
        """The self-sustaining half: a verdict must not re-read itself."""

        notices = [
            entry
            for entry in _entries(_FALSE_DEATH)
            if entry.get("type") == "attachment"
            and entry["attachment"]["type"] == "hook_additional_context"
        ]

        assert notices, "fixture must carry the guard's own prior notice"
        for notice in notices:
            assert "LANE TERMINATED - FAILURE" in notice["attachment"]["content"]
            assert _RE_AUTH_FAILED.search(notice["attachment"]["content"]) is not None
            assert _harness_error_text(notice) == ""

    def test_hook_success_echoes_of_the_command_are_excluded(self) -> None:
        """The permanent half: hook attachments keep stale text resident.

        A ``hook_success`` attachment's ``stdout`` is the whole
        ``PreToolUse`` payload, so the command's own text is re-injected
        every time the hook fires, long after the lane stopped writing it.
        """

        echoes = [
            entry
            for entry in _entries(_FALSE_DEATH)
            if entry.get("type") == "attachment"
            and entry["attachment"]["type"] == "hook_success"
        ]

        assert len(echoes) >= 6
        assert any(self._BROKER_REFUSAL in e["attachment"]["stdout"] for e in echoes)
        for echo in echoes:
            assert _harness_error_text(echo) == ""

    def test_a_tool_result_carrying_the_refusal_is_excluded(self) -> None:
        """OMN-17421's original instance: a third-party body is not a death."""

        results = [
            entry
            for entry in _entries(_FALSE_DEATH)
            if entry.get("type") == "user"
            and any(
                isinstance(part, dict) and part.get("type") == "tool_result"
                for part in entry["message"]["content"]
            )
        ]

        assert any(
            self._BROKER_REFUSAL in str(entry["message"]["content"])
            for entry in results
        )
        for entry in results:
            assert _harness_error_text(entry) == ""

    def test_the_lanes_own_prose_is_excluded(self) -> None:
        """A lane cannot kill itself by describing the defect."""

        prose = [
            entry
            for entry in _entries(_FALSE_DEATH)
            if entry.get("type") == "assistant" and not entry.get("isApiErrorMessage")
        ]

        assert any(
            self._BROKER_REFUSAL in str(entry["message"]["content"]) for entry in prose
        )
        for entry in prose:
            assert _harness_error_text(entry) == ""

    def test_a_genuine_harness_auth_death_is_still_classified(self) -> None:
        """The narrowing is not a deletion."""

        result = classify_lane_termination(_stop_event(str(_HARNESS_DEATH)))

        assert result.terminal_state is EnumLaneTerminalState.DIED_AUTH_FAILED
        assert result.is_failure

    def test_the_classifier_tells_the_two_windows_apart(self) -> None:
        """The single assertion that is RED at the parent in both directions.

        The shipped classifier returns ``died_auth_failed`` for BOTH of
        these fixtures -- a healthy lane that merged two PRs and a lane
        the harness killed are indistinguishable to it. That is the
        defect stated as one fact.
        """

        healthy = classify_lane_termination(_stop_event(str(_FALSE_DEATH)))
        dead = classify_lane_termination(_stop_event(str(_HARNESS_DEATH)))

        assert healthy.terminal_state is not dead.terminal_state
        assert not healthy.is_failure
        assert dead.is_failure

    def test_the_two_fixtures_differ_only_by_the_harness_frame(self) -> None:
        """So the positive control isolates one cause and nothing else."""

        healthy = _FALSE_DEATH.read_text(encoding="utf-8").splitlines()
        dead = _HARNESS_DEATH.read_text(encoding="utf-8").splitlines()

        assert dead[: len(healthy) - 1] == healthy[:-1]
        assert json.loads(dead[-1])["isApiErrorMessage"] is True

    def test_the_system_error_frame_is_still_a_harness_frame(self) -> None:
        """The F-09 shape keeps working; the P0 fixture is its regression pin."""

        result = classify_lane_termination(_stop_event(str(_FIXTURE)))

        assert result.terminal_state is EnumLaneTerminalState.DIED_USAGE_LIMIT

    def test_the_anchor_refuses_a_match_that_begins_mid_token(self) -> None:
        """Belt and braces: the pattern itself no longer matches in-token.

        ``_`` is a word character, so a leading ``\b`` refuses the match
        inside the broker's refusal code while the bare token standing
        alone still matches.
        """

        assert _RE_AUTH_FAILED.search(self._BROKER_REFUSAL) is None
        assert _RE_AUTH_FAILED.search("authentication_failed") is not None


class TestLoopSafetyAndFailPosture:
    """The guard must never wedge a lane and never block on uncertainty."""

    def test_stop_hook_active_drops_the_block_but_keeps_the_verdict(
        self, tmp_path: pathlib.Path
    ) -> None:
        path = _write_transcript(
            tmp_path, [_entry(0, role="user", text="brief"), _entry(285)]
        )

        result = classify_lane_termination(_stop_event(path, stop_hook_active=True))

        assert result.terminal_state is EnumLaneTerminalState.DIED_ZERO_WORK
        assert not result.blocking
        assert "retry_exhausted" in result.reason

    def test_unreadable_transcript_fails_open(self) -> None:
        result = classify_lane_termination(
            _stop_event("/nonexistent/path/does/not/exist.jsonl")
        )

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED
        assert result.reason == "insufficient_evidence_of_death"
        assert not result.blocking

    def test_empty_event_fails_open(self) -> None:
        result = classify_lane_termination({})

        assert result.terminal_state is EnumLaneTerminalState.COMPLETED
        assert not result.blocking

    def test_untimestamped_transcript_does_not_fire_zero_work(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Duration must be *measured*, never assumed to be zero."""

        path = tmp_path / "no_ts.jsonl"
        path.write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})
            + "\n",
            encoding="utf-8",
        )

        result = classify_lane_termination(_stop_event(str(path)))

        assert result.metrics.duration_ms is None
        assert result.terminal_state is EnumLaneTerminalState.COMPLETED


class TestHookEnvelope:
    """Silence on pass; a loud, unambiguous failure otherwise."""

    def test_completed_emits_nothing(self, tmp_path: pathlib.Path) -> None:
        """A SubagentStop hook that speaks on pass clobbers the real report.

        This is the OMN-15213 mechanism: the agent replies to the
        end-of-turn notification and that reply becomes the captured
        return. Never add a "clean" message here.
        """

        path = _write_transcript(
            tmp_path,
            [_entry(0, role="user", text="brief"), _entry(300, tool_uses=2)],
        )
        result = classify_lane_termination(_stop_event(path))

        assert _hook_output(result) is None

    def test_zero_work_emits_a_blocking_envelope(self, tmp_path: pathlib.Path) -> None:
        path = _write_transcript(
            tmp_path, [_entry(0, role="user", text="brief"), _entry(285)]
        )
        output = _hook_output(classify_lane_termination(_stop_event(path)))

        assert output is not None
        assert output["decision"] == "block"
        assert "LANE TERMINATED - FAILURE" in output["reason"]
        assert output["hookSpecificOutput"]["hookEventName"] == "SubagentStop"

    def test_non_blocking_death_still_surfaces_context(self) -> None:
        """The lane is gone, so blocking cannot help — but silence must not win."""

        output = _hook_output(classify_lane_termination(_stop_event(str(_FIXTURE))))

        assert output is not None
        assert "decision" not in output
        assert "died_usage_limit" in (output["hookSpecificOutput"]["additionalContext"])


class TestLaneRegistry:
    """Dispatch and terminal records, and how they are correlated."""

    def test_dispatch_of_an_agent_lane_is_recorded(self) -> None:
        record = open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-1",
                "tool_input": {
                    "subagent_type": "verify-build-drive",
                    "prompt": "Adversarially verify OMN-16471 and OMN-15213.",
                },
            }
        )

        assert record is not None
        assert record.status is EnumLaneStatus.OPEN
        assert record.lane_name == "verify-build-drive"
        assert record.tickets == ("OMN-16471", "OMN-15213")
        assert record.prompt_digest, "brief must be digested, never stored verbatim"
        assert len(load_records()) == 1

    def test_prompt_text_is_never_written_to_disk(self) -> None:
        """A registry that stores every brief becomes a secret store."""

        secret = "hunter2-not-a-real-credential"
        open_lane(
            {
                "tool_name": "Agent",
                "session_id": "sess-1",
                "tool_input": {"name": "lane", "prompt": f"token={secret}"},
            }
        )

        blob = json.dumps([record.to_json() for record in load_records()])
        assert secret not in blob

    def test_non_dispatch_tools_are_ignored(self) -> None:
        assert open_lane({"tool_name": "Bash", "tool_input": {"command": "ls"}}) is None
        assert load_records() == ()

    def test_close_matches_the_open_record_by_lane_name(self) -> None:
        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-1",
                "tool_input": {"name": "lane-a"},
            }
        )
        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-1",
                "tool_input": {"name": "lane-b"},
            }
        )

        closed = close_lane(
            session_id="sess-1",
            lane_name="lane-b",
            terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
            terminal_reason="weekly limit",
        )

        assert closed is not None
        assert closed.lane_name == "lane-b"
        states = {record.lane_name: record.status for record in load_records()}
        assert states["lane-a"] is EnumLaneStatus.OPEN
        assert states["lane-b"] is EnumLaneStatus.CLOSED

    def test_an_unattributable_death_is_still_recorded(self) -> None:
        """A death that cannot be matched to a dispatch is still a death.

        Dropping it would restore exactly the silence this module removes.
        The ambiguous OPEN records are left alone, so the failure direction
        is "reconcile reports an open lane", never "a dead lane was marked
        complete".
        """

        for name in ("lane-a", "lane-b"):
            open_lane(
                {
                    "tool_name": "Task",
                    "session_id": "sess-1",
                    "tool_input": {"name": name},
                }
            )

        closed = close_lane(
            session_id="sess-1",
            lane_name="lane-unknown",
            terminal_state=EnumLaneTerminalState.DIED_AUTH_FAILED,
            terminal_reason="Not logged in",
        )

        assert closed is not None
        assert closed.lane_id.startswith("unattributed-")
        open_names = {
            record.lane_name
            for record in load_records()
            if record.status is EnumLaneStatus.OPEN
        }
        assert open_names == {"lane-a", "lane-b"}

    def test_registry_degrades_without_a_state_dir(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unset ONEX_STATE_DIR must not wedge a dispatch."""

        monkeypatch.delenv("ONEX_STATE_DIR", raising=False)

        assert open_lane({"tool_name": "Task", "tool_input": {"name": "x"}}) is None
        assert load_records() == ()


def _record(
    lane_id: str,
    *,
    status: EnumLaneStatus,
    dispatched_at: str,
    terminal: EnumLaneTerminalState | None = None,
) -> ModelLaneRecord:
    return ModelLaneRecord(
        lane_id=lane_id,
        lane_name=lane_id,
        session_id="sess-1",
        tool_name="Task",
        dispatched_at=dispatched_at,
        status=status,
        terminal_state=terminal,
    )


class TestReconciliation:
    """Absence of a terminal record is a failure, not a pending."""

    def test_open_lane_past_ttl_is_a_failure(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
        stale = _record(
            "dead",
            status=EnumLaneStatus.OPEN,
            dispatched_at=(now - timedelta(hours=9)).isoformat(),
        )

        verdict = reconcile(ttl_seconds=3600, now=now, records=(stale,))

        assert verdict.has_failures
        assert verdict.failed[0].terminal_state is (
            EnumLaneTerminalState.DIED_NO_TERMINAL
        )

    def test_open_lane_within_ttl_is_still_running(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
        fresh = _record(
            "alive",
            status=EnumLaneStatus.OPEN,
            dispatched_at=(now - timedelta(minutes=5)).isoformat(),
        )

        verdict = reconcile(ttl_seconds=3600, now=now, records=(fresh,))

        assert not verdict.has_failures
        assert len(verdict.open_within_ttl) == 1

    def test_an_unparseable_dispatch_timestamp_fails_closed(self) -> None:
        """A lane that cannot be proven young must not hide forever."""

        broken = _record("broken", status=EnumLaneStatus.OPEN, dispatched_at="")

        verdict = reconcile(
            ttl_seconds=3600,
            now=datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
            records=(broken,),
        )

        assert verdict.has_failures
        assert verdict.failed[0].terminal_state is (
            EnumLaneTerminalState.DIED_NO_TERMINAL
        )

    def test_completed_lanes_do_not_fail(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
        done = _record(
            "done",
            status=EnumLaneStatus.CLOSED,
            dispatched_at=(now - timedelta(hours=9)).isoformat(),
            terminal=EnumLaneTerminalState.COMPLETED,
        )

        verdict = reconcile(ttl_seconds=3600, now=now, records=(done,))

        assert not verdict.has_failures
        assert len(verdict.completed) == 1

    def test_a_recorded_death_is_a_failure(self) -> None:
        now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)
        died = _record(
            "died",
            status=EnumLaneStatus.CLOSED,
            dispatched_at=now.isoformat(),
            terminal=EnumLaneTerminalState.DIED_ZERO_WORK,
        )

        verdict = reconcile(ttl_seconds=3600, now=now, records=(died,))

        assert verdict.has_failures


class TestCorrectingAMisclassifiedRecordOmn17421:
    """A closed record carrying a wrong terminal state must be correctable.

    RED at the parent commit: the resolution overlay applied only to
    records still ``OPEN``, so a lane the guard wrongly scored dead was
    unresolvable forever -- the same permanence the misclassification
    itself has. Records are still never rewritten.
    """

    def _misclassified(self) -> ModelLaneRecord:
        return ModelLaneRecord(
            lane_id="lane-59504f674488a7ab72be",
            lane_name="omn18691-ci-bus-phase2-bringup-2015",
            session_id="sess-omn18691",
            tool_name="Agent",
            dispatched_at="2026-09-18T20:13:31+00:00",
            status=EnumLaneStatus.CLOSED,
            tickets=("OMN-18691",),
            prompt_digest="d",
            terminal_state=EnumLaneTerminalState.DIED_AUTH_FAILED,
            terminal_reason="authentication failure signature",
            closed_at="2026-09-18T20:49:17+00:00",
            evidence={"tool_calls": 86},
        )

    def _correction(self) -> ModelLaneResolution:
        return ModelLaneResolution(
            lane_id="lane-59504f674488a7ab72be",
            superseded_lane_id="",
            terminal_state=EnumLaneTerminalState.COMPLETED,
            terminal_reason="misclassified; corrected under OMN-17421",
            resolved_at="2026-09-18T21:30:00+00:00",
            evidence={"merged_prs": ["omnibase_infra#3780"]},
            ticket="OMN-17421",
        )

    def test_a_correction_clears_a_closed_false_death(self) -> None:
        record = self._misclassified()

        assert reconcile(records=(record,)).has_failures

        append_resolution(self._correction())
        verdict = reconcile(records=(record,))

        assert not verdict.has_failures
        assert len(verdict.completed) == 1
        assert "OMN-17421" in verdict.completed[0].terminal_reason

    def test_the_record_file_is_never_rewritten(self) -> None:
        """The correction is a new line, not an edit."""

        close_lane(
            session_id="sess-omn18691",
            lane_name="omn18691-ci-bus-phase2-bringup-2015",
            terminal_state=EnumLaneTerminalState.DIED_AUTH_FAILED,
            terminal_reason="authentication failure signature",
            evidence={"tool_calls": 86},
        )
        before = load_records()
        assert len(before) == 1

        append_resolution(
            ModelLaneResolution(
                lane_id=before[0].lane_id,
                superseded_lane_id="",
                terminal_state=EnumLaneTerminalState.COMPLETED,
                terminal_reason="misclassified; corrected under OMN-17421",
                resolved_at="2026-09-18T21:30:00+00:00",
                ticket="OMN-17421",
            )
        )

        after = load_records()
        assert after[0].terminal_state is EnumLaneTerminalState.DIED_AUTH_FAILED
        assert not reconcile().has_failures

    def test_the_journal_line_names_the_ticket_that_wrote_it(self) -> None:
        """Two repair classes share the journal; a reader must tell them apart."""

        append_resolution(self._correction())

        loaded = load_resolutions()["lane-59504f674488a7ab72be"]

        assert loaded.ticket == "OMN-17421"
        assert loaded.superseded_lane_id == ""

    def test_an_attribution_repair_still_defaults_to_its_own_ticket(self) -> None:
        """OMN-18690 lines predate the field and must keep their meaning."""

        append_resolution(
            ModelLaneResolution(
                lane_id="lane-x",
                superseded_lane_id="unattributed-y",
                terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
                terminal_reason="usage limit",
                resolved_at="2026-09-18T21:30:00+00:00",
            )
        )

        assert load_resolutions()["lane-x"].ticket == "OMN-18690"


class TestReconcileCli:
    """The failing exit code is the enforcement surface."""

    def test_exits_nonzero_when_a_lane_died(
        self, capsys: pytest.CaptureFixture[str], tmp_path: pathlib.Path
    ) -> None:
        path = _write_transcript(
            tmp_path, [_entry(0, role="user", text="brief"), _entry(285)]
        )
        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-f09",
                "tool_input": {"name": "verify-build-drive"},
            }
        )
        record_termination(classify_lane_termination(_stop_event(path)))

        exit_code = lane_reconcile.main([])

        assert exit_code == lane_reconcile.EXIT_LANE_FAILURES
        assert "FAILED LANES" in capsys.readouterr().out

    def test_exits_zero_when_every_lane_completed(self, tmp_path: pathlib.Path) -> None:
        path = _write_transcript(
            tmp_path,
            [_entry(0, role="user", text="brief"), _entry(300, tool_uses=2)],
        )
        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-f09",
                "tool_input": {"name": "verify-build-drive"},
            }
        )
        record_termination(classify_lane_termination(_stop_event(path)))

        assert lane_reconcile.main([]) == lane_reconcile.EXIT_OK

    def test_a_dispatched_lane_that_never_reported_fails(self) -> None:
        """The F-09 corrective action, end to end: silence is a failure."""

        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-f09",
                "tool_input": {"name": "omn15459-supersession"},
            }
        )

        assert lane_reconcile.main(["--ttl-seconds", "0"]) == (
            lane_reconcile.EXIT_LANE_FAILURES
        )

    def test_json_output_is_machine_readable(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        open_lane(
            {
                "tool_name": "Task",
                "session_id": "sess-f09",
                "tool_input": {"name": "lane"},
            }
        )

        lane_reconcile.main(["--ttl-seconds", "0", "--json"])
        payload = json.loads(capsys.readouterr().out)

        assert payload["has_failures"] is True
        assert payload["counts"]["failed"] == 1


class TestCliWiring:
    """The module runs as the shell wrapper invokes it."""

    def _run(
        self, payload: dict[str, object], state_dir: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_LIB_DIR / "lane_termination_guard.py")],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": "/usr/bin:/bin",
                "ONEX_STATE_DIR": str(state_dir),
            },
        )

    def test_zero_work_death_exits_two_with_a_json_envelope(
        self, tmp_path: pathlib.Path
    ) -> None:
        path = _write_transcript(
            tmp_path, [_entry(0, role="user", text="brief"), _entry(285)]
        )

        proc = self._run(_stop_event(path), tmp_path / "state")

        assert proc.returncode == 2
        assert json.loads(proc.stdout)["decision"] == "block"

    def test_completed_lane_exits_zero_and_says_nothing(
        self, tmp_path: pathlib.Path
    ) -> None:
        path = _write_transcript(
            tmp_path,
            [_entry(0, role="user", text="brief"), _entry(300, tool_uses=2)],
        )

        proc = self._run(_stop_event(path), tmp_path / "state")

        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_malformed_stdin_does_not_crash(self, tmp_path: pathlib.Path) -> None:
        proc = subprocess.run(
            [sys.executable, str(_LIB_DIR / "lane_termination_guard.py")],
            input="not json at all",
            capture_output=True,
            text=True,
            check=False,
            env={"PATH": "/usr/bin:/bin", "ONEX_STATE_DIR": str(tmp_path / "state")},
        )

        assert proc.returncode == 0


class TestHooksRegistration:
    """The guard is only a mechanism while it is registered."""

    def test_both_hooks_are_registered(self) -> None:
        hooks_json = (
            pathlib.Path(__file__).parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "hooks.json"
        )
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        commands = [
            hook.get("command", "")
            for event in data["hooks"].values()
            for group in event
            for hook in group.get("hooks", [])
        ]

        assert any("pre_tool_use_lane_open.sh" in cmd for cmd in commands)
        assert any("subagent_stop_lane_termination_guard.sh" in cmd for cmd in commands)

    def test_the_dispatch_matcher_covers_every_lane_tool(self) -> None:
        hooks_json = (
            pathlib.Path(__file__).parent.parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "hooks.json"
        )
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        matchers = [
            group.get("matcher", "")
            for group in data["hooks"]["PreToolUse"]
            if any(
                "pre_tool_use_lane_open.sh" in hook.get("command", "")
                for hook in group.get("hooks", [])
            )
        ]

        assert matchers == ["^(Task|Agent|Workflow)$"]

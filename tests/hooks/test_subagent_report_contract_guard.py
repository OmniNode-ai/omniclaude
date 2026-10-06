# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the SubagentStop report-contract guard [OMN-15213].

RED-first coverage of the exact defect the ticket documents: a
``SubagentStop`` hook notification fires at end-of-turn, the agent replies
to it with a short acknowledgement, and because the captured return is the
LAST assistant message that acknowledgement clobbers the real report 1-2
turns earlier (reproduced 3/5 in ``wf_00bcb6a9-f0b``, 3/3 in
``wf_1923e07f-b65``).

``tests/hooks/fixtures/subagent_stop_clobbered_return.jsonl`` is that
transcript, hermetic: a full contract-satisfying report, then the hook
notification, then "Done.". The RED anchor is
``test_old_path_silently_accepts_the_clobbered_return`` — the surface that
existed before this ticket (the OMN-15062 secret-leak guard, the only
registered SubagentStop hook) returns ALLOW on that fixture, i.e. the lane
was accepted with a filler return. The GREEN anchor is the same fixture
through this guard: RED + blocking.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from subagent_report_contract_guard import (  # noqa: E402
    MIN_REPORT_CHARS,
    EnumReportContractVerdict,
    _extract_last_assistant_message,
    _hook_output,
    classify_final_report,
    scan_stop_event,
)

pytestmark = pytest.mark.unit

_FIXTURE = (
    pathlib.Path(__file__).parent / "fixtures" / "subagent_stop_clobbered_return.jsonl"
)

# A return that satisfies the contract: verdict, ticket id, file path,
# command + output.
_GOOD_REPORT = (
    "VERDICT: PASS. OMN-15213 landed the SubagentStop report-contract guard.\n"
    "Changed: plugins/onex/hooks/lib/subagent_report_contract_guard.py and "
    "plugins/onex/hooks/hooks.json.\n"
    "$ uv run pytest tests/hooks/test_subagent_report_contract_guard.py -q\n"
    "18 passed in 0.42s\n"
    "PR https://github.com/OmniNode-ai/omniclaude/pull/1953 - not merged."
)


def _structured_transcript(
    tmp_path: pathlib.Path,
    narration: str = "Now compute date drift and the new snapshot.",
    *,
    mixed_content: bool = False,
) -> pathlib.Path:
    entries = [
        {"type": "user", "message": {"role": "user", "content": "Return the report."}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": narration}],
            },
        },
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_x",
                        "name": "StructuredOutput",
                        "input": {"outcome": "success", "snapshot": {"date_drift": 0}},
                    },
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_x", "content": "OK"}
                ],
            },
        },
    ]
    if mixed_content:
        entries[2]["message"]["content"].insert(0, {"type": "text", "text": "Done."})
    path = tmp_path / "agent.jsonl"
    path.write_text("\n".join(json.dumps(entry) for entry in entries), encoding="utf-8")
    return path


class TestLiveStructuredReturns:
    @pytest.mark.parametrize("mixed_content", [False, True])
    @pytest.mark.parametrize(
        "source", ["agent_transcript_path", "transcript_path", "transcript"]
    )
    @pytest.mark.parametrize(
        "direct_field",
        [
            None,
            "last_assistant_message",
            "final_message",
            "assistant_message",
            "last_message",
        ],
    )
    @pytest.mark.parametrize(
        "narration",
        [
            "Now compute date drift and the new snapshot.",
            "Exit 1. I need the header lines and counts.",
        ],
    )
    def test_structured_return_wins(
        self, tmp_path, source, direct_field, narration, mixed_content
    ) -> None:
        path = _structured_transcript(tmp_path, narration, mixed_content=mixed_content)
        event = {
            source: path.read_text(encoding="utf-8")
            if source == "transcript"
            else str(path)
        }
        if direct_field:
            event[direct_field] = "Structured output provided successfully"
        result = scan_stop_event(event)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "schema_bound_return"
        assert result.blocking is False
        assert _extract_last_assistant_message(event) == json.dumps(
            {"snapshot": {"date_drift": 0}, "outcome": "success"}, sort_keys=True
        )

    def test_shell_wrapper_passes_structured_return_silently(self, tmp_path) -> None:
        path = _structured_transcript(tmp_path)
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "CLAUDE_PROJECT_DIR": str(_LIB_DIR.parents[3]),
            "PLUGIN_PYTHON_BIN": sys.executable,
        }
        proc = subprocess.run(
            [
                "bash",
                str(
                    _LIB_DIR.parent
                    / "scripts"
                    / "subagent_stop_report_contract_guard.sh"
                ),
            ],
            input=json.dumps(
                {
                    "agent_transcript_path": str(path),
                    "last_assistant_message": "Structured output provided successfully",
                }
            ),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == ""


class TestLiveReportEvidence:
    @pytest.mark.parametrize(
        "exit_citation",
        ["exit 64", "exited 64", "exits 64", "EXIT CODE 64", "Exit status 64"],
    )
    def test_prose_ledger_refusal_passes(self, exit_citation) -> None:
        report = (
            "The ledger row was not written. The script refused the STATUS row "
            "because it needs `--actor` and `--model`, and neither was passed in "
            "the arguments. `ONEX_LANE_ACTOR` and `ONEX_LANE_MODEL` aren't both "
            "set in the environment either. I won't retry or reword it. "
            f"The script reported {exit_citation}. No TERMINAL row was written. "
            "The caller must provide the actor and model before a new attempt; "
            "the existing ledger remains unchanged and there is no successful "
            "write to cite from this invocation."
        )
        assert 430 <= len(report) <= 830
        result = classify_final_report(report)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.evidence_classes == ("command_or_output",)
        assert result.blocking is False

    @pytest.mark.parametrize(
        "observation",
        [
            "Read at 08:49:46 EDT, nothing changed. The CPU is still at about 90 C.",
            "No beep source shows up on host-b (box-two). Read at 00:07:56 ET Oct 2.",
            "host-a (box-one), read at 00:08 ET Oct 2: I found no beep source.",
            "Read at 2026-10-02T00:08Z, nothing changed.",
        ],
    )
    def test_read_only_observation_passes(self, observation) -> None:
        report = (
            observation
            + "\n"
            + (
                "The read was limited to observation. No settings were changed, "
                "no services were restarted, and the measured state stayed steady. "
            )
            * 16
        )
        assert 2000 <= len(report) <= 3600
        result = classify_final_report(report)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.evidence_classes == ("observation_time",)
        assert result.blocking is False

    def test_markdown_observation_table_passes(self) -> None:
        report = (
            "The CPU is still at about 90 C. Nothing changed during this read; "
            "the baseline and current measurements are recorded below for comparison.\n"
            "| Metric | Baseline | Now | Delta |\n"
            "|---|---|---|---|\n"
            "| CPU temperature | 90 C | 90 C | 0 C |"
        )
        result = classify_final_report(report)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.evidence_classes == ("table",)
        assert result.blocking is False

    def test_clock_and_table_evidence_order(self) -> None:
        report = (
            "Read at 08:49:46 EDT, nothing changed. The CPU is still at about 90 C.\n"
            "| Metric | 08:37 baseline | Now (08:49) | Delta |\n"
            "|---|---|---|---|"
        )
        result = classify_final_report(report)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.evidence_classes == ("observation_time", "table")

    @pytest.mark.parametrize(
        ("value", "classes"),
        [
            ("OMN-20331", ("ticket_id",)),
            ("OMN-1", ()),
            (
                "MERGED c022c90de9f94aaee30d7a8bd28e4ecbabd73fa5 2026-10-01T23:20:04Z",
                ("commit_sha", "observation_time"),
            ),
            ("OPEN OPEN 1adbd9e4fde2326a5c7501ee48129113e8c295a7", ("commit_sha",)),
            ("CLOSED DRAFT APPROVED abc1234", ("commit_sha",)),
        ],
    )
    def test_machine_value_return_passes(self, value, classes) -> None:
        result = classify_final_report(value)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "machine_value_return"
        assert result.evidence_classes == classes
        assert result.blocking is False

    def test_ledger_cite_as_return_passes(self) -> None:
        result = classify_final_report(
            "CITE-AS: RULING 2026-10-02T00:39:29Z lane=record-rename-ruling"
        )
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.evidence_classes == (
            "command_or_output",
            "verdict",
            "observation_time",
        )
        assert result.blocking is False


class TestMatcherBoundaries:
    @pytest.mark.parametrize(
        "prose",
        [
            "Acknowledged; I have received the report",
            "I believe the work is finished and everything looks good to me now.",
            "I believe the work is finished and everything looks good to me now. "
            "I reviewed the outcome and have nothing further to add to this response.",
        ],
    )
    def test_unsupported_prose_stays_red(self, prose) -> None:
        result = classify_final_report(prose)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "no_evidence_citations"
        assert result.blocking is True

    def test_short_timed_hook_echo_stays_red(self) -> None:
        result = classify_final_report(
            "Acknowledged the SubagentStop hook notification at 12:30."
        )
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "hook_notification_echo"
        assert result.blocking is True

    @pytest.mark.parametrize("separator", ["\n\n", "\nordinary prose\n"])
    def test_nonconsecutive_table_rows_are_not_evidence(self, separator) -> None:
        report = (
            "The observations remain unchanged and there is no new measurement "
            "to report from the current read. The independent rows below summarize "
            "the steady state.\n| Metric | Baseline |"
            + separator
            + "| CPU temperature | warm |"
        )
        result = classify_final_report(report)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.evidence_classes == ()

    @pytest.mark.parametrize("name", ["structuredoutput", "OtherTool"])
    def test_other_tool_names_do_not_count_as_returns(self, tmp_path, name) -> None:
        path = _structured_transcript(tmp_path)
        path.write_text(
            path.read_text(encoding="utf-8").replace("StructuredOutput", name),
            encoding="utf-8",
        )
        result = scan_stop_event({"agent_transcript_path": str(path)})
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "no_evidence_citations"

    @pytest.mark.parametrize("unreadable", [False, True])
    def test_agent_transcript_takes_precedence(self, tmp_path, unreadable) -> None:
        path = _structured_transcript(tmp_path)
        agent_path = tmp_path / "priority.jsonl"
        if not unreadable:
            agent_path.write_text(
                json.dumps({"role": "assistant", "content": "Done."}), encoding="utf-8"
            )
        result = scan_stop_event(
            {"agent_transcript_path": str(agent_path), "transcript_path": str(path)}
        )
        assert result.reason == (
            "no_message_extracted" if unreadable else "bare_completion_claim"
        )

    @pytest.mark.parametrize(
        "value",
        [
            "OPEN",
            "MERGED deadbeef",
            "OPEN OMN-20331 extra",
            "OMN-20331\nOPEN",
            " ".join(["OMN-20331"] * 41),
        ],
    )
    def test_invalid_machine_values_do_not_use_machine_rule(self, value) -> None:
        assert classify_final_report(value).reason != "machine_value_return"

    def test_later_text_clobbers_structured_return(self, tmp_path) -> None:
        path = _structured_transcript(tmp_path)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "message": {"role": "assistant", "content": "Done."},
                    }
                )
            )
        result = scan_stop_event({"agent_transcript_path": str(path)})
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "bare_completion_claim"

    def test_thinking_only_entry_after_the_call_is_not_a_later_return(
        self, tmp_path
    ) -> None:
        path = _structured_transcript(tmp_path)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(
                "\n"
                + json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "role": "assistant",
                            "content": [{"type": "thinking", "thinking": ""}],
                        },
                    }
                )
            )
        result = scan_stop_event(
            {
                "agent_transcript_path": str(path),
                "last_assistant_message": "Structured output provided successfully",
            }
        )
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "schema_bound_return"

    @pytest.mark.parametrize(
        "source", ["agent_transcript_path", "transcript_path", "transcript"]
    )
    def test_malformed_transcript_does_not_accept_partial_return(
        self, tmp_path, source
    ) -> None:
        path = _structured_transcript(tmp_path)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("\n{malformed")
        event = {
            source: path.read_text(encoding="utf-8")
            if source == "transcript"
            else str(path)
        }
        assert scan_stop_event(event).reason == "no_message_extracted"


class TestClobberedReturnIsRed:
    """RED-first: the observed filler shapes must fail the lane."""

    @pytest.mark.parametrize(
        "filler",
        [
            "Done.",
            "done",
            "**Done.**",
            "Task complete.",
            "Task completed.",
            "All done!",
            "Finished.",
            "Acknowledged.",
            "OK",
            "Understood.",
            "No further action needed",
            "Nothing to report.",
        ],
    )
    def test_bare_completion_claims_are_red(self, filler: str) -> None:
        result = classify_final_report(filler)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "bare_completion_claim"
        assert result.blocking is True

    def test_hook_notification_echo_is_red(self) -> None:
        """The 'unrelated hook-notification echo' lane shape from the repro."""
        echo = (
            "The SubagentStop secret-leak guard reported clean with no matches, "
            "so there is nothing else for me to do here."
        )
        result = classify_final_report(echo)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "hook_notification_echo"

    def test_prose_without_any_citation_is_red(self) -> None:
        prose = (
            "I finished the work you asked for. Everything looks good and the "
            "changes are in place. I checked the behaviour and it all works as "
            "expected, so the lane should be considered complete now."
        )
        assert len(prose) >= MIN_REPORT_CHARS
        result = classify_final_report(prose)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "no_evidence_citations"

    def test_empty_final_return_is_red(self) -> None:
        result = classify_final_report("   \n\t ")
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "empty_final_return"


class TestContractSatisfyingReturnsPass:
    """The guard must not RED a lane that did return a real report."""

    def test_full_report_passes(self) -> None:
        result = classify_final_report(_GOOD_REPORT)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "contract_satisfied"
        assert result.blocking is False
        assert len(result.evidence_classes) >= 2

    def test_terse_but_citing_report_passes_below_length_floor(self) -> None:
        """Two evidence classes carry a short return -- no length penalty."""
        terse = "PASS - OMN-15213: tests/hooks/test_x.py, 12 passed."
        assert len(terse) < MIN_REPORT_CHARS
        result = classify_final_report(terse)
        assert result.verdict is EnumReportContractVerdict.PASSED

    def test_single_class_citation_needs_length(self) -> None:
        """One evidence class alone is only enough for a substantive report."""
        short_one_class = "Touched plugins/onex/hooks/hooks.json."
        assert len(short_one_class) < MIN_REPORT_CHARS
        assert (
            classify_final_report(short_one_class).verdict
            is EnumReportContractVerdict.RED
        )

        long_one_class = (
            "I reworked the registration surface so the guard is wired at the "
            "SubagentStop seam rather than left on disk unregistered, which is "
            "the whole point of the change: plugins/onex/hooks/hooks.json."
        )
        assert len(long_one_class) >= MIN_REPORT_CHARS
        assert (
            classify_final_report(long_one_class).verdict
            is EnumReportContractVerdict.PASSED
        )

    def test_schema_bound_return_passes(self) -> None:
        """The control group from the ticket: 7/7 schema-bound returns clean."""
        structured = json.dumps({"outcome": "success", "detail": "lane complete"})
        result = classify_final_report(structured)
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "schema_bound_return"

    def test_report_declaring_failure_passes_the_shape_contract(self) -> None:
        """An honest RED report is a valid report -- the gate checks shape."""
        failed = (
            "VERDICT: BLOCKED. OMN-15213 could not land: "
            "$ uv run pytest tests/hooks/ -q\n2 failed, 400 passed. "
            "See plugins/onex/hooks/lib/subagent_report_contract_guard.py."
        )
        assert classify_final_report(failed).verdict is EnumReportContractVerdict.PASSED


class TestToolResultLinePasses:
    """OMN-18946: a forked ledger-write/ledger-msg subagent returns the script's
    own result line, as its skill mandates. Verbatim lines the guard refused on
    h202 on 2026-10-01; before the fix each classified ``no_evidence_citations``
    and forced a re-emit that replaced the line with prose."""

    @pytest.mark.parametrize(
        "line",
        [
            "REFUSED 64 usage: --displaces must name real displaced work\n"
            "FIX: correct the arguments and run the command again",
            "REFUSED 64 args: first word must be one of MSG, HOLD, ACK, RELEASE, "
            "got '--from'\nFIX: invoke /omni:ledger-msg with arguments shaped as:",
            "RETRY 75 bus: no receipt arrived, the outcome is unknown",
            "OK MSG 2026-10-01T20:37:44Z lane=m3-order-r3 line=23537\n"
            "CITE-AS: MSG 2026-10-01T20:37:44Z lane=m3-order-r3",
        ],
    )
    def test_result_line_passes(self, line: str) -> None:
        result = classify_final_report(line)
        assert result.verdict is EnumReportContractVerdict.PASSED
        expected = ("command_or_output", "verdict")
        if line.startswith("OK "):
            expected += ("observation_time",)
        assert result.evidence_classes == expected

    @pytest.mark.parametrize(
        "line",
        [
            # ledger-msg's inbox read ends on this line and carries no CITE-AS.
            "inbox t20-item5-9143: 0 open item(s)",
            "MSG 41233: MSG | lane=orchestrator | to=t20-item5-9143 | id=m1\n"
            "inbox t20-item5-9143: 1 open item(s)",
            # a forked executor's relay may indent the script's own line.
            "  RETRY 75 bus: no receipt arrived, the outcome is unknown",
            "\t  OK MSG 2026-10-01T20:37:44Z lane=m3-order-r3 line=23537",
        ],
    )
    def test_further_result_line_shapes_pass(self, line: str) -> None:
        result = classify_final_report(line)
        assert result.verdict is EnumReportContractVerdict.PASSED, result.reason
        assert "command_or_output" in result.evidence_classes

    @pytest.mark.parametrize(
        "text",
        [
            "inbox",
            "inbox: all quiet",
            "the inbox t20: 0 open item(s) was empty",
            "inbox t20: 0 open item(s)ubmitted. Done.",
            "  OK MSG 2026-10-01TDone.",
        ],
    )
    def test_inbox_lookalike_stays_red(self, text: str) -> None:
        assert classify_final_report(text).verdict is EnumReportContractVerdict.RED

    @pytest.mark.parametrize(
        "text", ["REFUSED", "Refused.", "OK", "it was refused, retry 75 later"]
    )
    def test_verdict_word_without_result_line_stays_red(self, text: str) -> None:
        assert classify_final_report(text).verdict is EnumReportContractVerdict.RED


class TestClobberedTranscriptFixture:
    """The hermetic end-to-end anchor: real report, hook notification, 'Done.'"""

    def test_fixture_last_assistant_message_is_the_clobber(self) -> None:
        event = {"transcript": _FIXTURE.read_text(encoding="utf-8")}
        result = scan_stop_event(event)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "bare_completion_claim"
        assert result.blocking is True

    def test_old_path_silently_accepts_the_clobbered_return(self) -> None:
        """RED anchor: the pre-OMN-15213 surface accepts the clobber.

        The only SubagentStop hook registered before this ticket is the
        OMN-15062 secret-leak guard. It returns ALLOW on the exact
        transcript above -- which is the defect: a lane whose captured
        return is "Done." was scored identically to one that returned a
        full report. Nothing else in the harness looked at the shape.
        """
        from subagent_secret_leak_guard import (
            EnumSecretGuardVerdict,
        )
        from subagent_secret_leak_guard import (
            scan_stop_event as secret_scan,
        )

        event = {"transcript": _FIXTURE.read_text(encoding="utf-8")}
        assert secret_scan(event).verdict is EnumSecretGuardVerdict.ALLOW

    def test_uncloberred_report_in_same_transcript_would_have_passed(self) -> None:
        """Proves the fixture's earlier turn is a genuine passing report.

        Without this the RED above could be an artifact of a fixture that
        contains no valid report at all, rather than of the clobber.
        """
        lines = [
            json.loads(line)
            for line in _FIXTURE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        real_report = lines[1]["message"]["content"][0]["text"]
        assert (
            classify_final_report(real_report).verdict
            is EnumReportContractVerdict.PASSED
        )


class TestLoopSafety:
    """A blocking Stop hook that never yields would wedge the lane forever."""

    def test_second_pass_stays_red_but_stops_blocking(self) -> None:
        event = {
            "messages": [{"role": "assistant", "content": "Done."}],
            "stop_hook_active": True,
        }
        result = scan_stop_event(event)
        assert result.verdict is EnumReportContractVerdict.RED
        assert result.reason == "bare_completion_claim_retry_exhausted"
        assert result.blocking is False
        assert _hook_output(result) is None

    def test_first_pass_blocks(self) -> None:
        event = {"messages": [{"role": "assistant", "content": "Done."}]}
        result = scan_stop_event(event)
        assert result.blocking is True

    def test_red_record_is_written_on_loop_break(self, tmp_path, monkeypatch) -> None:
        """The loop break must leave durable evidence, not evaporate."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        event = {
            "messages": [{"role": "assistant", "content": "Done."}],
            "stop_hook_active": True,
            "session_id": "sess-omn-15213",
        }
        scan_stop_event(event)
        records = list((tmp_path / "hooks" / "report_contract_red").glob("*.json"))
        assert len(records) == 1
        payload = json.loads(records[0].read_text(encoding="utf-8"))
        assert payload["verdict"] == "red"
        assert payload["session_id"] == "sess-omn-15213"

    def test_missing_state_dir_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
        event = {
            "messages": [{"role": "assistant", "content": "Done."}],
            "stop_hook_active": True,
        }
        assert scan_stop_event(event).verdict is EnumReportContractVerdict.RED


class TestNoExtractableMessageDoesNotBlock:
    """Absence of a transcript is not evidence of a contract violation."""

    def test_empty_event_passes(self) -> None:
        result = scan_stop_event({})
        assert result.verdict is EnumReportContractVerdict.PASSED
        assert result.reason == "no_message_extracted"


class TestHookOutputIsSilentOnPass:
    """The solicitation half of OMN-15213.

    A hook that speaks on the pass path IS the end-of-turn notification an
    agent replies to, and that reply is what clobbers the report. The pass
    path must emit nothing at all.
    """

    def test_pass_emits_no_envelope(self) -> None:
        assert _hook_output(classify_final_report(_GOOD_REPORT)) is None

    def test_block_emits_both_decision_forms(self) -> None:
        output = _hook_output(classify_final_report("Done."))
        assert output is not None
        assert output["decision"] == "block"
        assert output["hookSpecificOutput"]["decision"] == "block"
        assert output["hookSpecificOutput"]["hookEventName"] == "SubagentStop"
        assert "OMN-15213" in output["reason"]

    def test_secret_leak_guard_allow_path_is_now_silent(self) -> None:
        """The registered guard no longer narrates on every clean turn."""
        from subagent_secret_leak_guard import (
            _hook_output as secret_hook_output,
        )
        from subagent_secret_leak_guard import (
            scan_stop_event as secret_scan,
        )

        allow = secret_scan(
            {"messages": [{"role": "assistant", "content": _GOOD_REPORT}]}
        )
        envelope = secret_hook_output(allow)
        assert envelope["hookSpecificOutput"]["decision"] == "allow"
        assert "additionalContext" not in envelope["hookSpecificOutput"]


class TestCliEndToEnd:
    """Exercises the CLI entrypoint the shell wrapper invokes."""

    def _run(self, event: dict[str, object]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_LIB_DIR / "subagent_report_contract_guard.py")],
            input=json.dumps(event),
            capture_output=True,
            text=True,
            check=False,
        )

    def test_cli_blocks_on_clobbered_return_and_exits_2(self) -> None:
        proc = self._run({"transcript": _FIXTURE.read_text(encoding="utf-8")})
        assert proc.returncode == 2
        payload = json.loads(proc.stdout)
        assert payload["decision"] == "block"
        # Exit 2 feeds stderr back to the agent -- the reason must be there.
        assert "REPORT CONTRACT RED" in proc.stderr

    def test_cli_passes_real_report_with_no_stdout(self) -> None:
        proc = self._run({"messages": [{"role": "assistant", "content": _GOOD_REPORT}]})
        assert proc.returncode == 0
        assert proc.stdout == ""

    def test_cli_handles_malformed_stdin_without_blocking(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(_LIB_DIR / "subagent_report_contract_guard.py")],
            input="not json{{{",
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert proc.stdout == ""


class TestRefusalRowNamesTheRealReason:
    """OMN-20398: the refusal row's detail was the constant "matched the
    bare-Done clobber signature" for every RED reason, so a result line refused
    as ``no_evidence_citations`` was filed as a bare-Done clobber and the
    fingerprint read as a false red on a result line with no way to tell which."""

    def test_detail_carries_the_classifier_reason(self, tmp_path) -> None:
        recorder_dir = tmp_path / "lib"
        recorder_dir.mkdir()
        argv_file = tmp_path / "argv.json"
        (recorder_dir / "hook_refusal_recorder.py").write_text(
            "import json, sys\n"
            f"open({str(argv_file)!r}, 'w').write(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "CLAUDE_PROJECT_DIR": str(_LIB_DIR.parents[3]),
            "PLUGIN_PYTHON_BIN": sys.executable,
            "HOOKS_LIB": str(recorder_dir),
        }
        proc = subprocess.run(
            [
                "bash",
                str(
                    _LIB_DIR.parent
                    / "scripts"
                    / "subagent_stop_report_contract_guard.sh"
                ),
            ],
            input=json.dumps(
                {"last_assistant_message": "I looked around and it seems fine."}
            ),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 2, proc.stderr
        for _ in range(50):
            if argv_file.exists() and argv_file.read_text():
                break
            time.sleep(0.1)
        argv = json.loads(argv_file.read_text(encoding="utf-8"))
        detail = argv[argv.index("--detail") + 1]
        assert "no_evidence_citations" in detail
        assert "bare-Done clobber signature" not in detail

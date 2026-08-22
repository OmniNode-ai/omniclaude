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
import pathlib
import subprocess
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from subagent_report_contract_guard import (  # noqa: E402
    MIN_REPORT_CHARS,
    EnumReportContractVerdict,
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

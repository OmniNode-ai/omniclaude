# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Unit tests for session outcome derivation.

Tests verify the deterministic decision tree:
    1. FAILED: exit_code != 0 OR error markers detected
    2. SUCCESS: tool_calls_completed > 0 AND completion markers detected
    3. ABANDONED: no completion markers AND duration < ABANDON_THRESHOLD_SECONDS
    4. UNKNOWN: none of the above criteria met

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

import pytest

from plugins.onex.hooks.lib.session_outcome import (
    ABANDON_THRESHOLD_SECONDS,
    OUTCOME_ABANDONED,
    OUTCOME_FAILED,
    OUTCOME_SUCCESS,
    OUTCOME_UNKNOWN,
    SessionOutcomeResult,
    derive_session_outcome,
)

pytestmark = pytest.mark.unit


# =============================================================================
# FAILED Outcomes
# =============================================================================


class TestFailedOutcome:
    """Test Gate 1: FAILED outcomes from exit codes and error markers."""

    def test_nonzero_exit_code_returns_failed(self) -> None:
        """Non-zero exit code produces FAILED regardless of other signals."""
        result = derive_session_outcome(
            exit_code=1,
            session_output="Everything completed successfully",
            tool_calls_completed=10,
            duration_seconds=300.0,
        )
        assert result.outcome == OUTCOME_FAILED
        assert "exit_code=1" in result.signals_used

    def test_negative_exit_code_returns_failed(self) -> None:
        """Negative exit code (e.g. signal kill) produces FAILED."""
        result = derive_session_outcome(
            exit_code=-9,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=5.0,
        )
        assert result.outcome == OUTCOME_FAILED
        assert "exit_code=-9" in result.signals_used

    def test_large_exit_code_returns_failed(self) -> None:
        """Large exit code produces FAILED."""
        result = derive_session_outcome(
            exit_code=127,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=100.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_error_marker_error_colon(self) -> None:
        """'Error:' in session output produces FAILED (case-sensitive)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Error: something went wrong",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED
        assert "error_markers_detected" in result.signals_used

    def test_error_marker_exception_colon(self) -> None:
        """'Exception:' in session output produces FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Exception: ValueError raised",
            tool_calls_completed=3,
            duration_seconds=90.0,
        )
        assert result.outcome == OUTCOME_FAILED
        assert "error_markers_detected" in result.signals_used

    def test_error_marker_traceback(self) -> None:
        """'Traceback' in session output produces FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Traceback (most recent call last):",
            tool_calls_completed=2,
            duration_seconds=60.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_error_marker_failed(self) -> None:
        """'FAILED' in session output produces FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Tests FAILED: 3 errors",
            tool_calls_completed=4,
            duration_seconds=200.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_error_markers_are_case_sensitive(self) -> None:
        """Error markers match case-sensitively: 'error:' does NOT trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="This is not an error: it is fine. Task completed.",
            tool_calls_completed=1,
            duration_seconds=120.0,
        )
        # Lowercase 'error:' should NOT match "Error:" pattern
        # But "completed" is a completion marker so this should be SUCCESS
        assert result.outcome == OUTCOME_SUCCESS

    def test_error_markers_lowercase_failed_does_not_trigger(self) -> None:
        """Lowercase 'failed' does NOT match the 'FAILED' pattern."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Nothing failed here. All done.",
            tool_calls_completed=2,
            duration_seconds=150.0,
        )
        # "failed" != "FAILED", but "done" is a completion marker
        assert result.outcome == OUTCOME_SUCCESS

    def test_exit_code_checked_before_error_markers(self) -> None:
        """Exit code is checked before error markers (exit code takes priority)."""
        result = derive_session_outcome(
            exit_code=2,
            session_output="Error: also has error markers",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        assert result.outcome == OUTCOME_FAILED
        # Should report exit code, not error markers
        assert "exit_code=2" in result.signals_used
        assert "error_markers_detected" not in result.signals_used

    def test_error_markers_checked_before_success(self) -> None:
        """Error markers take priority over completion markers (Gate 1 before Gate 2)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed but\nError: validation failed",
            tool_calls_completed=5,
            duration_seconds=300.0,
        )
        # Even though "completed" is present, "Error:" at line start triggers FAILED first
        assert result.outcome == OUTCOME_FAILED


# =============================================================================
# SUCCESS Outcomes
# =============================================================================


class TestSuccessOutcome:
    """Test Gate 2: SUCCESS outcomes from tool calls AND completion markers."""

    def test_tool_calls_and_completed_marker(self) -> None:
        """Tool calls > 0 with 'completed' marker produces SUCCESS."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed successfully",
            tool_calls_completed=3,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_SUCCESS
        assert "tool_calls=3" in result.signals_used
        assert "completion_markers_detected" in result.signals_used

    def test_tool_calls_and_done_marker(self) -> None:
        """Tool calls > 0 with 'done' marker produces SUCCESS."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="All tasks are done",
            tool_calls_completed=1,
            duration_seconds=45.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_tool_calls_and_finished_marker(self) -> None:
        """Tool calls > 0 with 'finished' marker produces SUCCESS."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="I have finished the implementation",
            tool_calls_completed=7,
            duration_seconds=500.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_tool_calls_and_success_marker(self) -> None:
        """Tool calls > 0 with 'success' marker produces SUCCESS."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Build success",
            tool_calls_completed=2,
            duration_seconds=60.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_completion_markers_are_case_insensitive(self) -> None:
        """Completion markers match case-insensitively."""
        for marker in ["COMPLETED", "Completed", "CompLeTed", "completed"]:
            result = derive_session_outcome(
                exit_code=0,
                session_output=f"Task {marker}",
                tool_calls_completed=1,
                duration_seconds=100.0,
            )
            assert result.outcome == OUTCOME_SUCCESS, (
                f"Marker '{marker}' should trigger SUCCESS"
            )

    def test_commit_hash_counts_as_completion_marker(self) -> None:
        """A commit hash (7-40 hex chars) in output is a completion marker."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Committed abc1234",
            tool_calls_completed=5,
            duration_seconds=200.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_long_commit_hash_counts_as_completion(self) -> None:
        """A full 40-char commit hash counts as a completion marker."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Commit: a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
            tool_calls_completed=3,
            duration_seconds=150.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_seven_char_commit_hash_is_minimum(self) -> None:
        """A 7-character hex string is the minimum to count as a commit hash."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Result: abcdef1",
            tool_calls_completed=2,
            duration_seconds=90.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_six_char_hex_is_not_commit_hash(self) -> None:
        """A 6-character hex string is too short for a commit hash."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Code: abcdef",
            tool_calls_completed=2,
            duration_seconds=90.0,
        )
        # No completion markers, long session with tool calls -> UNKNOWN
        assert result.outcome == OUTCOME_UNKNOWN

    def test_large_tool_calls_count(self) -> None:
        """Very large tool_calls_completed still produces SUCCESS with markers."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="All tasks completed",
            tool_calls_completed=999999,
            duration_seconds=3600.0,
        )
        assert result.outcome == OUTCOME_SUCCESS
        assert "tool_calls=999999" in result.signals_used

    def test_success_requires_both_signals(self) -> None:
        """SUCCESS requires BOTH tool_calls > 0 AND completion markers."""
        # Has tool calls but no completion markers
        result_no_markers = derive_session_outcome(
            exit_code=0,
            session_output="Some output without any relevant keywords",
            tool_calls_completed=5,
            duration_seconds=300.0,
        )
        assert result_no_markers.outcome != OUTCOME_SUCCESS

        # Has completion markers but no tool calls
        result_no_tools = derive_session_outcome(
            exit_code=0,
            session_output="Task completed",
            tool_calls_completed=0,
            duration_seconds=300.0,
        )
        assert result_no_tools.outcome != OUTCOME_SUCCESS


# =============================================================================
# ABANDONED Outcomes
# =============================================================================


class TestAbandonedOutcome:
    """Test Gate 3: ABANDONED outcomes from short sessions without markers."""

    def test_short_session_no_markers_is_abandoned(self) -> None:
        """Session under threshold without completion markers is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Hello",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        assert result.outcome == OUTCOME_ABANDONED
        assert "no_completion_markers" in result.signals_used
        assert "duration=10.0s" in result.signals_used

    def test_duration_just_below_threshold_is_abandoned(self) -> None:
        """Duration just below 60s threshold is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Just opened and closed",
            tool_calls_completed=0,
            duration_seconds=59.9,
        )
        assert result.outcome == OUTCOME_ABANDONED

    def test_duration_at_threshold_is_not_abandoned(self) -> None:
        """Duration exactly at 60s threshold is NOT ABANDONED (uses strict less-than)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Some output",
            tool_calls_completed=0,
            duration_seconds=ABANDON_THRESHOLD_SECONDS,  # 60.0
        )
        # At threshold, Gate 3 condition (< 60) is false, falls through to UNKNOWN
        assert result.outcome == OUTCOME_UNKNOWN

    def test_duration_above_threshold_is_not_abandoned(self) -> None:
        """Duration above 60s threshold is NOT ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Some output without markers",
            tool_calls_completed=0,
            duration_seconds=120.0,
        )
        assert result.outcome != OUTCOME_ABANDONED

    def test_zero_duration_is_abandoned(self) -> None:
        """Zero duration session without markers is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert result.outcome == OUTCOME_ABANDONED

    def test_short_session_with_tool_calls_still_abandoned(self) -> None:
        """Short session with tool calls but no completion markers is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Ran some tools",
            tool_calls_completed=3,
            duration_seconds=15.0,
        )
        assert result.outcome == OUTCOME_ABANDONED

    def test_short_session_with_completion_markers_is_not_abandoned(self) -> None:
        """Short session WITH completion markers is NOT ABANDONED.

        Completion markers prevent Gate 3 (which requires 'not has_completion').
        However, without tool calls, Gate 2 (SUCCESS) also fails.
        Falls through to UNKNOWN.
        """
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task done quickly",
            tool_calls_completed=0,
            duration_seconds=5.0,
        )
        # Has "done" marker, so not abandoned. No tool calls, so not success -> UNKNOWN
        assert result.outcome == OUTCOME_UNKNOWN

    def test_abandon_threshold_constant_is_60(self) -> None:
        """Verify ABANDON_THRESHOLD_SECONDS is 60.0."""
        assert ABANDON_THRESHOLD_SECONDS == 60.0


# =============================================================================
# UNKNOWN Outcomes
# =============================================================================


class TestUnknownOutcome:
    """Test Gate 4: UNKNOWN outcomes when no other gate matches."""

    def test_long_session_with_tool_calls_no_markers(self) -> None:
        """Long session with tool calls but no completion markers is UNKNOWN."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Various output without relevant keywords",
            tool_calls_completed=10,
            duration_seconds=600.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN
        assert "tool_calls=10" in result.signals_used

    def test_completion_markers_but_no_tool_calls(self) -> None:
        """Session with completion markers but zero tool calls is UNKNOWN."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed without tool use",
            tool_calls_completed=0,
            duration_seconds=300.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN
        assert "completion_markers_detected" in result.signals_used

    def test_long_session_no_signals(self) -> None:
        """Long session with no tool calls and no markers is UNKNOWN."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Just chatting for a while",
            tool_calls_completed=0,
            duration_seconds=3600.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN

    def test_unknown_includes_duration_in_signals(self) -> None:
        """UNKNOWN outcome includes duration in signals_used."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Ambiguous session",
            tool_calls_completed=0,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN
        assert "duration=120.0s" in result.signals_used

    def test_at_threshold_with_tool_calls_no_markers(self) -> None:
        """At threshold with tool calls but no markers is UNKNOWN (not ABANDONED)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Working on things",
            tool_calls_completed=5,
            duration_seconds=60.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_session_output_zero_duration(self) -> None:
        """Empty output with zero duration and zero exit is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert result.outcome == OUTCOME_ABANDONED

    def test_empty_session_output_long_duration(self) -> None:
        """Empty output with long duration is UNKNOWN."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=500.0,
        )
        assert result.outcome == OUTCOME_UNKNOWN

    def test_whitespace_only_session_output(self) -> None:
        """Whitespace-only output has no markers; short session is ABANDONED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="   \n\t\r  ",
            tool_calls_completed=0,
            duration_seconds=5.0,
        )
        assert result.outcome == OUTCOME_ABANDONED

    def test_very_large_tool_calls_completed(self) -> None:
        """Very large tool_calls_completed does not break anything."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="All finished",
            tool_calls_completed=2**31,
            duration_seconds=7200.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_very_large_duration(self) -> None:
        """Very large duration does not break anything."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Still going",
            tool_calls_completed=0,
            duration_seconds=1e9,
        )
        assert result.outcome == OUTCOME_UNKNOWN

    def test_error_marker_mid_sentence_does_not_trigger(self) -> None:
        """Error marker in mid-sentence text does NOT trigger FAILED.

        With line-start anchoring, 'Error:' only triggers when it appears
        at the beginning of a line (possibly with leading whitespace or
        a type prefix like 'ValueError:').
        """
        result = derive_session_outcome(
            exit_code=0,
            session_output="Found SomeError: unexpected value in logs",
            tool_calls_completed=5,
            duration_seconds=200.0,
        )
        # "SomeError:" mid-sentence does not match line-start anchored pattern
        # No completion markers either, duration > 60s -> UNKNOWN
        assert result.outcome == OUTCOME_UNKNOWN

    def test_completion_marker_embedded_in_word(self) -> None:
        """Completion marker within a compound word does NOT trigger.

        With word boundary matching, 'done' only matches as a standalone word,
        so 'abandoned' does not match the 'done' pattern (no word boundary
        between 'n' and 'd' within the word).
        """
        result = derive_session_outcome(
            exit_code=0,
            session_output="The task was abandoned",
            tool_calls_completed=1,
            duration_seconds=120.0,
        )
        # "abandoned" does not match \bdone\b (no word boundary)
        # No completion markers, duration > 60s -> UNKNOWN
        assert result.outcome == OUTCOME_UNKNOWN

    def test_commit_hash_with_uppercase_hex_not_matched(self) -> None:
        """Commit hash regex only matches lowercase hex characters."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Hash: ABCDEF1234567",
            tool_calls_completed=2,
            duration_seconds=90.0,
        )
        # Uppercase hex does not match \b[0-9a-f]{7,40}\b
        assert result.outcome == OUTCOME_UNKNOWN

    def test_multiple_error_markers_still_failed(self) -> None:
        """Multiple error markers in output still produces FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Error: first\nException: second\nTraceback\nFAILED",
            tool_calls_completed=10,
            duration_seconds=600.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_multiline_session_output(self) -> None:
        """Multiline output is searched correctly."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Line 1\nLine 2\nTask completed\nLine 4",
            tool_calls_completed=3,
            duration_seconds=100.0,
        )
        assert result.outcome == OUTCOME_SUCCESS


# =============================================================================
# False Positive Rejection (Tightened Patterns)
# =============================================================================


class TestFalsePositiveRejection:
    """Verify that benign text does NOT trigger error markers."""

    def test_fix_failed_test_does_not_trigger(self) -> None:
        """'fix FAILED test' is a benign reference and should NOT trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="fix FAILED test",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        # No error markers should match; short session -> ABANDONED
        assert result.outcome != OUTCOME_FAILED

    def test_previously_failed_build_does_not_trigger(self) -> None:
        """'previously FAILED build' is a benign reference and should NOT trigger."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="previously FAILED build",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        assert result.outcome != OUTCOME_FAILED

    def test_error_colon_mid_sentence_does_not_trigger(self) -> None:
        """'This is an Error: none found' mid-sentence should NOT trigger."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="This is an Error: none found",
            tool_calls_completed=0,
            duration_seconds=10.0,
        )
        assert result.outcome != OUTCOME_FAILED


# =============================================================================
# True Positive Confirmation (Tightened Patterns)
# =============================================================================


class TestTruePositiveConfirmation:
    """Verify that real error text still triggers error markers."""

    def test_count_failed_triggers(self) -> None:
        """'3 FAILED' (count + FAILED) should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="3 FAILED",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_test_failed_triggers(self) -> None:
        """'test FAILED' should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="test FAILED",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_error_colon_after_newline_triggers(self) -> None:
        """Error: at start of a line (after newline) should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Some preamble\nError: connection refused",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_valueerror_at_line_start_triggers(self) -> None:
        """'  ValueError: invalid input' at line start should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="  ValueError: invalid input",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_failed_at_end_of_line_triggers(self) -> None:
        """'FAILED' at end of a line should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="some test FAILED",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_failed_at_end_of_string_triggers(self) -> None:
        """'FAILED' at end of multiline string should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="line 1\nline 2\nFAILED",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_error_type_at_start_of_string_triggers(self) -> None:
        """'TypeError: ...' at start of string should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="TypeError: unsupported operand",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_exception_after_newline_triggers(self) -> None:
        """'RuntimeException:' after newline should trigger FAILED."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Output:\nRuntimeException: something broke",
            tool_calls_completed=5,
            duration_seconds=120.0,
        )
        assert result.outcome == OUTCOME_FAILED


# =============================================================================
# Result Structure
# =============================================================================


class TestResultStructure:
    """Test SessionOutcomeResult NamedTuple structure and invariants."""

    def test_result_is_namedtuple(self) -> None:
        """Result is a SessionOutcomeResult NamedTuple."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Done",
            tool_calls_completed=1,
            duration_seconds=100.0,
        )
        assert isinstance(result, SessionOutcomeResult)
        assert isinstance(result, tuple)

    def test_result_has_outcome_field(self) -> None:
        """Result has an 'outcome' field."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert hasattr(result, "outcome")

    def test_result_has_reason_field(self) -> None:
        """Result has a 'reason' field."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert hasattr(result, "reason")

    def test_result_has_signals_used_field(self) -> None:
        """Result has a 'signals_used' field."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="",
            tool_calls_completed=0,
            duration_seconds=0.0,
        )
        assert hasattr(result, "signals_used")

    def test_outcome_is_always_valid_string(self) -> None:
        """Outcome is always one of the four valid values."""
        valid_outcomes = {
            OUTCOME_SUCCESS,
            OUTCOME_FAILED,
            OUTCOME_ABANDONED,
            OUTCOME_UNKNOWN,
        }
        test_cases = [
            (1, "", 0, 0.0),  # FAILED (exit code)
            (0, "Error: x", 0, 0.0),  # FAILED (marker)
            (0, "Done", 1, 100.0),  # SUCCESS
            (0, "", 0, 5.0),  # ABANDONED
            (0, "", 0, 300.0),  # UNKNOWN
        ]
        for exit_code, output, tools, duration in test_cases:
            result = derive_session_outcome(exit_code, output, tools, duration)
            assert result.outcome in valid_outcomes, (
                f"Unexpected outcome '{result.outcome}' for inputs "
                f"({exit_code}, {output!r}, {tools}, {duration})"
            )

    def test_reason_is_nonempty_string(self) -> None:
        """Reason is always a non-empty string."""
        test_cases = [
            (1, "", 0, 0.0),
            (0, "Error: x", 0, 0.0),
            (0, "Done", 1, 100.0),
            (0, "", 0, 5.0),
            (0, "", 0, 300.0),
        ]
        for exit_code, output, tools, duration in test_cases:
            result = derive_session_outcome(exit_code, output, tools, duration)
            assert isinstance(result.reason, str)
            assert len(result.reason) > 0, (
                f"Empty reason for outcome '{result.outcome}'"
            )

    def test_signals_used_is_list(self) -> None:
        """signals_used is always a list."""
        test_cases = [
            (1, "", 0, 0.0),
            (0, "Error: x", 0, 0.0),
            (0, "Done", 1, 100.0),
            (0, "", 0, 5.0),
            (0, "", 0, 300.0),
        ]
        for exit_code, output, tools, duration in test_cases:
            result = derive_session_outcome(exit_code, output, tools, duration)
            assert isinstance(result.signals_used, list)

    def test_signals_used_is_nonempty(self) -> None:
        """signals_used is always non-empty (at least one signal contributed)."""
        test_cases = [
            (1, "", 0, 0.0),
            (0, "Error: x", 0, 0.0),
            (0, "Done", 1, 100.0),
            (0, "", 0, 5.0),
            (0, "", 0, 300.0),
        ]
        for exit_code, output, tools, duration in test_cases:
            result = derive_session_outcome(exit_code, output, tools, duration)
            assert len(result.signals_used) > 0, (
                f"Empty signals_used for outcome '{result.outcome}'"
            )

    def test_signals_used_contains_only_strings(self) -> None:
        """All elements in signals_used are strings."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed",
            tool_calls_completed=5,
            duration_seconds=200.0,
        )
        for signal in result.signals_used:
            assert isinstance(signal, str)

    def test_result_is_unpacked_by_index(self) -> None:
        """Result can be unpacked by index (NamedTuple behavior)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Finished",
            tool_calls_completed=1,
            duration_seconds=100.0,
        )
        outcome, reason, signals = result
        assert outcome == result.outcome
        assert reason == result.reason
        assert signals == result.signals_used


# =============================================================================
# Decision Tree Priority
# =============================================================================


class TestDecisionTreePriority:
    """Test that the decision tree gates are evaluated in the correct order."""

    def test_failed_takes_priority_over_success(self) -> None:
        """FAILED (Gate 1) is checked before SUCCESS (Gate 2)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed but Traceback in logs",
            tool_calls_completed=5,
            duration_seconds=200.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_failed_takes_priority_over_abandoned(self) -> None:
        """FAILED (Gate 1) is checked before ABANDONED (Gate 3)."""
        result = derive_session_outcome(
            exit_code=1,
            session_output="Quick exit",
            tool_calls_completed=0,
            duration_seconds=2.0,
        )
        assert result.outcome == OUTCOME_FAILED

    def test_success_takes_priority_over_unknown(self) -> None:
        """SUCCESS (Gate 2) is checked before UNKNOWN (Gate 4)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Long session that eventually finished",
            tool_calls_completed=20,
            duration_seconds=7200.0,
        )
        assert result.outcome == OUTCOME_SUCCESS

    def test_abandoned_takes_priority_over_unknown(self) -> None:
        """ABANDONED (Gate 3) is checked before UNKNOWN (Gate 4)."""
        result = derive_session_outcome(
            exit_code=0,
            session_output="Brief",
            tool_calls_completed=0,
            duration_seconds=3.0,
        )
        assert result.outcome == OUTCOME_ABANDONED


# =============================================================================
# Constants
# =============================================================================


class TestConstants:
    """Test that module constants have expected values."""

    def test_outcome_success_value(self) -> None:
        """OUTCOME_SUCCESS is the string 'success'."""
        assert OUTCOME_SUCCESS == "success"

    def test_outcome_failed_value(self) -> None:
        """OUTCOME_FAILED is the string 'failed'."""
        assert OUTCOME_FAILED == "failed"

    def test_outcome_abandoned_value(self) -> None:
        """OUTCOME_ABANDONED is the string 'abandoned'."""
        assert OUTCOME_ABANDONED == "abandoned"

    def test_outcome_unknown_value(self) -> None:
        """OUTCOME_UNKNOWN is the string 'unknown'."""
        assert OUTCOME_UNKNOWN == "unknown"

    def test_abandon_threshold_type(self) -> None:
        """ABANDON_THRESHOLD_SECONDS is a float."""
        assert isinstance(ABANDON_THRESHOLD_SECONDS, float)


# =============================================================================
# Determinism
# =============================================================================


class TestDeterminism:
    """Test that derive_session_outcome is deterministic (same inputs -> same outputs)."""

    def test_repeated_calls_same_result(self) -> None:
        """Multiple calls with identical inputs produce identical results."""
        kwargs = {
            "exit_code": 0,
            "session_output": "Task completed with abc1234def commit",
            "tool_calls_completed": 8,
            "duration_seconds": 450.0,
        }
        results = [derive_session_outcome(**kwargs) for _ in range(10)]
        for result in results:
            assert result.outcome == results[0].outcome
            assert result.reason == results[0].reason
            assert result.signals_used == results[0].signals_used

    def test_each_gate_is_deterministic(self) -> None:
        """Each gate classification is deterministic across repeated calls."""
        gate_inputs = [
            # Gate 1: FAILED
            {
                "exit_code": 1,
                "session_output": "",
                "tool_calls_completed": 0,
                "duration_seconds": 0.0,
            },
            # Gate 2: SUCCESS
            {
                "exit_code": 0,
                "session_output": "Done",
                "tool_calls_completed": 1,
                "duration_seconds": 100.0,
            },
            # Gate 3: ABANDONED
            {
                "exit_code": 0,
                "session_output": "",
                "tool_calls_completed": 0,
                "duration_seconds": 5.0,
            },
            # Gate 4: UNKNOWN
            {
                "exit_code": 0,
                "session_output": "",
                "tool_calls_completed": 0,
                "duration_seconds": 300.0,
            },
        ]
        for kwargs in gate_inputs:
            first = derive_session_outcome(**kwargs)
            second = derive_session_outcome(**kwargs)
            assert first == second

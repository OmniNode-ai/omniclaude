# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic_quality_gate.py (OMN-5729).

Coverage:
- All four quality checks: tool calls, content length, refusals, iterations
- Passing case with all checks satisfied
- Edge cases: empty content, None content, exactly-at-threshold values
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add the plugins path so we can import hooks.lib modules.
_PLUGINS_ROOT = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks"
if str(_PLUGINS_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGINS_ROOT))

from lib.agentic_quality_gate import check_agentic_quality


@pytest.mark.unit
class TestToolCallsCheck:
    def test_zero_tool_calls_fails(self) -> None:
        result = check_agentic_quality(
            content="A" * 200, tool_calls_count=0, iterations=3
        )
        assert result.passed is False
        assert "insufficient tool calls" in result.reason

    def test_one_tool_call_passes(self) -> None:
        result = check_agentic_quality(
            content="A" * 200, tool_calls_count=1, iterations=3
        )
        assert result.passed is True


@pytest.mark.unit
class TestContentLengthCheck:
    def test_none_content_fails(self) -> None:
        result = check_agentic_quality(content=None, tool_calls_count=2, iterations=3)
        assert result.passed is False
        assert "content too short" in result.reason

    def test_empty_content_fails(self) -> None:
        result = check_agentic_quality(content="", tool_calls_count=2, iterations=3)
        assert result.passed is False
        assert "content too short" in result.reason

    def test_short_content_fails(self) -> None:
        result = check_agentic_quality(
            content="Too short", tool_calls_count=2, iterations=3
        )
        assert result.passed is False
        assert "content too short" in result.reason

    def test_whitespace_only_content_fails(self) -> None:
        result = check_agentic_quality(
            content="   \n\t  ", tool_calls_count=2, iterations=3
        )
        assert result.passed is False

    def test_exactly_100_chars_passes(self) -> None:
        result = check_agentic_quality(
            content="A" * 100, tool_calls_count=2, iterations=3
        )
        assert result.passed is True


@pytest.mark.unit
class TestRefusalCheck:
    def test_refusal_i_cannot_fails(self) -> None:
        result = check_agentic_quality(
            content="I cannot access the file system " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is False
        assert "refusal detected" in result.reason

    def test_refusal_apologize_fails(self) -> None:
        result = check_agentic_quality(
            content="I apologize, but I'm not able to " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is False
        assert "refusal detected" in result.reason

    def test_refusal_deep_in_content_passes(self) -> None:
        """Refusal indicators after the first 300 chars should not trigger."""
        prefix = "A" * 301
        result = check_agentic_quality(
            content=prefix + "I cannot do this",
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True

    def test_no_refusal_passes(self) -> None:
        result = check_agentic_quality(
            content="The error handling in hook_system.py uses try/except " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True


@pytest.mark.unit
class TestIterationsCheck:
    def test_one_iteration_fails(self) -> None:
        result = check_agentic_quality(
            content="A" * 200, tool_calls_count=2, iterations=1
        )
        assert result.passed is False
        assert "insufficient iterations" in result.reason

    def test_two_iterations_passes(self) -> None:
        result = check_agentic_quality(
            content="A" * 200, tool_calls_count=2, iterations=2
        )
        assert result.passed is True


@pytest.mark.unit
class TestHappyPath:
    def test_all_checks_pass(self) -> None:
        result = check_agentic_quality(
            content="The delegation system uses a ReAct loop " + "x" * 200,
            tool_calls_count=5,
            iterations=4,
        )
        assert result.passed is True
        assert result.reason == ""

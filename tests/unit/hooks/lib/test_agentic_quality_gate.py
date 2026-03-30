# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for agentic_quality_gate.py (OMN-5729, OMN-6961)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "agentic_quality_gate.py"
)
_spec = importlib.util.spec_from_file_location("agentic_quality_gate", _MODULE_PATH)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
sys.modules["agentic_quality_gate"] = _mod
_spec.loader.exec_module(_mod)

check_agentic_quality = _mod.check_agentic_quality


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
            content="The file src/main.py contains " + "x" * 200,
            tool_calls_count=1,
            iterations=3,
        )
        assert result.passed is True


@pytest.mark.unit
class TestContentLengthCheck:
    def test_none_content_fails(self) -> None:
        result = check_agentic_quality(content=None, tool_calls_count=2, iterations=3)
        assert result.passed is False

    def test_empty_content_fails(self) -> None:
        result = check_agentic_quality(content="", tool_calls_count=2, iterations=3)
        assert result.passed is False

    def test_short_content_fails(self) -> None:
        result = check_agentic_quality(
            content="Too short", tool_calls_count=2, iterations=3
        )
        assert result.passed is False

    def test_whitespace_only_content_fails(self) -> None:
        result = check_agentic_quality(
            content="   \n\t  ", tool_calls_count=2, iterations=3
        )
        assert result.passed is False


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

    def test_refusal_deep_in_content_passes(self) -> None:
        prefix = "The file handler.py at line 42 shows " + "A" * 270
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
            content="The file main.py has " + "A" * 200,
            tool_calls_count=2,
            iterations=1,
        )
        assert result.passed is False
        assert "insufficient iterations" in result.reason

    def test_two_iterations_passes(self) -> None:
        result = check_agentic_quality(
            content="The file main.py has " + "A" * 200,
            tool_calls_count=2,
            iterations=2,
        )
        assert result.passed is True


@pytest.mark.unit
class TestGroundingCheck:
    def test_no_grounding_fails(self) -> None:
        result = check_agentic_quality(
            content="This is a general discussion about software " * 10,
            tool_calls_count=3,
            iterations=3,
        )
        assert result.passed is False
        assert "grounding" in result.reason

    def test_file_path_is_grounding(self) -> None:
        result = check_agentic_quality(
            content="The entry point is in src/main.py which handles " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True

    def test_python_def_is_grounding(self) -> None:
        result = check_agentic_quality(
            content="The function def handle_request is responsible for " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True

    def test_backtick_code_ref_is_grounding(self) -> None:
        result = check_agentic_quality(
            content="The module `delegation_daemon` handles background jobs "
            + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True

    def test_line_number_ref_is_grounding(self) -> None:
        result = check_agentic_quality(
            content="The error occurs at line 42 in the handler where " + "x" * 200,
            tool_calls_count=2,
            iterations=3,
        )
        assert result.passed is True


@pytest.mark.unit
class TestHappyPath:
    def test_all_checks_pass(self) -> None:
        result = check_agentic_quality(
            content="The delegation system in delegation_orchestrator.py uses "
            "a ReAct loop (def run_agentic_loop) " + "x" * 200,
            tool_calls_count=5,
            iterations=4,
        )
        assert result.passed is True
        assert result.reason == ""

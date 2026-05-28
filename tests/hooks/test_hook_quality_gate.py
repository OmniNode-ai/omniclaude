# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for hook_quality_gate (T19).

Tests the ModelHookQualityGateInput/Result shapes, run_hook_quality_gate
pure function, and the hook_quality_result_from_gate bridge to T18 telemetry.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_GATE_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "hook_quality_gate.py"
)
_TELEMETRY_PATH = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "hook_delegation_telemetry.py"
)


def _load(name: str, path: Path) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_gate = _load("hook_quality_gate", _GATE_PATH)
_telemetry = _load("hook_delegation_telemetry", _TELEMETRY_PATH)

ModelHookQualityGateInput = _gate.ModelHookQualityGateInput
ModelHookQualityGateResult = _gate.ModelHookQualityGateResult
run_hook_quality_gate = _gate.run_hook_quality_gate
hook_quality_result_from_gate = _telemetry.hook_quality_result_from_gate
HookQualityResult = _telemetry.HookQualityResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_input(
    content: str,
    task_type: str = "research",
    tool_calls_count: int = 0,
    iterations: int = 0,
    expected_markers: tuple[str, ...] = (),
    min_response_length: int = 0,
) -> ModelHookQualityGateInput:
    return ModelHookQualityGateInput(
        correlation_id="corr-test",
        task_type=task_type,
        llm_response_content=content,
        tool_calls_count=tool_calls_count,
        iterations=iterations,
        expected_markers=expected_markers,
        min_response_length=min_response_length,
    )


def _run(content: str, **kwargs: object) -> ModelHookQualityGateResult:
    return run_hook_quality_gate(_make_input(content, **kwargs))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ModelHookQualityGateResult shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelHookQualityGateResult:
    def test_hook_path_non_authoritative_always_true(self) -> None:
        result = _run("x" * 100)
        assert result.hook_path_non_authoritative is True

    def test_to_dict_has_expected_keys(self) -> None:
        result = _run("x" * 100)
        d = result.to_dict()
        assert "correlation_id" in d
        assert "passed" in d
        assert "fail_category" in d
        assert "quality_score" in d
        assert "failure_reasons" in d
        assert "fallback_recommended" in d
        assert d["hook_path_non_authoritative"] is True

    def test_fail_category_never_fail_deterministic(self) -> None:
        # Hook gate only emits "pass" or "fail_heuristic"
        result = _run("")
        assert result.fail_category in ("pass", "fail_heuristic")

    def test_frozen(self) -> None:
        result = _run("x" * 100)
        with pytest.raises(Exception):
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunHookQualityGatePasses:
    def test_adequate_response_passes(self) -> None:
        content = "x" * 100
        result = _run(content, task_type="research")
        assert result.passed is True
        assert result.fail_category == "pass"
        assert result.quality_score >= 0.6

    def test_long_response_full_score(self) -> None:
        content = "a" * 200
        result = _run(content)
        assert result.passed is True
        assert result.quality_score == pytest.approx(1.0)

    def test_thinking_traces_stripped_before_check(self) -> None:
        # Thinking trace padded with junk — stripped content is still adequate
        content = "<think>internal reasoning here</think>" + "x" * 100
        result = _run(content, task_type="research")
        assert result.passed is True

    def test_markers_present_passes(self) -> None:
        content = "def test_foo(): assert True\n" + "x" * 80
        result = _run(content, task_type="test", expected_markers=("def test_",))
        assert result.passed is True

    def test_document_task_type_min_length(self) -> None:
        # document minimum is 100 chars
        content = "d" * 100
        result = _run(content, task_type="document")
        assert result.passed is True


# ---------------------------------------------------------------------------
# Failure cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunHookQualityGateFails:
    def test_empty_response_fails(self) -> None:
        result = _run("")
        assert result.passed is False
        assert result.fail_category == "fail_heuristic"
        assert any("WEAK_OUTPUT" in r for r in result.failure_reasons)

    def test_too_short_fails(self) -> None:
        result = _run("hi", task_type="research")
        assert result.passed is False
        assert any("WEAK_OUTPUT" in r for r in result.failure_reasons)

    def test_refusal_phrase_fails(self) -> None:
        content = "I cannot help with that task. " + "x" * 100
        result = _run(content)
        assert result.passed is False
        assert result.fail_category == "fail_heuristic"
        assert any("REFUSAL" in r for r in result.failure_reasons)

    def test_refusal_sets_fallback_recommended(self) -> None:
        content = "As an AI, I cannot do that. " + "x" * 100
        result = _run(content)
        assert result.fallback_recommended is True

    def test_missing_markers_reduces_score_and_adds_reason(self) -> None:
        # Missing markers add a TASK_MISMATCH reason and reduce quality_score
        # but do NOT fail the gate alone when length and no_refusal both pass
        # (mirrors runtime gate: markers are heuristic, not blocking by themselves).
        # score = length(1.0)*0.4 + no_refusal(1.0)*0.3 + markers(0.0)*0.3 = 0.7
        # passed because 0.7 >= 0.6 AND no_refusal=1.0 AND length=1.0
        content = "x" * 100
        result = _run(content, expected_markers=("def test_", "@pytest.mark"))
        assert any("TASK_MISMATCH" in r for r in result.failure_reasons)
        assert result.quality_score == pytest.approx(0.7)

    def test_token_limit_marker_fails(self) -> None:
        content = "some output<|im_end|>rest of content"
        result = _run(content)
        assert result.passed is False
        assert any("MALFORMED" in r for r in result.failure_reasons)
        assert result.fallback_recommended is True

    def test_endoftext_marker_fails(self) -> None:
        content = "output<|endoftext|>"
        result = _run(content)
        assert result.passed is False
        assert any("MALFORMED" in r for r in result.failure_reasons)

    def test_truncated_marker_fails(self) -> None:
        content = "some response [TRUNCATED]"
        result = _run(content)
        assert result.passed is False

    def test_refusal_fails_gate_and_records_failure(self) -> None:
        # Refusal detected → no_refusal=0.0 → gate fails (no_refusal requirement).
        # score = length(1.0)*0.4 + no_refusal(0.0)*0.3 + markers(1.0)*0.3 = 0.7
        # but passed=False because no_refusal != 1.0
        content = "I'm sorry, I cannot help. " + "x" * 100
        result = _run(content)
        assert result.passed is False
        assert result.quality_score == pytest.approx(0.7)
        assert any("REFUSAL" in r for r in result.failure_reasons)

    def test_quality_score_partial_on_length_failure_only(self) -> None:
        # No refusal, but content too short: length=0.0, no_refusal=1.0, markers=1.0
        # score = 0.0*0.4 + 1.0*0.3 + 1.0*0.3 = 0.6  → exactly at threshold
        # With task_type min_length=60, len("x"*59)=59 < 60 → length fails
        content = "x" * 59
        result = _run(content, task_type="research")
        assert result.passed is False
        assert result.quality_score == pytest.approx(0.6, abs=0.01)

    def test_custom_min_length_overrides_task_type(self) -> None:
        content = "x" * 50
        # Default for "research" is 60, but we override to 200
        result = _run(content, task_type="research", min_response_length=200)
        assert result.passed is False
        assert any("WEAK_OUTPUT" in r for r in result.failure_reasons)


# ---------------------------------------------------------------------------
# Task-type specific behaviour
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskTypeDefaults:
    def test_agentic_min_length_100(self) -> None:
        result = _run("x" * 99, task_type="agentic")
        assert result.passed is False

        result2 = _run("x" * 100, task_type="agentic")
        assert result2.passed is True

    def test_test_min_length_80(self) -> None:
        result = _run("x" * 79, task_type="test")
        assert result.passed is False

        result2 = _run("x" * 80, task_type="test")
        assert result2.passed is True

    def test_unknown_task_type_uses_default_60(self) -> None:
        result = _run("x" * 59, task_type="unknown_custom")
        assert result.passed is False

        result2 = _run("x" * 60, task_type="unknown_custom")
        assert result2.passed is True


# ---------------------------------------------------------------------------
# hook_quality_result_from_gate bridge (T18 <-> T19)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHookQualityResultFromGate:
    def test_passing_gate_produces_passed_result(self) -> None:
        gate_dict = {
            "passed": True,
            "fail_category": "pass",
            "quality_score": 1.0,
            "failure_reasons": [],
            "fallback_recommended": False,
            "hook_path_non_authoritative": True,
        }
        qr = hook_quality_result_from_gate(gate_dict)
        assert isinstance(qr, HookQualityResult)
        assert qr.passed is True
        assert qr.reason == ""
        assert qr.authoritative is False

    def test_failing_gate_propagates_reason(self) -> None:
        gate_dict = {
            "passed": False,
            "fail_category": "fail_heuristic",
            "quality_score": 0.3,
            "failure_reasons": ["WEAK_OUTPUT: too short", "REFUSAL: detected phrase"],
            "fallback_recommended": True,
            "hook_path_non_authoritative": True,
        }
        qr = hook_quality_result_from_gate(gate_dict)
        assert qr.passed is False
        assert "WEAK_OUTPUT" in qr.reason
        assert "REFUSAL" in qr.reason
        assert qr.authoritative is False

    def test_empty_failure_reasons_gives_empty_string(self) -> None:
        gate_dict = {"passed": True, "failure_reasons": []}
        qr = hook_quality_result_from_gate(gate_dict)
        assert qr.reason == ""

    def test_missing_passed_defaults_to_true(self) -> None:
        qr = hook_quality_result_from_gate({})
        assert qr.passed is True

    def test_roundtrip_with_run_gate(self) -> None:
        content = "x" * 100
        gate_result = run_hook_quality_gate(_make_input(content))
        qr = hook_quality_result_from_gate(gate_result.to_dict())
        assert qr.passed == gate_result.passed
        assert qr.authoritative is False

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Post-response quality gate for hook delegation (T19).

Runs after the LLM/agentic loop returns text, using the same contract shape as
the runtime delegation quality gate (node_delegation_quality_gate_reducer).

This module is intentionally standalone — it does NOT import from omnibase_compat
or omnimarket so it can run inside the plugin lib without those packages installed.
The field names and category literals match the canonical wire DTOs so that
downstream consumers (omnidash, projectors) can treat hook-path gate results the
same way as runtime-path gate results.

Runtime quality gate reference:
    omnimarket/src/omnimarket/nodes/node_delegation_quality_gate_reducer/
        handlers/handler_quality_gate.py  — delta() pure function
    omnibase_compat/src/omnibase_compat/contracts/delegation/wire/
        model_quality_gate.py             — ModelQualityGateInput / ModelQualityGateResult

Semantic differences from the runtime gate:
    - dod_deterministic / dod_heuristic: not resolved from task_class_contracts.yaml;
      falls through to legacy heuristic checks (length, refusal, markers)
    - fail_category="fail_deterministic" is not emitted here — the hook path does not
      block Claude based on this gate; it is advisory/telemetry only
    - quality_score is a 0.0-1.0 heuristic based on three checks, not a DoD score

All results are NON-AUTHORITATIVE. See docs/architecture/omniclaude-delegation-classification.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Mirror the canonical EnumQualityGateCategory literal without importing omnibase_compat
EnumHookQualityGateCategory = Literal["pass", "fail_deterministic", "fail_heuristic"]

# Refusal phrases — matches the runtime gate's _REFUSAL_PHRASES set
_REFUSAL_PHRASES: tuple[str, ...] = (
    "i cannot",
    "i'm sorry",
    "as an ai",
    "error:",
    "traceback",
    "i'm unable",
    "i apologize",
    "i don't have",
    "i can't",
    "i am unable",
    "sorry, i",
    "unfortunately, i",
)

# Minimum response lengths by task type — matches runtime _MIN_LENGTHS
_MIN_LENGTHS: dict[str, int] = {
    "document": 100,
    "test": 80,
    "research": 60,
    "agentic": 100,
}
_DEFAULT_MIN_LENGTH = 60

# Scoring weights — matches runtime gate
_WEIGHT_LENGTH: float = 0.4
_WEIGHT_NO_REFUSAL: float = 0.3
_WEIGHT_MARKERS: float = 0.3

# Token-limit error markers (agentic path specific)
_TOKEN_LIMIT_MARKERS: tuple[str, ...] = (
    "<|im_end|>",
    "<|endoftext|>",
    "[TRUNCATED]",
)

_THINKING_TRACE_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _strip_thinking_traces(content: str) -> str:
    return _THINKING_TRACE_RE.sub("", content)


@dataclass(frozen=True)
class ModelHookQualityGateInput:
    """Input to the hook quality gate.

    Mirrors ModelQualityGateInput from omnibase_compat wire DTOs.
    All fields are NON-AUTHORITATIVE.
    """

    correlation_id: str
    task_type: str
    llm_response_content: str
    # NON-AUTHORITATIVE: tool calls count from agentic loop; 0 for sync delegation
    tool_calls_count: int = 0
    # NON-AUTHORITATIVE: iterations from agentic loop; 0 for sync delegation
    iterations: int = 0
    expected_markers: tuple[str, ...] = ()
    min_response_length: int = 0  # 0 = use task_type default


@dataclass(frozen=True)
class ModelHookQualityGateResult:
    """Output of the hook quality gate.

    Mirrors ModelQualityGateResult from omnibase_compat wire DTOs.
    All fields are NON-AUTHORITATIVE — hook_path_non_authoritative is always True.
    fail_category="fail_deterministic" is never emitted (hook gate is advisory only).
    """

    correlation_id: str
    passed: bool
    # "pass" | "fail_heuristic" only — hook gate never hard-blocks
    fail_category: str  # EnumHookQualityGateCategory
    quality_score: float
    failure_reasons: tuple[str, ...]
    fallback_recommended: bool
    # Always True — marker for downstream consumers
    hook_path_non_authoritative: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "correlation_id": self.correlation_id,
            "passed": self.passed,
            "fail_category": self.fail_category,
            "quality_score": self.quality_score,
            "failure_reasons": list(self.failure_reasons),
            "fallback_recommended": self.fallback_recommended,
            "hook_path_non_authoritative": self.hook_path_non_authoritative,
        }


def run_hook_quality_gate(
    gate_input: ModelHookQualityGateInput,
) -> ModelHookQualityGateResult:
    """Evaluate LLM output quality for a hook delegation response.

    Pure function: deterministic for given input, no I/O.

    Uses the same heuristic checks as the runtime gate's legacy fallback path:
    length, refusal detection, and marker presence. Never emits fail_deterministic
    (the hook gate is advisory/telemetry only — it does not block Claude).

    Args:
        gate_input: Input with LLM response, task type, and optional markers.

    Returns:
        ModelHookQualityGateResult with pass/fail verdict, score, and reasons.
    """
    content = _strip_thinking_traces(gate_input.llm_response_content)
    task_type = gate_input.task_type
    failure_reasons: list[str] = []
    scores: dict[str, float] = {}

    # Check 1: Token-limit truncation markers (agentic-specific)
    for marker in _TOKEN_LIMIT_MARKERS:
        if marker in content:
            failure_reasons.append(
                f"MALFORMED: response contains token-limit marker '{marker}'"
            )
            return ModelHookQualityGateResult(
                correlation_id=gate_input.correlation_id,
                passed=False,
                fail_category="fail_heuristic",
                quality_score=0.0,
                failure_reasons=tuple(failure_reasons),
                fallback_recommended=True,
            )

    # Check 2: Minimum length
    min_length = (
        gate_input.min_response_length
        if gate_input.min_response_length > 0
        else _MIN_LENGTHS.get(task_type, _DEFAULT_MIN_LENGTH)
    )
    if len(content) >= min_length:
        scores["length"] = 1.0
    else:
        scores["length"] = 0.0
        failure_reasons.append(
            f"WEAK_OUTPUT: response length {len(content)} below minimum {min_length}"
        )

    # Check 3: No refusal phrases (first 200 chars)
    first_200 = content[:200].lower()
    detected = [p for p in _REFUSAL_PHRASES if p in first_200]
    if not detected:
        scores["no_refusal"] = 1.0
    else:
        scores["no_refusal"] = 0.0
        failure_reasons.append(
            f"REFUSAL: detected refusal phrases: {', '.join(detected)}"
        )

    # Check 4: Expected markers (task-type specific)
    expected_markers = gate_input.expected_markers
    if not expected_markers:
        scores["markers"] = 1.0
    else:
        content_lower = content.lower()
        found = sum(1 for m in expected_markers if m.lower() in content_lower)
        scores["markers"] = found / len(expected_markers)
        if scores["markers"] < 1.0:
            missing = [m for m in expected_markers if m.lower() not in content_lower]
            failure_reasons.append(
                f"TASK_MISMATCH: missing expected markers: {', '.join(missing)}"
            )

    quality_score = round(
        scores["length"] * _WEIGHT_LENGTH
        + scores["no_refusal"] * _WEIGHT_NO_REFUSAL
        + scores["markers"] * _WEIGHT_MARKERS,
        3,
    )

    # Pass requires: no refusal AND length met AND overall score >= 0.6.
    # Length is a hard requirement: a response that is too short is not acceptable
    # regardless of the combined score, since 0.0*0.4 + 1.0*0.3 + 1.0*0.3 = 0.6
    # would otherwise slip through exactly at the threshold.
    passed = (
        quality_score >= 0.6
        and scores["no_refusal"] == 1.0
        and scores.get("length", 0.0) == 1.0
    )
    fallback_recommended = not passed and scores["no_refusal"] == 0.0

    return ModelHookQualityGateResult(
        correlation_id=gate_input.correlation_id,
        passed=passed,
        fail_category="pass" if passed else "fail_heuristic",
        quality_score=quality_score,
        failure_reasons=tuple(failure_reasons),
        fallback_recommended=fallback_recommended,
    )


__all__: list[str] = [
    "EnumHookQualityGateCategory",
    "ModelHookQualityGateInput",
    "ModelHookQualityGateResult",
    "run_hook_quality_gate",
]

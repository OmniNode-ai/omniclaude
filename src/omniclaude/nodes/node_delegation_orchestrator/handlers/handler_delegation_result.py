# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Delegation result handler with quality gate and metrics.

Receives LLM response from the effect node, runs quality gate with
failure class preservation, computes savings, emits terminal events.

Quality gate failure classes:
    - REFUSAL: model refused the task ("I cannot", "I don't have")
    - MALFORMED: response doesn't match expected structure
    - TOO_SHORT: below minimum length for intent
    - TASK_MISMATCH: response content doesn't match requested intent
    - LOW_UTILITY: generic/low-value response
    - PASS: quality gate passed

Related:
    - OMN-7110: Implement delegation result handler with quality gate
    - OMN-7103: Node-Based LLM Delegation Workflow
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class EnumQualityGateResult(StrEnum):
    """Quality gate failure classes."""

    PASSED = "passed"  # noqa: S105
    REFUSAL = "refusal"
    MALFORMED = "malformed"
    TOO_SHORT = "too_short"
    TASK_MISMATCH = "task_mismatch"
    LOW_UTILITY = "low_utility"


# Refusal indicators — checked in first 200 chars of response
_REFUSAL_INDICATORS: tuple[str, ...] = (
    "i cannot",
    "i'm unable",
    "i apologize",
    "as an ai",
    "i don't have",
    "i can't",
)

# Minimum response length per intent type
_MIN_LENGTH: dict[str, int] = {
    "document": 100,
    "test": 80,
    "research": 60,
    "implement": 50,
}

# Task-type markers that indicate the response matches the intent
_TASK_MARKERS: dict[str, tuple[str, ...]] = {
    "test": ("def test_", "class Test", "@pytest", "assert "),
    "document": (
        '"""',
        "Args:",
        "Returns:",
        "Parameters:",
        "#",
        "Description",
        "Overview",
    ),
}


def run_quality_gate(
    response_text: str,
    intent: str,
) -> tuple[EnumQualityGateResult, str]:
    """Run quality gate with failure class preservation.

    Returns:
        Tuple of (result, reason). Result is always set.
    """
    if not response_text:
        return EnumQualityGateResult.MALFORMED, "empty response"

    # Check minimum length
    min_len = _MIN_LENGTH.get(intent, 50)
    if len(response_text) < min_len:
        return (
            EnumQualityGateResult.TOO_SHORT,
            f"response {len(response_text)} chars < {min_len} minimum for {intent}",
        )

    # Check refusal indicators in first 200 chars
    preview = response_text[:200].lower()
    for indicator in _REFUSAL_INDICATORS:
        if indicator in preview:
            return EnumQualityGateResult.REFUSAL, f"refusal indicator: {indicator!r}"

    # Check task-type markers (optional — only for test/document)
    markers = _TASK_MARKERS.get(intent)
    if markers:
        has_marker = any(m.lower() in response_text.lower() for m in markers)
        if not has_marker:
            return (
                EnumQualityGateResult.LOW_UTILITY,
                f"no task markers found for {intent} (expected one of: {markers[:3]})",
            )

    return EnumQualityGateResult.PASSED, ""


def handle_delegation_result(
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Process LLM response, run quality gate, build terminal event.

    Args:
        payload: LLM response payload with 'generated_text', 'model_used',
            'intent', 'correlation_id', 'latency_ms', 'confidence',
            'estimated_savings_usd'.

    Returns:
        Dict with terminal event data: delegation_success, quality_gate_result,
        quality_gate_reason, model, intent, latency, savings, response.
    """
    generated_text = payload.get("generated_text") or ""
    intent = payload.get("intent", "")
    correlation_id = payload.get("correlation_id", "")
    model_used = payload.get("model_used", "unknown")
    latency_ms = payload.get("latency_ms", 0)
    confidence = payload.get("confidence", 0.0)
    savings = payload.get("estimated_savings_usd", 0.0)

    # Strip reasoning model prefixes (Qwen3 <think>, GLM reasoning_content)
    clean_text = generated_text
    if "<think>" in clean_text:
        # Strip Qwen3 chain-of-thought
        think_end = clean_text.rfind("</think>")
        if think_end != -1:
            clean_text = clean_text[think_end + 8 :].strip()

    # Run quality gate
    gate_result, gate_reason = run_quality_gate(clean_text, intent)

    result = {
        "correlation_id": correlation_id,
        "delegation_success": gate_result == EnumQualityGateResult.PASSED,
        "quality_gate_result": gate_result.value,
        "quality_gate_reason": gate_reason,
        "model_used": model_used,
        "intent": intent,
        "confidence": confidence,
        "latency_ms": latency_ms,
        "estimated_savings_usd": savings
        if gate_result == EnumQualityGateResult.PASSED
        else 0.0,
        "response_length": len(clean_text),
    }

    if gate_result == EnumQualityGateResult.PASSED:
        result["response"] = clean_text
        logger.info(
            "Delegation completed: model=%s intent=%s latency=%dms savings=$%.4f (correlation_id=%s)",
            model_used,
            intent,
            latency_ms,
            savings,
            correlation_id,
        )
    else:
        logger.warning(
            "Delegation failed quality gate: model=%s intent=%s result=%s reason=%s (correlation_id=%s)",
            model_used,
            intent,
            gate_result.value,
            gate_reason,
            correlation_id,
        )

    return result


__all__ = [
    "EnumQualityGateResult",
    "handle_delegation_result",
    "run_quality_gate",
]

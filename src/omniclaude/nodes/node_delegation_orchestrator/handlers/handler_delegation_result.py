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

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_result import (
    ModelDelegationOutcome,
)

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


class ModelLlmResponsePayload(BaseModel):
    """Inbound LLM response from an effect node — input to the result handler."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    generated_text: str = Field(default="", description="LLM-generated text")
    model_used: str = Field(
        default="unknown", description="Model that produced the response"
    )
    intent: str = Field(default="", description="Classified task intent")
    correlation_id: str = Field(default="", description="Correlation ID")
    latency_ms: float = Field(default=0.0, ge=0.0, description="E2E latency in ms")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Classification confidence"
    )
    estimated_savings_usd: float = Field(
        default=0.0, ge=0.0, description="Cost savings estimate"
    )


def handle_delegation_result(
    payload: ModelLlmResponsePayload,
) -> ModelDelegationOutcome:
    """Process LLM response, run quality gate, build terminal event.

    Args:
        payload: Typed LLM response payload from the effect node.

    Returns:
        Typed delegation outcome with quality gate result and metrics.
    """
    # Strip reasoning model prefixes (Qwen3 <think>, GLM reasoning_content)
    clean_text = payload.generated_text
    if "<think>" in clean_text:
        think_end = clean_text.rfind("</think>")
        if think_end != -1:
            clean_text = clean_text[think_end + 8 :].strip()

    # Run quality gate
    gate_result, gate_reason = run_quality_gate(clean_text, payload.intent)
    success = gate_result == EnumQualityGateResult.PASSED

    if success:
        logger.info(
            "Delegation completed: model=%s intent=%s latency=%dms savings=$%.4f (correlation_id=%s)",
            payload.model_used,
            payload.intent,
            payload.latency_ms,
            payload.estimated_savings_usd,
            payload.correlation_id,
        )
    else:
        logger.warning(
            "Delegation failed quality gate: model=%s intent=%s result=%s reason=%s (correlation_id=%s)",
            payload.model_used,
            payload.intent,
            gate_result.value,
            gate_reason,
            payload.correlation_id,
        )

    return ModelDelegationOutcome(
        correlation_id=payload.correlation_id,
        delegation_success=success,
        quality_gate_result=gate_result.value,
        quality_gate_reason=gate_reason,
        model_used=payload.model_used,
        intent=payload.intent,
        confidence=payload.confidence,
        latency_ms=payload.latency_ms,
        estimated_savings_usd=payload.estimated_savings_usd if success else 0.0,
        response_length=len(clean_text),
        response=clean_text if success else None,
    )


__all__ = [
    "EnumQualityGateResult",
    "ModelLlmResponsePayload",
    "handle_delegation_result",
    "run_quality_gate",
]

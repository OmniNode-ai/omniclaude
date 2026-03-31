# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegation result models — dispatch routing and terminal outcome.

Published to ``onex.evt.omniclaude.delegation-completed.v1`` or
``onex.evt.omniclaude.delegation-failed.v1``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelDelegationDispatchResult(BaseModel):
    """Result of the dispatch handler — routing decision.

    Attributes:
        routed: Whether the prompt was classified as delegatable and a backend was found.
        backend: Selected backend identifier (local_vllm, gemini_cli, codex_cli, glm).
        base_url: Endpoint URL for the selected backend.
        model: Model identifier for the selected backend.
        api_key: API key for authenticated backends (GLM). None for local/CLI.
        timeout: Timeout in seconds for the selected backend.
        intent: Classified task intent (document, test, research, implement).
        confidence: Classification confidence score (0.0-1.0).
        estimated_savings_usd: Estimated cost savings vs primary model.
        prompt: The original prompt being delegated.
        correlation_id: Correlation ID for distributed tracing.
        session_id: Claude Code session ID.
        reason: Reason for non-delegation (empty when routed=True).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    routed: bool = Field(..., description="Whether delegation was routed to a backend")
    backend: str = Field(default="", description="Selected backend identifier")
    base_url: str = Field(default="", description="Backend endpoint URL")
    model: str = Field(default="", description="Model identifier")
    api_key: str | None = Field(default=None, description="API key for auth (GLM)")
    timeout: int = Field(default=30, ge=1, description="Backend timeout in seconds")
    intent: str = Field(default="", description="Classified task intent")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Classification confidence"
    )
    estimated_savings_usd: float = Field(
        default=0.0, ge=0.0, description="Estimated cost savings"
    )
    prompt: str = Field(default="", description="Original prompt")
    correlation_id: str = Field(default="", description="Correlation ID")
    session_id: str = Field(default="", description="Session ID")
    reason: str = Field(default="", description="Reason for non-delegation")


class ModelDelegationOutcome(BaseModel):
    """Terminal delegation result — emitted as completion or failure event.

    Attributes:
        correlation_id: Correlation ID for distributed tracing.
        delegation_success: Whether the delegation passed quality gate.
        quality_gate_result: Quality gate outcome (passed, refusal, malformed, etc.).
        quality_gate_reason: Human-readable reason for gate failure.
        model_used: Model that generated the response.
        intent: Classified task intent.
        confidence: Classification confidence.
        latency_ms: End-to-end latency in milliseconds.
        estimated_savings_usd: Cost savings (0 if gate failed).
        response_length: Length of the generated response.
        response: The generated response text (only on success).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    correlation_id: str = Field(default="", description="Correlation ID")
    delegation_success: bool = Field(..., description="Whether quality gate passed")
    quality_gate_result: str = Field(..., description="Gate outcome class")
    quality_gate_reason: str = Field(default="", description="Gate failure reason")
    model_used: str = Field(default="", description="Model that generated the response")
    intent: str = Field(default="", description="Classified task intent")
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Classification confidence"
    )
    latency_ms: float = Field(default=0.0, ge=0.0, description="E2E latency in ms")
    estimated_savings_usd: float = Field(
        default=0.0, ge=0.0, description="Cost savings"
    )
    response_length: int = Field(
        default=0, ge=0, description="Response length in chars"
    )
    response: str | None = Field(
        default=None, description="Generated text (only on success)"
    )


__all__ = [
    "ModelDelegationDispatchResult",
    "ModelDelegationOutcome",
]

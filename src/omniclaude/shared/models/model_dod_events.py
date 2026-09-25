# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""DoD (Definition of Done) guard event model (OMN-5197).

Topic:
    onex.evt.omniclaude.dod-guard-fired.v1       (append-only, each event unique)

The verification-completed event is omnimarket's node_dod_verify terminal.
This package's own flat telemetry spelling of it had no consumer and was
retired by OMN-19153.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelDodGuardFiredEvent(BaseModel):
    """Emitted on every DoD guard interception (pre-tool-use hook).

    Attributes:
        ticket_id: Linear ticket identifier.
        session_id: Claude Code session identifier.
        correlation_id: End-to-end correlation identifier (OMN-6884).
        guard_outcome: Guard decision — allowed, warned, or blocked.
        policy_mode: DoD enforcement policy — advisory, soft, or hard.
        receipt_age_seconds: Seconds since the last DoD receipt (None if no receipt).
        receipt_pass: Whether the receipt indicated a passing DoD run (None if no receipt).
        timestamp: ISO 8601 UTC timestamp of the guard firing.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    ticket_id: str
    session_id: str
    # OMN-6884: correlation_id was missing. Guard firings always occur
    # within a session context, so correlation_id is required for tracing.
    correlation_id: str
    guard_outcome: str  # allowed | warned | blocked
    policy_mode: str
    receipt_age_seconds: float | None
    receipt_pass: bool | None
    timestamp: str  # ISO 8601


__all__ = [
    "ModelDodGuardFiredEvent",
]

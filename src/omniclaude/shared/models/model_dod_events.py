# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""DoD (Definition of Done) verification event models for OMN-5197.

Two new event types for DoD telemetry consumed by omnidash:

Topics:
    onex.evt.omniclaude.dod-verify-completed.v1  (append-only, dedup by run_id)
    onex.evt.omniclaude.dod-guard-fired.v1       (append-only, each event unique)

These events close the DoD observability gap: DoD verification currently writes
local JSON files but emits no Kafka events, so omnidash has no visibility into
DoD data.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelDodVerifyCompletedEvent(BaseModel):
    """Emitted after every DoD evidence verification run.

    Attributes:
        ticket_id: Linear ticket identifier (e.g. "OMN-5197").
        run_id: Unique evidence run identifier — dedup key for projection.
        session_id: Claude Code session identifier.
        correlation_id: End-to-end correlation identifier.
        total_checks: Total number of DoD checks evaluated.
        passed_checks: Number of checks that passed.
        failed_checks: Number of checks that failed.
        skipped_checks: Number of checks that were skipped.
        overall_pass: Whether the overall verification passed.
        policy_mode: DoD enforcement policy — advisory, soft, or hard.
        evidence_items: Serialized EvidenceRunResult items.
        timestamp: ISO 8601 UTC timestamp of the verification run.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    run_id: str
    session_id: str
    correlation_id: str
    total_checks: int
    passed_checks: int
    failed_checks: int
    skipped_checks: int
    overall_pass: bool
    policy_mode: str  # advisory | soft | hard
    evidence_items: list[dict[str, object]]
    timestamp: str  # ISO 8601


class ModelDodGuardFiredEvent(BaseModel):
    """Emitted on every DoD guard interception (pre-tool-use hook).

    Attributes:
        ticket_id: Linear ticket identifier.
        session_id: Claude Code session identifier.
        guard_outcome: Guard decision — allowed, warned, or blocked.
        policy_mode: DoD enforcement policy — advisory, soft, or hard.
        receipt_age_seconds: Seconds since the last DoD receipt (None if no receipt).
        receipt_pass: Whether the receipt indicated a passing DoD run (None if no receipt).
        timestamp: ISO 8601 UTC timestamp of the guard firing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str
    session_id: str
    guard_outcome: str  # allowed | warned | blocked
    policy_mode: str
    receipt_age_seconds: float | None
    receipt_pass: bool | None
    timestamp: str  # ISO 8601


__all__ = [
    "ModelDodVerifyCompletedEvent",
    "ModelDodGuardFiredEvent",
]

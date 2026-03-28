# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Coordination signal models for multi-session awareness (OMN-6857).

Coordination signals enable concurrent Claude Code sessions to share awareness
of each other's work via Kafka events. Signals are emitted at key pipeline
moments (PR merged, ticket claimed, conflict detected) and consumed by
projectors that materialize session state.

Doctrine D5: Signals use ModelCoordinationSignalPayload with typed fields
(repo, file_paths, pr_number, related_task_id, reason), not bare dict.

Doctrine D6: Conflict signals from graph projector are advisory hints,
not control events.

Design:
    - emitted_at must be explicitly injected (no datetime.now default)
    - All models are frozen (immutable after construction)
    - Signal-specific extras use dict[str, object] for extensibility
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnumCoordinationSignalType(StrEnum):
    """Types of coordination signals emitted between sessions.

    Values:
        PR_MERGED: A PR was merged — downstream sessions may need to rebase.
        REBASE_NEEDED: A session detected it needs to rebase against merged changes.
        CONFLICT_DETECTED: File-level conflict detected between concurrent sessions.
        TICKET_CLAIMED: A session has claimed a ticket for active work.
        TICKET_COMPLETED: A session has completed work on a ticket.
        FILES_CHANGED: Significant file changes that may affect other sessions.
    """

    PR_MERGED = "pr_merged"
    REBASE_NEEDED = "rebase_needed"
    CONFLICT_DETECTED = "conflict_detected"
    TICKET_CLAIMED = "ticket_claimed"
    TICKET_COMPLETED = "ticket_completed"
    FILES_CHANGED = "files_changed"


class ModelCoordinationSignalPayload(BaseModel):
    """Structured payload for coordination signals (Doctrine D5).

    Common fields for all signal types. Signal-specific data goes in ``extra``.

    Attributes:
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        file_paths: List of affected file paths (may be empty).
        pr_number: PR number if applicable (None otherwise).
        related_task_id: Related ticket/task ID (e.g. "OMN-1234").
        reason: Human-readable reason for the signal.
        extra: Signal-specific additional data.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    repo: str = Field(
        ...,
        description="Repository slug (e.g. OmniNode-ai/omniclaude)",
    )
    file_paths: list[str] = Field(
        default_factory=list,
        description="Affected file paths",
    )
    pr_number: int | None = Field(
        default=None,
        description="PR number if applicable",
    )
    related_task_id: str | None = Field(
        default=None,
        description="Related ticket/task ID (e.g. OMN-1234)",
    )
    reason: str = Field(
        default="",
        description="Human-readable reason for the signal",
    )
    extra: dict[str, object] = Field(
        default_factory=dict,
        description="Signal-specific additional data",
    )


class ModelCoordinationSignal(BaseModel):
    """Full coordination signal envelope.

    Wraps a signal type, source identifiers, and structured payload.

    Attributes:
        signal_id: Unique identifier for this signal (UUID).
        signal_type: The type of coordination signal.
        task_id: The task/ticket ID this signal relates to.
        session_id: The session that emitted this signal.
        payload: Structured signal payload.
        emitted_at: Timestamp when the signal was emitted (UTC, explicitly injected).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    signal_id: UUID = Field(
        ...,
        description="Unique identifier for this signal",
    )
    signal_type: EnumCoordinationSignalType = Field(
        ...,
        description="Type of coordination signal",
    )
    task_id: str = Field(
        ...,
        description="Task/ticket ID this signal relates to",
    )
    session_id: str = Field(
        ...,
        description="Session that emitted this signal",
    )
    payload: ModelCoordinationSignalPayload = Field(
        ...,
        description="Structured signal payload",
    )
    emitted_at: datetime = Field(
        ...,
        description="Timestamp when the signal was emitted (UTC, explicitly injected)",
    )


__all__ = [
    "EnumCoordinationSignalType",
    "ModelCoordinationSignal",
    "ModelCoordinationSignalPayload",
]

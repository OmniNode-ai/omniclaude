# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Coordination signal models and conflict detection for multi-session awareness.

Coordination signals enable concurrent Claude Code sessions to share awareness
of each other's work via Kafka events. Signals are emitted at key pipeline
moments (PR merged, ticket claimed, conflict detected) and consumed by
projectors that materialize session state.

Doctrine D5: Signals use ModelCoordinationSignalPayload with typed fields
(repo, file_paths, pr_number, related_task_id, reason), not bare dict.

Doctrine D6: Conflict signals from graph projector are advisory hints,
not control events. Emission must remain idempotent (same conflict = same
signal_id via deterministic uuid5).

Design:
    - emitted_at must be explicitly injected (no datetime.now default)
    - All models are frozen (immutable after construction)
    - Signal-specific extras use dict[str, object] for extensibility
    - should_emit_conflict_signal() is a pure function for file overlap detection (OMN-6861)
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

# Namespace UUID for deterministic conflict signal IDs (OMN-6861).
# Same conflict (task pair + sorted shared files) always produces the same signal_id.
_CONFLICT_NAMESPACE = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


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


class ModelFileConflict(BaseModel):
    """A detected file-level conflict between two tasks (OMN-6861).

    Attributes:
        other_task_id: The task that shares files with the current task.
        shared_files: Sorted list of file paths both tasks touch.
        signal_id: Deterministic UUID5 for idempotent emission (Doctrine D6).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    other_task_id: str = Field(
        ...,
        description="Task ID of the conflicting session",
    )
    shared_files: list[str] = Field(
        ...,
        description="Sorted list of shared file paths",
    )
    signal_id: UUID = Field(
        ...,
        description="Deterministic UUID5 for idempotent emission",
    )


def _compute_conflict_signal_id(
    task_id_a: str,
    task_id_b: str,
    shared_files: list[str],
) -> UUID:
    """Compute a deterministic signal_id for a file conflict (Doctrine D6).

    The same pair of tasks with the same shared files always produces
    the same UUID, ensuring idempotent emission.
    """
    # Sort task IDs so order doesn't matter (A vs B == B vs A)
    sorted_tasks = sorted([task_id_a, task_id_b])
    # Files are already sorted by caller, but sort defensively
    sorted_files = sorted(shared_files)
    name = f"{sorted_tasks[0]}:{sorted_tasks[1]}:{','.join(sorted_files)}"
    return uuid5(_CONFLICT_NAMESPACE, name)


def should_emit_conflict_signal(
    current_task: dict[str, object],
    other_tasks: list[dict[str, object]],
) -> list[ModelFileConflict]:
    """Detect file-level conflicts between the current task and other active tasks.

    Pure function that compares file overlap. Returns a list of conflicts
    with ``other_task_id``, ``shared_files``, and a deterministic ``signal_id``.
    Empty list means no conflicts detected.

    This is an advisory detection function per Doctrine D6 -- the results are
    hints, not authoritative control events.

    Args:
        current_task: Dict with ``task_id`` (str) and ``files_touched`` (list[str]).
        other_tasks: List of dicts, each with ``task_id`` and ``files_touched``.

    Returns:
        List of ModelFileConflict for each task with overlapping files.
    """
    current_id = str(current_task.get("task_id", ""))
    current_files = set(current_task.get("files_touched", []))  # type: ignore[arg-type]
    if not current_files:
        return []

    conflicts: list[ModelFileConflict] = []
    for other in other_tasks:
        other_id = str(other.get("task_id", ""))
        if other_id == current_id:
            continue
        other_files = set(other.get("files_touched", []))  # type: ignore[arg-type]
        overlap = sorted(current_files & other_files)
        if overlap:
            signal_id = _compute_conflict_signal_id(current_id, other_id, overlap)
            conflicts.append(
                ModelFileConflict(
                    other_task_id=other_id,
                    shared_files=overlap,
                    signal_id=signal_id,
                )
            )
    return conflicts


__all__ = [
    "EnumCoordinationSignalType",
    "ModelCoordinationSignal",
    "ModelCoordinationSignalPayload",
    "ModelFileConflict",
    "should_emit_conflict_signal",
]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Skill completion event model — published after every skill invocation.

Emitted on both ``success`` and ``failed`` outcome topics as the authoritative
record of a completed skill run. Carries enough context to join with the
started event (via ``run_id``) and reconstruct a full execution trace.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus


class ModelSkillCompletionEvent(BaseModel):
    """Event published when a skill invocation completes (success or failure).

    This event is emitted by the skill dispatcher after every invocation,
    regardless of outcome. It provides a join key (``run_id``) to correlate
    with the corresponding skill-started event.

    Attributes:
        event_id: Unique identifier for this completion event.
        run_id: Identifier shared with the skill-started event, used as the
            primary join key for execution tracing.
        skill_name: Human-readable skill name (e.g. ``"local-review"``).
        command_topic: The Kafka topic the inbound command was received on
            (echo of the inbound topic).
        status: Final invocation outcome: success, failed, or partial.
        backend_selected: Which backend executed the skill. One of
            ``"claude_code"`` or ``"local_llm"``.
        backend_detail: Implementation-level detail about the backend selection,
            e.g. ``"claude_subprocess"`` or an LLM endpoint ID such as
            ``"http://192.168.86.201:8001"``.  # onex-allow-internal-ip
        working_directory: Filesystem path the skill ran in, or ``None`` if
            not applicable.
        duration_ms: Wall-clock time from dispatch to completion in milliseconds.
        error_code: Short machine-readable error code if status is ``failed``
            or ``partial`` (e.g. ``"UNKNOWN_SKILL"``, ``"BACKEND_UNAVAILABLE"``,
            ``"TIMEOUT"``). ``None`` on success.
        error_message: Human-readable error description, bounded to 1 000 characters.
            ``None`` on success.
        correlation_id: Correlation ID propagated from the inbound command event.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID = Field(
        ...,
        description="Unique identifier for this completion event",
    )
    run_id: UUID = Field(
        ...,
        description="Join key shared with the skill-started event",
    )
    skill_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable skill name (e.g. 'local-review')",
    )
    command_topic: str = Field(
        ...,
        min_length=1,
        description="Kafka topic the inbound command was received on",
    )
    status: SkillResultStatus = Field(
        ...,
        description="Final invocation outcome",
    )
    backend_selected: str = Field(
        ...,
        min_length=1,
        description="Which backend executed the skill: 'claude_code' or 'local_llm'",
    )
    backend_detail: str = Field(
        ...,
        min_length=1,
        description=(
            "Implementation-level backend detail, e.g. 'claude_subprocess' "
            "or an LLM endpoint ID"
        ),
    )
    working_directory: str | None = Field(
        default=None,
        description="Filesystem path the skill ran in, or None if not applicable",
    )
    duration_ms: int = Field(
        ...,
        ge=0,
        description="Wall-clock execution time in milliseconds",
    )
    error_code: str | None = Field(
        default=None,
        description=(
            "Short machine-readable error code on failure "
            "(e.g. 'UNKNOWN_SKILL', 'BACKEND_UNAVAILABLE', 'TIMEOUT')"
        ),
    )
    error_message: str | None = Field(
        default=None,
        max_length=1000,
        description="Human-readable error description, bounded to 1 000 chars",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID propagated from the inbound command event",
    )


__all__ = ["ModelSkillCompletionEvent"]

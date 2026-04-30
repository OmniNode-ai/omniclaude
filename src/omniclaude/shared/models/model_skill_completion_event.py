# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Skill completion event model — published after every skill invocation.

Emitted on both ``success`` and ``failed`` outcome topics as the authoritative
record of a completed skill run. Carries enough context to join with the
started event (via ``run_id``) and reconstruct a full execution trace.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from omniclaude.shared.models.model_skill_result import SkillResultStatus


class EnumUsageSource(StrEnum):
    """Source quality for token/cost usage attribution."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ModelCostProvenance(BaseModel):
    """Validated provenance for measured, estimated, or unknown usage."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    usage_source: EnumUsageSource = Field(
        description="Whether usage/cost was measured, estimated, or unknown."
    )
    estimation_method: str | None = Field(
        default=None,
        description="Estimator name or method. Required only for estimated usage.",
    )
    source_payload_hash: str | None = Field(
        default=None,
        description="Stable payload hash. Required only for measured usage.",
    )

    @model_validator(mode="after")
    def validate_source_requirements(self) -> ModelCostProvenance:
        if self.usage_source == EnumUsageSource.MEASURED:
            if self.source_payload_hash is None:
                raise ValueError("source_payload_hash is required for measured usage")
            if self.estimation_method is not None:
                raise ValueError("estimation_method must be null for measured usage")
            return self

        if self.usage_source == EnumUsageSource.ESTIMATED:
            if self.estimation_method is None:
                raise ValueError("estimation_method is required for estimated usage")
            if self.source_payload_hash is not None:
                raise ValueError("source_payload_hash must be null for estimated usage")
            return self

        if self.estimation_method is not None:
            raise ValueError("estimation_method must be null for unknown usage")
        if self.source_payload_hash is not None:
            raise ValueError("source_payload_hash must be null for unknown usage")
        return self

    @classmethod
    def rollup(cls, calls: Sequence[ModelCallRecord]) -> ModelCostProvenance:
        """Roll up per-call provenance into dispatch-level cost provenance."""

        cost_bearing_calls = [
            call
            for call in calls
            if call.input_tokens > 0 or call.output_tokens > 0 or call.cost_dollars > 0
        ]
        if not cost_bearing_calls:
            return cls(usage_source=EnumUsageSource.UNKNOWN)

        if any(
            call.cost_provenance.usage_source == EnumUsageSource.ESTIMATED
            for call in cost_bearing_calls
        ):
            return cls(
                usage_source=EnumUsageSource.ESTIMATED,
                estimation_method="model_call_rollup",
            )

        if all(
            call.cost_provenance.usage_source == EnumUsageSource.MEASURED
            for call in cost_bearing_calls
        ):
            hashes = [
                call.cost_provenance.source_payload_hash
                for call in cost_bearing_calls
                if call.cost_provenance.source_payload_hash is not None
            ]
            source_payload_hash = hashlib.sha256(
                "\n".join(sorted(hashes)).encode("utf-8")
            ).hexdigest()
            return cls(
                usage_source=EnumUsageSource.MEASURED,
                source_payload_hash=source_payload_hash,
            )

        return cls(usage_source=EnumUsageSource.UNKNOWN)


class ModelCallRecord(BaseModel):
    """Single model call attribution record for a skill completion event."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    input_tokens: int = Field(default=0, ge=0)  # secret-ok: token usage metric
    output_tokens: int = Field(default=0, ge=0)  # secret-ok: token usage metric
    latency_ms: int = Field(default=0, ge=0)
    cost_dollars: float = Field(default=0.0, ge=0.0)
    cost_provenance: ModelCostProvenance = Field(
        default_factory=lambda: ModelCostProvenance(
            usage_source=EnumUsageSource.UNKNOWN
        ),
    )


class ModelSkillCompletionEvent(BaseModel):
    """Event published when a skill invocation completes (success or failure).

    This event is emitted by the skill dispatcher after every invocation,
    regardless of outcome. It provides a join key (``run_id``) to correlate
    with the corresponding skill-started event.

    Attributes:
        event_id: Unique identifier for this completion event.
        run_id: Identifier shared with the skill-started event, used as the
            primary join key for execution tracing.
        skill_name: Human-readable skill name (e.g. ``"local_review"``).
        command_topic: The Kafka topic the inbound command was received on
            (echo of the inbound topic).
        status: Final invocation outcome: success, failed, or partial.
        backend_selected: Which backend executed the skill. One of
            ``"claude_code"`` or ``"local_llm"``.
        backend_detail: Implementation-level detail about the backend selection,
            e.g. ``"claude_subprocess"`` or an LLM endpoint ID such as
            ``"${LLM_CODER_FAST_URL}"``.  # resolved from environment
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
        description="Human-readable skill name (e.g. 'local_review')",
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
    task_id: str | None = Field(
        default=None,
        min_length=1,
        description="Task identifier associated with a dispatch worker run.",
    )
    dispatch_id: str | None = Field(
        default=None,
        min_length=1,
        description="Dispatch identifier associated with a dispatch worker run.",
    )
    ticket_id: str | None = Field(
        default=None,
        min_length=1,
        description="Ticket identifier associated with a dispatch worker run.",
    )
    artifact_path: str | None = Field(
        default=None,
        min_length=1,
        description="Path to the durable artifact produced by the dispatch run.",
    )
    model_calls: list[ModelCallRecord] = Field(
        default_factory=list,
        description="Model calls attributed to this skill completion.",
    )
    token_cost: int = Field(  # secret-ok: token usage metric
        default=0,
        ge=0,
        description="Total input plus output tokens attributed to the run.",
    )
    dollars_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Total dollar cost attributed to the run.",
    )
    cost_provenance: ModelCostProvenance | None = Field(
        default=None,
        description="Envelope-level cost provenance rollup for model_calls.",
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


__all__ = [
    "EnumUsageSource",
    "ModelCallRecord",
    "ModelCostProvenance",
    "ModelSkillCompletionEvent",
]

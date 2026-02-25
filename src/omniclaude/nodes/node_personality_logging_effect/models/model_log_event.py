# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""LogEvent — canonical structured log event model.

Model ownership: PRIVATE to omniclaude.

LogEvent carries all structured data for a log entry. The personality layer
may render this into human-readable text but MUST NOT mutate any field.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EnumLogSeverity(StrEnum):
    """Log severity levels."""

    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    FATAL = "fatal"


class ModelLogMetrics(BaseModel):
    """Optional metrics snapshot attached to a log event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu: float | None = Field(default=None, description="CPU utilisation 0.0–1.0")
    mem: float | None = Field(default=None, description="Memory utilisation 0.0–1.0")
    queue_depth: int | None = Field(
        default=None, description="Queue depth at emit time"
    )
    latency_p95: float | None = Field(
        default=None, description="p95 latency in milliseconds"
    )


class ModelLogTrace(BaseModel):
    """Distributed-tracing identifiers for a log event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: UUID | None = Field(
        default=None, description="Cross-service correlation ID"
    )
    span_id: str | None = Field(default=None, description="Current span identifier")


class ModelLogPolicy(BaseModel):
    """Privacy and routing policy attached to a log event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    redaction_rules: list[str] = Field(
        default_factory=list,
        description=(
            "List of regex patterns; matching attr keys are redacted "
            "before rendering (privacy_mode: strict)"
        ),
    )
    destination_allowlist: list[str] = Field(
        default_factory=list,
        description=(
            "Sink names permitted to receive this event. "
            "Empty list means all configured sinks are allowed."
        ),
    )


class ModelLogEvent(BaseModel):
    """Canonical structured log event.

    This model is IMMUTABLE — the personality layer renders it into text
    but never modifies any field. Consumers that need a scrubbed copy
    must create a new instance via ``model_copy(update=...)``.

    Attributes:
        severity: Log severity level.
        event_name: Machine-readable event identifier (e.g. ``"db.query.slow"``).
        message: Human-readable description of what happened.
        attrs: Arbitrary structured key/value annotations.
        metrics: Optional performance snapshot.
        trace: Distributed-tracing identifiers.
        policy: Redaction and destination-routing policy.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    severity: EnumLogSeverity = Field(..., description="Severity level")
    event_name: str = Field(..., description="Machine-readable event identifier")
    message: str = Field(..., description="Human-readable event description")
    attrs: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary structured annotations",
    )
    metrics: ModelLogMetrics | None = Field(
        default=None, description="Optional performance metrics snapshot"
    )
    trace: ModelLogTrace = Field(
        default_factory=ModelLogTrace,
        description="Distributed-tracing identifiers",
    )
    policy: ModelLogPolicy = Field(
        default_factory=ModelLogPolicy,
        description="Privacy and routing policy",
    )


__all__ = [
    "EnumLogSeverity",
    "ModelLogEvent",
    "ModelLogMetrics",
    "ModelLogPolicy",
    "ModelLogTrace",
]

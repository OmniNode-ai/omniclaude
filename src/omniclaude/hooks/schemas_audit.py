# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Audit event schemas for context integrity enforcement.

Frozen Pydantic models for the context integrity audit system (OMN-5230).
These events are emitted by audit hooks to track dispatch validation,
scope violations, context budget enforcement, return path control,
and context compression lifecycle.

All models follow the omniclaude event schema conventions:
    - frozen=True (immutable after creation)
    - extra="forbid" (strict field validation)
    - from_attributes=True (ORM compatibility)
    - Explicit timestamp injection (no datetime.now() defaults)

Event Schemas:
    - AuditDispatchValidatedEvent: Dispatch validation pass/fail
    - AuditScopeViolationEvent: Scope boundary violations
    - AuditContextBudgetEvent: Context budget threshold tracking
    - AuditReturnBoundedEvent: Return path size enforcement
    - AuditCompressionEvent: Context compression lifecycle

Related:
    - OMN-5230: Context Integrity Audit & Enforcement
    - OMN-5234: Create audit event schemas in omniclaude
    - schemas.py: Existing hook event schemas (pattern reference)
    - topics.py: TopicBase enum (audit topics registered there)
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.schemas import TimezoneAwareDatetime

# =============================================================================
# Audit Event Enums
# =============================================================================


class AuditScopeViolationType(StrEnum):
    """Types of scope violations detected by context integrity audit.

    Values:
        MEMORY: Handler accessed memory namespaces outside declared scope.
        TOOL: Handler invoked tools outside declared tool scope.
        CONTEXT: Handler consumed context outside declared retrieval sources.
        RETURN: Handler returned payload exceeding declared return schema.
    """

    MEMORY = "memory"
    TOOL = "tool"
    CONTEXT = "context"
    RETURN = "return"


class AuditCompressionTrigger(StrEnum):
    """Triggers that initiate context compression.

    Values:
        TOKEN_THRESHOLD: Compression triggered by exceeding token budget threshold.
        TIME_LIMIT: Compression triggered by exceeding time limit.
    """

    TOKEN_THRESHOLD = "token_threshold"  # noqa: S105
    TIME_LIMIT = "time_limit"


class AuditEnforcementAction(StrEnum):
    """Actions taken by the enforcement system on violation detection.

    Values:
        LOG: Violation logged only (permissive mode).
        WARN: Violation logged and alert event emitted (warn mode).
        BLOCK: Violating operation blocked (strict mode).
        ROLLBACK: Operation blocked and rolled back (paranoid mode).
    """

    LOG = "log"
    WARN = "warn"
    BLOCK = "block"
    ROLLBACK = "rollback"


# =============================================================================
# Audit Event Models
# =============================================================================


class AuditDispatchValidatedEvent(BaseModel):
    """Event emitted when a task dispatch is validated against its contract.

    Records whether the dispatched task's declared constraints (agent type,
    enforcement level) passed validation. Emitted by the dispatch validation
    hook before a sub-agent begins execution.

    Attributes:
        task_id: Unique identifier for the dispatched task.
        contract_id: Contract identifier being validated against.
        parent_task_id: Parent task that dispatched this task (None for root).
        agent_type: Type of agent being dispatched.
        enforcement_level: Enforcement level declared in the contract.
        passed: Whether validation passed.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when this event was emitted (UTC).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    task_id: UUID = Field(
        ...,
        description="Unique identifier for the dispatched task",
    )
    contract_id: str = Field(
        ...,
        min_length=1,
        description="Contract identifier being validated against",
    )
    parent_task_id: UUID | None = Field(
        default=None,
        description="Parent task that dispatched this task (None for root)",
    )
    agent_type: str = Field(
        ...,
        min_length=1,
        description="Type of agent being dispatched",
    )
    enforcement_level: str = Field(
        ...,
        min_length=1,
        description="Enforcement level: PERMISSIVE, WARN, STRICT, or PARANOID",
    )
    passed: bool = Field(
        ...,
        description="Whether dispatch validation passed",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when this event was emitted (UTC)",
    )


class AuditScopeViolationEvent(BaseModel):
    """Event emitted when a scope violation is detected during task execution.

    Records the type of violation, what was declared versus what was accessed,
    and the enforcement action taken. Emitted by PreToolUse and PostToolUse
    audit hooks when a task exceeds its declared scope.

    Attributes:
        task_id: Unique identifier for the violating task.
        violation_type: Category of scope violation.
        declared_scope: Scope declared in the contract.
        actual_access: What was actually accessed.
        enforcement_action: Action taken by the enforcement system.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when this event was emitted (UTC).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    task_id: UUID = Field(
        ...,
        description="Unique identifier for the violating task",
    )
    violation_type: AuditScopeViolationType = Field(
        ...,
        description="Category of scope violation (memory, tool, context, return)",
    )
    declared_scope: list[str] = Field(
        ...,
        description="Scope entries declared in the contract",
    )
    actual_access: str = Field(
        ...,
        min_length=1,
        description="What was actually accessed outside the declared scope",
    )
    enforcement_action: AuditEnforcementAction = Field(
        ...,
        description="Action taken by the enforcement system",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when this event was emitted (UTC)",
    )


class AuditContextBudgetEvent(BaseModel):
    """Event emitted to track context budget usage for a task.

    Records the declared budget, actual token usage, and whether the budget
    was exceeded. Emitted periodically during task execution and at task
    completion to track context window consumption.

    Attributes:
        task_id: Unique identifier for the task being tracked.
        budget_tokens: Token budget declared in the contract.
        actual_tokens: Actual tokens consumed so far.
        exceeded: Whether the budget has been exceeded.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when this event was emitted (UTC).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    task_id: UUID = Field(
        ...,
        description="Unique identifier for the task being tracked",
    )
    budget_tokens: int = Field(
        ...,
        ge=1,
        description="Token budget declared in the contract",
    )
    actual_tokens: int = Field(
        ...,
        ge=0,
        description="Actual tokens consumed so far",
    )
    exceeded: bool = Field(
        ...,
        description="Whether the budget has been exceeded",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when this event was emitted (UTC)",
    )


class AuditReturnBoundedEvent(BaseModel):
    """Event emitted when return path size is evaluated against constraints.

    Records the return payload size, declared maximum, fields returned,
    and whether the return was blocked. Emitted by PostToolUse audit hooks
    when a task completes and returns data.

    Attributes:
        task_id: Unique identifier for the returning task.
        return_tokens: Estimated token count of the return payload.
        max_tokens: Maximum return tokens declared in the contract.
        fields_returned: List of field names in the return payload.
        blocked: Whether the return was blocked due to exceeding limits.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when this event was emitted (UTC).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    task_id: UUID = Field(
        ...,
        description="Unique identifier for the returning task",
    )
    return_tokens: int = Field(
        ...,
        ge=0,
        description="Estimated token count of the return payload",
    )
    max_tokens: int = Field(
        ...,
        ge=1,
        description="Maximum return tokens declared in the contract",
    )
    fields_returned: list[str] = Field(
        ...,
        description="List of field names in the return payload",
    )
    blocked: bool = Field(
        ...,
        description="Whether the return was blocked due to exceeding limits",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when this event was emitted (UTC)",
    )


class AuditCompressionEvent(BaseModel):
    """Event emitted when context compression is triggered.

    Records what triggered the compression, token counts before and after,
    and the compression ratio achieved. Emitted by the compression lifecycle
    handler when context window management compresses task context.

    Attributes:
        task_id: Unique identifier for the task whose context was compressed.
        trigger: What triggered the compression.
        before_tokens: Token count before compression.
        after_tokens: Token count after compression.
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp when this event was emitted (UTC).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        from_attributes=True,
    )

    task_id: UUID = Field(
        ...,
        description="Unique identifier for the task whose context was compressed",
    )
    trigger: AuditCompressionTrigger = Field(
        ...,
        description="What triggered the compression (token_threshold or time_limit)",
    )
    before_tokens: int = Field(
        ...,
        ge=0,
        description="Token count before compression",
    )
    after_tokens: int = Field(
        ...,
        ge=0,
        description="Token count after compression",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID for distributed tracing",
    )
    emitted_at: TimezoneAwareDatetime = Field(
        ...,
        description="Timestamp when this event was emitted (UTC)",
    )


__all__ = [
    # Enums
    "AuditCompressionTrigger",
    "AuditEnforcementAction",
    "AuditScopeViolationType",
    # Event models
    "AuditCompressionEvent",
    "AuditContextBudgetEvent",
    "AuditDispatchValidatedEvent",
    "AuditReturnBoundedEvent",
    "AuditScopeViolationEvent",
]

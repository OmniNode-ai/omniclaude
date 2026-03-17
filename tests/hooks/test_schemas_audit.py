# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for audit event schemas (OMN-5230).

Validates all five audit event models follow ONEX conventions:
    - frozen=True (immutable after creation)
    - extra="forbid" (strict field validation)
    - from_attributes=True (ORM compatibility)
    - Explicit timestamp injection (no datetime.now() defaults)
    - Required fields are enforced
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.hooks.schemas_audit import (
    AuditCompressionEvent,
    AuditCompressionTrigger,
    AuditContextBudgetEvent,
    AuditDispatchValidatedEvent,
    AuditEnforcementAction,
    AuditReturnBoundedEvent,
    AuditScopeViolationEvent,
    AuditScopeViolationType,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Helper Factories
# =============================================================================


def _ts() -> datetime:
    """Create a valid timezone-aware timestamp."""
    return datetime.now(UTC)


def _id():  # noqa: ANN202
    return uuid4()


# =============================================================================
# AuditDispatchValidatedEvent
# =============================================================================


class TestAuditDispatchValidatedEvent:
    """Tests for AuditDispatchValidatedEvent."""

    def test_create_passing(self) -> None:
        evt = AuditDispatchValidatedEvent(
            task_id=_id(),
            contract_id="node_poly_enforcer_effect",
            parent_task_id=_id(),
            agent_type="onex:polymorphic-agent",
            enforcement_level="STRICT",
            passed=True,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.passed is True
        assert evt.enforcement_level == "STRICT"

    def test_create_failing(self) -> None:
        evt = AuditDispatchValidatedEvent(
            task_id=_id(),
            contract_id="node_poly_enforcer_effect",
            parent_task_id=None,
            agent_type="onex:polymorphic-agent",
            enforcement_level="WARN",
            passed=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.passed is False
        assert evt.parent_task_id is None

    def test_frozen(self) -> None:
        evt = AuditDispatchValidatedEvent(
            task_id=_id(),
            contract_id="contract-1",
            agent_type="agent-1",
            enforcement_level="PERMISSIVE",
            passed=True,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        with pytest.raises(ValidationError):
            evt.passed = False  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError, match="extra"):
            AuditDispatchValidatedEvent(
                task_id=_id(),
                contract_id="contract-1",
                agent_type="agent-1",
                enforcement_level="STRICT",
                passed=True,
                correlation_id=_id(),
                emitted_at=_ts(),
                unexpected_field="bad",  # type: ignore[call-arg]
            )

    def test_missing_required_field(self) -> None:
        with pytest.raises(ValidationError):
            AuditDispatchValidatedEvent(
                task_id=_id(),
                # contract_id missing
                agent_type="agent-1",
                enforcement_level="STRICT",
                passed=True,
                correlation_id=_id(),
                emitted_at=_ts(),
            )  # type: ignore[call-arg]


# =============================================================================
# AuditScopeViolationEvent
# =============================================================================


class TestAuditScopeViolationEvent:
    """Tests for AuditScopeViolationEvent."""

    def test_memory_violation(self) -> None:
        evt = AuditScopeViolationEvent(
            task_id=_id(),
            violation_type=AuditScopeViolationType.MEMORY,
            declared_scope=["namespace-a", "namespace-b"],
            actual_access="namespace-c",
            enforcement_action=AuditEnforcementAction.BLOCK,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.violation_type == AuditScopeViolationType.MEMORY
        assert evt.enforcement_action == AuditEnforcementAction.BLOCK

    def test_tool_violation(self) -> None:
        evt = AuditScopeViolationEvent(
            task_id=_id(),
            violation_type=AuditScopeViolationType.TOOL,
            declared_scope=["Read", "Glob"],
            actual_access="Bash",
            enforcement_action=AuditEnforcementAction.WARN,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.violation_type == AuditScopeViolationType.TOOL

    def test_all_violation_types(self) -> None:
        for vt in AuditScopeViolationType:
            evt = AuditScopeViolationEvent(
                task_id=_id(),
                violation_type=vt,
                declared_scope=["scope-a"],
                actual_access="scope-x",
                enforcement_action=AuditEnforcementAction.LOG,
                correlation_id=_id(),
                emitted_at=_ts(),
            )
            assert evt.violation_type == vt

    def test_all_enforcement_actions(self) -> None:
        for action in AuditEnforcementAction:
            evt = AuditScopeViolationEvent(
                task_id=_id(),
                violation_type=AuditScopeViolationType.CONTEXT,
                declared_scope=[],
                actual_access="unexpected",
                enforcement_action=action,
                correlation_id=_id(),
                emitted_at=_ts(),
            )
            assert evt.enforcement_action == action

    def test_frozen(self) -> None:
        evt = AuditScopeViolationEvent(
            task_id=_id(),
            violation_type=AuditScopeViolationType.RETURN,
            declared_scope=["a"],
            actual_access="b",
            enforcement_action=AuditEnforcementAction.ROLLBACK,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        with pytest.raises(ValidationError):
            evt.actual_access = "c"  # type: ignore[misc]


# =============================================================================
# AuditContextBudgetEvent
# =============================================================================


class TestAuditContextBudgetEvent:
    """Tests for AuditContextBudgetEvent."""

    def test_within_budget(self) -> None:
        evt = AuditContextBudgetEvent(
            task_id=_id(),
            budget_tokens=10000,
            actual_tokens=8500,
            exceeded=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.exceeded is False
        assert evt.actual_tokens < evt.budget_tokens

    def test_exceeded_budget(self) -> None:
        evt = AuditContextBudgetEvent(
            task_id=_id(),
            budget_tokens=10000,
            actual_tokens=12000,
            exceeded=True,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.exceeded is True

    def test_budget_tokens_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            AuditContextBudgetEvent(
                task_id=_id(),
                budget_tokens=0,
                actual_tokens=100,
                exceeded=False,
                correlation_id=_id(),
                emitted_at=_ts(),
            )

    def test_actual_tokens_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            AuditContextBudgetEvent(
                task_id=_id(),
                budget_tokens=1000,
                actual_tokens=-1,
                exceeded=False,
                correlation_id=_id(),
                emitted_at=_ts(),
            )

    def test_frozen(self) -> None:
        evt = AuditContextBudgetEvent(
            task_id=_id(),
            budget_tokens=5000,
            actual_tokens=3000,
            exceeded=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        with pytest.raises(ValidationError):
            evt.exceeded = True  # type: ignore[misc]


# =============================================================================
# AuditReturnBoundedEvent
# =============================================================================


class TestAuditReturnBoundedEvent:
    """Tests for AuditReturnBoundedEvent."""

    def test_within_bounds(self) -> None:
        evt = AuditReturnBoundedEvent(
            task_id=_id(),
            return_tokens=500,
            max_tokens=1000,
            fields_returned=["status", "result"],
            blocked=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.blocked is False
        assert len(evt.fields_returned) == 2

    def test_blocked_return(self) -> None:
        evt = AuditReturnBoundedEvent(
            task_id=_id(),
            return_tokens=2000,
            max_tokens=1000,
            fields_returned=["status", "result", "debug_trace", "full_context"],
            blocked=True,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.blocked is True

    def test_max_tokens_must_be_positive(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 1"):
            AuditReturnBoundedEvent(
                task_id=_id(),
                return_tokens=0,
                max_tokens=0,
                fields_returned=[],
                blocked=False,
                correlation_id=_id(),
                emitted_at=_ts(),
            )

    def test_frozen(self) -> None:
        evt = AuditReturnBoundedEvent(
            task_id=_id(),
            return_tokens=100,
            max_tokens=500,
            fields_returned=["a"],
            blocked=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        with pytest.raises(ValidationError):
            evt.blocked = True  # type: ignore[misc]


# =============================================================================
# AuditCompressionEvent
# =============================================================================


class TestAuditCompressionEvent:
    """Tests for AuditCompressionEvent."""

    def test_token_threshold_trigger(self) -> None:
        evt = AuditCompressionEvent(
            task_id=_id(),
            trigger=AuditCompressionTrigger.TOKEN_THRESHOLD,
            before_tokens=50000,
            after_tokens=25000,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.trigger == AuditCompressionTrigger.TOKEN_THRESHOLD
        assert evt.before_tokens > evt.after_tokens

    def test_time_limit_trigger(self) -> None:
        evt = AuditCompressionEvent(
            task_id=_id(),
            trigger=AuditCompressionTrigger.TIME_LIMIT,
            before_tokens=30000,
            after_tokens=15000,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        assert evt.trigger == AuditCompressionTrigger.TIME_LIMIT

    def test_tokens_cannot_be_negative(self) -> None:
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            AuditCompressionEvent(
                task_id=_id(),
                trigger=AuditCompressionTrigger.TOKEN_THRESHOLD,
                before_tokens=-1,
                after_tokens=0,
                correlation_id=_id(),
                emitted_at=_ts(),
            )

    def test_frozen(self) -> None:
        evt = AuditCompressionEvent(
            task_id=_id(),
            trigger=AuditCompressionTrigger.TOKEN_THRESHOLD,
            before_tokens=10000,
            after_tokens=5000,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        with pytest.raises(ValidationError):
            evt.before_tokens = 0  # type: ignore[misc]


# =============================================================================
# JSON round-trip tests
# =============================================================================


class TestJsonRoundTrip:
    """Verify all audit event models serialize and deserialize correctly."""

    def test_dispatch_validated_roundtrip(self) -> None:
        evt = AuditDispatchValidatedEvent(
            task_id=_id(),
            contract_id="contract-abc",
            parent_task_id=_id(),
            agent_type="onex:polymorphic-agent",
            enforcement_level="PARANOID",
            passed=True,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        restored = AuditDispatchValidatedEvent.model_validate_json(
            evt.model_dump_json()
        )
        assert restored == evt

    def test_scope_violation_roundtrip(self) -> None:
        evt = AuditScopeViolationEvent(
            task_id=_id(),
            violation_type=AuditScopeViolationType.TOOL,
            declared_scope=["Read", "Glob"],
            actual_access="Bash",
            enforcement_action=AuditEnforcementAction.BLOCK,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        restored = AuditScopeViolationEvent.model_validate_json(evt.model_dump_json())
        assert restored == evt

    def test_context_budget_roundtrip(self) -> None:
        evt = AuditContextBudgetEvent(
            task_id=_id(),
            budget_tokens=10000,
            actual_tokens=8000,
            exceeded=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        restored = AuditContextBudgetEvent.model_validate_json(evt.model_dump_json())
        assert restored == evt

    def test_return_bounded_roundtrip(self) -> None:
        evt = AuditReturnBoundedEvent(
            task_id=_id(),
            return_tokens=500,
            max_tokens=1000,
            fields_returned=["status"],
            blocked=False,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        restored = AuditReturnBoundedEvent.model_validate_json(evt.model_dump_json())
        assert restored == evt

    def test_compression_roundtrip(self) -> None:
        evt = AuditCompressionEvent(
            task_id=_id(),
            trigger=AuditCompressionTrigger.TIME_LIMIT,
            before_tokens=40000,
            after_tokens=20000,
            correlation_id=_id(),
            emitted_at=_ts(),
        )
        restored = AuditCompressionEvent.model_validate_json(evt.model_dump_json())
        assert restored == evt


# =============================================================================
# Enum coverage
# =============================================================================


class TestEnums:
    """Verify enum values are correct."""

    def test_scope_violation_type_values(self) -> None:
        assert AuditScopeViolationType.MEMORY == "memory"
        assert AuditScopeViolationType.TOOL == "tool"
        assert AuditScopeViolationType.CONTEXT == "context"
        assert AuditScopeViolationType.RETURN == "return"
        assert len(AuditScopeViolationType) == 4

    def test_compression_trigger_values(self) -> None:
        assert AuditCompressionTrigger.TOKEN_THRESHOLD == "token_threshold"
        assert AuditCompressionTrigger.TIME_LIMIT == "time_limit"
        assert len(AuditCompressionTrigger) == 2

    def test_enforcement_action_values(self) -> None:
        assert AuditEnforcementAction.LOG == "log"
        assert AuditEnforcementAction.WARN == "warn"
        assert AuditEnforcementAction.BLOCK == "block"
        assert AuditEnforcementAction.ROLLBACK == "rollback"
        assert len(AuditEnforcementAction) == 4

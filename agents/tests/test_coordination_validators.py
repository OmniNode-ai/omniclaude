#!/usr/bin/env python3
"""
Test suite for Coordination Validation Quality Gates.

Comprehensive tests for CV-001, CV-002, CV-003 validators with mock delegation
scenarios and multi-agent test cases.

ONEX v2.0 Compliance:
- Async test patterns
- Mock coordination data (no actual multi-agent execution)
- Comprehensive validation scenarios
- Performance verification
"""

import pytest

from agents.lib.models.model_quality_gate import EnumQualityGate
from agents.lib.validators.coordination_validators import (
    AgentCoordinationValidator,
    ContextInheritanceValidator,
    DelegationValidationValidator,
)


class TestContextInheritanceValidator:
    """Test suite for CV-001: Context Inheritance Validator."""

    @pytest.fixture
    def validator(self) -> ContextInheritanceValidator:
        """Create validator instance."""
        return ContextInheritanceValidator()

    @pytest.fixture
    def successful_context_inheritance(self) -> dict:
        """Mock successful context inheritance data."""
        return {
            "parent_context": {
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                "task_id": "task_001",
                "agent_name": "agent_workflow_coordinator",
                "context_version": "1.0",
                "project_id": "project_123",
                "user_request": "Generate ONEX node",
            },
            "delegated_context": {
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                "task_id": "task_001",
                "agent_name": "agent_onex_generator",
                "context_version": "1.0",
                "project_id": "project_123",
                "user_request": "Generate ONEX node",
                "inheritance_chain": ["agent_workflow_coordinator"],
            },
            "critical_fields": ["correlation_id", "task_id", "agent_name"],
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(
        self, validator: ContextInheritanceValidator
    ):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.CONTEXT_INHERITANCE
        assert validator.gate.category == "coordination_validation"
        assert validator.gate.performance_target_ms == 40

    @pytest.mark.asyncio
    async def test_successful_context_inheritance(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test validation passes with successful context inheritance."""
        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "6/6 fields preserved" in result.message
        assert result.metadata["preservation_ratio"] == 1.0
        assert result.metadata["correlation_id_preserved"] is True
        assert result.metadata["version_compatible"] is True
        assert result.metadata["chain_valid"] is True

    @pytest.mark.asyncio
    async def test_no_parent_context(self, validator: ContextInheritanceValidator):
        """Test validation fails when no parent context exists."""
        context = {
            "context_inheritance": {
                "parent_context": {},
                "delegated_context": {"some": "data"},
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No parent context" in result.message
        assert result.metadata["reason"] == "no_parent_context"

    @pytest.mark.asyncio
    async def test_no_delegated_context(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test validation fails when no context passed to delegated agent."""
        successful_context_inheritance["delegated_context"] = {}

        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No context was passed" in result.message
        assert result.metadata["reason"] == "no_delegated_context"

    @pytest.mark.asyncio
    async def test_critical_fields_lost(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test validation fails when critical fields are lost."""
        # Remove critical field from delegated context
        del successful_context_inheritance["delegated_context"]["task_id"]

        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Critical context fields lost" in result.message
        assert "task_id" in result.metadata["missing_fields"]
        assert result.metadata["reason"] == "critical_fields_lost"

    @pytest.mark.asyncio
    async def test_correlation_id_mismatch(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test validation fails when correlation ID doesn't match."""
        successful_context_inheritance["delegated_context"][
            "correlation_id"
        ] = "different-correlation-id"

        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Correlation ID not preserved" in result.message
        assert result.metadata["reason"] == "correlation_id_mismatch"

    @pytest.mark.asyncio
    async def test_partial_field_preservation(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test validation with partial field preservation."""
        # Remove non-critical field
        del successful_context_inheritance["delegated_context"]["user_request"]

        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        # Should pass - user_request is not critical
        assert result.status == "passed"
        assert result.metadata["preservation_ratio"] == pytest.approx(0.833, rel=0.01)
        assert result.metadata["preserved_fields_count"] == 5
        assert result.metadata["total_parent_fields"] == 6

    @pytest.mark.asyncio
    async def test_context_version_compatibility(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test context version compatibility check."""
        successful_context_inheritance["delegated_context"]["context_version"] = "2.0"

        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        # Should still pass but version_compatible will be False
        assert result.status == "passed"
        assert result.metadata["version_compatible"] is False

    @pytest.mark.asyncio
    async def test_inheritance_chain_validation(
        self,
        validator: ContextInheritanceValidator,
        successful_context_inheritance: dict,
    ):
        """Test inheritance chain validation."""
        context = {"context_inheritance": successful_context_inheritance}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["chain_valid"] is True
        assert result.metadata["inheritance_chain_length"] == 1
        assert result.metadata["parent_agent"] == "agent_workflow_coordinator"


class TestAgentCoordinationValidator:
    """Test suite for CV-002: Agent Coordination Validator."""

    @pytest.fixture
    def validator(self) -> AgentCoordinationValidator:
        """Create validator instance."""
        return AgentCoordinationValidator()

    @pytest.fixture
    def successful_agent_coordination(self) -> dict:
        """Mock successful agent coordination data."""
        return {
            "protocol": "parallel",
            "communications": [
                {
                    "from": "agent_coordinator",
                    "to": "agent_worker_1",
                    "message_type": "task_assignment",
                    "success": True,
                },
                {
                    "from": "agent_worker_1",
                    "to": "agent_coordinator",
                    "message_type": "task_result",
                    "success": True,
                },
                {
                    "from": "agent_coordinator",
                    "to": "agent_worker_2",
                    "message_type": "task_assignment",
                    "success": True,
                },
                {
                    "from": "agent_worker_2",
                    "to": "agent_coordinator",
                    "message_type": "task_result",
                    "success": True,
                },
            ],
            "collaboration_metrics": {
                "deadlock_detected": False,
                "resource_conflicts": 2,  # Some conflicts but resolved
            },
            "active_agents": [
                "agent_coordinator",
                "agent_worker_1",
                "agent_worker_2",
            ],
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(
        self, validator: AgentCoordinationValidator
    ):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.AGENT_COORDINATION
        assert validator.gate.category == "coordination_validation"
        assert validator.gate.performance_target_ms == 60

    @pytest.mark.asyncio
    async def test_successful_agent_coordination(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation passes with successful agent coordination."""
        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "3 agents" in result.message
        assert "4/4 comms successful" in result.message
        assert result.metadata["agent_count"] == 3
        assert result.metadata["total_communications"] == 4
        assert result.metadata["comm_success_rate"] == 1.0
        assert not result.metadata["protocol_warning"]
        assert not result.metadata["deadlock_detected"]

    @pytest.mark.asyncio
    async def test_no_protocol_specified(self, validator: AgentCoordinationValidator):
        """Test validation fails when no protocol specified."""
        context = {
            "agent_coordination": {
                "communications": [],
                "collaboration_metrics": {},
                "active_agents": [],
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No coordination protocol" in result.message
        assert result.metadata["reason"] == "no_protocol"

    @pytest.mark.asyncio
    async def test_custom_protocol_warning(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test custom protocol triggers warning but not failure."""
        successful_agent_coordination["protocol"] = "custom_protocol"

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        # Should pass but with warning
        assert result.status == "passed"
        assert result.metadata["protocol_warning"] is True

    @pytest.mark.asyncio
    async def test_communication_failures(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation fails when communications fail."""
        # Mark some communications as failed
        successful_agent_coordination["communications"][1]["success"] = False
        successful_agent_coordination["communications"][3]["success"] = False

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "communication failures" in result.message
        assert result.metadata["failed_count"] == 2
        assert result.metadata["total_communications"] == 4
        assert 1 in result.metadata["failed_indices"]
        assert 3 in result.metadata["failed_indices"]

    @pytest.mark.asyncio
    async def test_deadlock_detected(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation fails when deadlock is detected."""
        successful_agent_coordination["collaboration_metrics"][
            "deadlock_detected"
        ] = True
        successful_agent_coordination["collaboration_metrics"]["deadlock_info"] = {
            "agents": ["agent_1", "agent_2"],
            "reason": "Circular wait on resources",
        }

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "deadlock detected" in result.message
        assert result.metadata["reason"] == "deadlock_detected"

    @pytest.mark.asyncio
    async def test_resource_conflicts_acceptable(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation passes with acceptable resource conflicts."""
        successful_agent_coordination["collaboration_metrics"]["resource_conflicts"] = 3

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        # Should pass - 3 conflicts is below default max of 5
        assert result.status == "passed"
        assert result.metadata["resource_conflicts"] == 3

    @pytest.mark.asyncio
    async def test_too_many_resource_conflicts(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation fails with too many resource conflicts."""
        successful_agent_coordination["collaboration_metrics"][
            "resource_conflicts"
        ] = 10

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Too many resource conflicts" in result.message
        assert result.metadata["conflict_count"] == 10
        assert result.metadata["max_allowed"] == 5

    @pytest.mark.asyncio
    async def test_no_communications_warning(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test validation with no communications (warning)."""
        successful_agent_coordination["communications"] = []

        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        # Should pass but with warning
        assert result.status == "passed"
        assert result.metadata["comm_warning"] is True

    @pytest.mark.asyncio
    async def test_communication_success_rate(
        self, validator: AgentCoordinationValidator, successful_agent_coordination: dict
    ):
        """Test communication success rate calculation."""
        context = {"agent_coordination": successful_agent_coordination}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["comm_success_rate"] == 1.0
        assert result.metadata["successful_communications"] == 4


class TestDelegationValidationValidator:
    """Test suite for CV-003: Delegation Validation Validator."""

    @pytest.fixture
    def validator(self) -> DelegationValidationValidator:
        """Create validator instance."""
        return DelegationValidationValidator()

    @pytest.fixture
    def successful_delegation(self) -> dict:
        """Mock successful delegation data."""
        return {
            "handoff_success": True,
            "task_completed": True,
            "results_returned": True,
            "delegation_chain": [
                "agent_coordinator",
                "agent_worker",
                "agent_specialist",
            ],
            "parent_task_id": "task_001",
            "delegated_agent": "agent_specialist",
            "delegation_time_ms": 1500,
            "task_status": "completed",
            "result_quality": {
                "has_error": False,
                "error_handled": True,
            },
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(
        self, validator: DelegationValidationValidator
    ):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.DELEGATION_VALIDATION
        assert validator.gate.category == "coordination_validation"
        assert validator.gate.performance_target_ms == 45

    @pytest.mark.asyncio
    async def test_successful_delegation(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation passes with successful delegation."""
        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "agent_specialist" in result.message
        assert "1500ms" in result.message
        assert result.metadata["handoff_success"] is True
        assert result.metadata["task_completed"] is True
        assert result.metadata["results_returned"] is True
        assert result.metadata["delegation_depth"] == 3
        assert not result.metadata["chain_warning"]
        assert not result.metadata["depth_warning"]

    @pytest.mark.asyncio
    async def test_handoff_failure(self, validator: DelegationValidationValidator):
        """Test validation fails when handoff fails."""
        context = {
            "delegation_validation": {
                "handoff_success": False,
                "handoff_error": "Agent not available",
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "handoff was not successful" in result.message
        assert result.metadata["reason"] == "handoff_failed"
        assert "Agent not available" in result.metadata["handoff_error"]

    @pytest.mark.asyncio
    async def test_task_not_completed(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation fails when delegated task not completed."""
        successful_delegation["task_completed"] = False
        successful_delegation["task_status"] = "failed"
        successful_delegation["task_error"] = "Validation error"

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "did not complete" in result.message
        assert result.metadata["reason"] == "task_not_completed"
        assert result.metadata["task_status"] == "failed"

    @pytest.mark.asyncio
    async def test_results_not_returned(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation fails when results not returned."""
        successful_delegation["results_returned"] = False

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "not returned to caller" in result.message
        assert result.metadata["reason"] == "results_not_returned"

    @pytest.mark.asyncio
    async def test_no_delegation_chain_warning(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation with no delegation chain (warning)."""
        successful_delegation["delegation_chain"] = []

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        # Should pass but with warning
        assert result.status == "passed"
        assert result.metadata["chain_warning"] is True

    @pytest.mark.asyncio
    async def test_excessive_delegation_depth(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation warns with excessive delegation depth."""
        # Create deep delegation chain
        successful_delegation["delegation_chain"] = [f"agent_{i}" for i in range(15)]

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        # Should pass but with depth warning
        assert result.status == "passed"
        assert result.metadata["depth_warning"] is True
        assert result.metadata["delegation_depth"] == 15

    @pytest.mark.asyncio
    async def test_unhandled_error(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation fails when error is not handled."""
        successful_delegation["result_quality"]["has_error"] = True
        successful_delegation["result_quality"]["error_handled"] = False
        successful_delegation["result_quality"]["error"] = "Unexpected exception"

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "error was not properly handled" in result.message
        assert result.metadata["reason"] == "unhandled_error"

    @pytest.mark.asyncio
    async def test_handled_error(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test validation passes when error is properly handled."""
        successful_delegation["result_quality"]["has_error"] = True
        successful_delegation["result_quality"]["error_handled"] = True

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        # Should pass - error was handled
        assert result.status == "passed"
        assert result.metadata["has_error"] is True
        assert result.metadata["error_handled"] is True

    @pytest.mark.asyncio
    async def test_parent_task_tracking(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test parent task ID tracking."""
        # Update delegation chain to include parent task ID for realistic tracking
        successful_delegation["delegation_chain"] = [
            "task_001:agent_coordinator",
            "task_002:agent_worker",
            "task_003:agent_specialist",
        ]

        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["parent_in_chain"] is True

    @pytest.mark.asyncio
    async def test_delegation_metrics(
        self, validator: DelegationValidationValidator, successful_delegation: dict
    ):
        """Test delegation metrics are captured."""
        context = {"delegation_validation": successful_delegation}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["delegation_time_ms"] == 1500
        assert result.metadata["delegated_agent"] == "agent_specialist"

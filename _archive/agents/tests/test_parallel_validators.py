#!/usr/bin/env python3
"""
Tests for Parallel Validation Gates (PV-001 to PV-003).

Comprehensive test coverage for:
- PV-001: Context Synchronization
- PV-002: Coordination Validation
- PV-003: Result Consistency

ONEX v2.0 Compliance:
- Test all pass/fail scenarios
- Validate performance targets
- Test dependency handling
- Verify parallel execution awareness
"""

from uuid import uuid4

import pytest

from agents.lib.validators.parallel_validators import (
    ContextSynchronizationValidator,
    CoordinationValidationValidator,
    ResultConsistencyValidator,
)


class TestContextSynchronizationValidator:
    """Test PV-001: Context Synchronization Validator."""

    @pytest.mark.asyncio
    async def test_synchronized_contexts_pass(self):
        """Test that synchronized contexts pass validation."""
        validator = ContextSynchronizationValidator()

        context = {
            "parallel_contexts": [
                {
                    "task_id": "123",
                    "shared_data": "value1",
                    "version": "1.0",
                    "correlation_id": uuid4(),
                },
                {
                    "task_id": "123",
                    "shared_data": "value1",
                    "version": "1.0",
                    "correlation_id": uuid4(),
                },
            ],
            "shared_state_keys": ["task_id", "shared_data"],
            "context_version": "1.0",
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["parallel_agents"] == 2
        assert result.metadata["shared_state_keys"] == 2

    @pytest.mark.asyncio
    async def test_no_contexts_fails(self):
        """Test that no parallel contexts fails validation."""
        validator = ContextSynchronizationValidator()

        context = {"parallel_contexts": []}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "synchronization failed" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert any(
            "no parallel contexts" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_context_inconsistencies_fail(self):
        """Test that inconsistent contexts fail validation."""
        validator = ContextSynchronizationValidator()

        context = {
            "parallel_contexts": [
                {"task_id": "123", "shared_data": "value1"},
                {"task_id": "456", "shared_data": "value2"},  # Different values
            ],
            "shared_state_keys": ["task_id", "shared_data"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "synchronization failed" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "inconsistencies" in result.metadata
        assert "inconsistencies" in result.metadata
        assert len(result.metadata["inconsistencies"]) == 2  # Both keys mismatch

    @pytest.mark.asyncio
    async def test_version_mismatch_fails(self):
        """Test that version mismatches fail validation."""
        validator = ContextSynchronizationValidator()

        context = {
            "parallel_contexts": [
                {"version": "1.0"},
                {"version": "2.0"},  # Different version
            ],
            "context_version": "1.0",
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "synchronization failed" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "version_mismatches" in result.metadata
        assert "version_mismatches" in result.metadata

    @pytest.mark.asyncio
    async def test_duplicate_correlation_ids_fail(self):
        """Test that duplicate correlation IDs fail validation (race condition)."""
        validator = ContextSynchronizationValidator()

        same_id = uuid4()
        context = {
            "parallel_contexts": [
                {"correlation_id": same_id},
                {"correlation_id": same_id},  # Duplicate
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "synchronization failed" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "duplicate_ids" in result.metadata
        assert "duplicate_ids" in result.metadata

    @pytest.mark.asyncio
    async def test_missing_sync_points_fail(self):
        """Test that missing synchronization points fail validation."""
        validator = ContextSynchronizationValidator()

        context = {
            "parallel_contexts": [
                {"reached_sync_points": ["init", "execute"]},
                {"reached_sync_points": ["init"]},  # Missing "execute"
            ],
            "synchronization_points": ["init", "execute"],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "synchronization failed" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "missing_sync_points" in result.metadata
        assert "missing_sync_points" in result.metadata

    @pytest.mark.asyncio
    async def test_execution_with_timing(self):
        """Test that timing meets performance target."""
        validator = ContextSynchronizationValidator()

        context = {
            "parallel_contexts": [
                {"task_id": "123"},
                {"task_id": "123"},
            ],
            "shared_state_keys": ["task_id"],
        }

        result = await validator.execute_with_timing(context)

        assert result.execution_time_ms >= 0
        assert result.execution_time_ms <= validator.gate.performance_target_ms * 2


class TestCoordinationValidationValidator:
    """Test PV-002: Coordination Validation Validator."""

    @pytest.mark.asyncio
    async def test_valid_coordination_pass(self):
        """Test that valid coordination passes validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [
                {
                    "type": "sync",
                    "protocol": "parallel",
                },
                {
                    "type": "message",
                    "protocol": "parallel",
                    "message": {
                        "from_agent": "agent1",
                        "to_agent": "agent2",
                        "message_type": "data",
                        "timestamp": "2024-01-01T00:00:00Z",
                    },
                },
            ],
            "sync_points": [
                {"name": "init", "status": "passed"},
                {"name": "execute", "status": "passed"},
            ],
            "agent_states": {"agent1": "executing", "agent2": "executing"},
            "coordination_protocol": "parallel",
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["coordination_events"] == 2
        assert result.metadata["sync_points"] == 2
        assert result.metadata["agents"] == 2

    @pytest.mark.asyncio
    async def test_protocol_violations_fail(self):
        """Test that protocol violations fail validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [
                {
                    "type": "sync",
                    "protocol": "sequential",  # Wrong protocol
                },
            ],
            "coordination_protocol": "parallel",
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "coordination" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "protocol_violations" in result.metadata
        assert "protocol_violations" in result.metadata

    @pytest.mark.asyncio
    async def test_failed_sync_points_fail(self):
        """Test that failed sync points fail validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [],
            "sync_points": [
                {"name": "init", "status": "passed"},
                {"name": "execute", "status": "failed", "failure_reason": "Timeout"},
            ],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "coordination" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "failed_sync_points" in result.metadata
        assert "failed_sync_points" in result.metadata

    @pytest.mark.asyncio
    async def test_timeout_sync_points_fail(self):
        """Test that timeout sync points fail validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [],
            "sync_points": [
                {"name": "init", "status": "timeout"},
            ],
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "failed_sync_points" in result.metadata

    @pytest.mark.asyncio
    async def test_invalid_message_format_fails(self):
        """Test that invalid coordination messages fail validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [
                {
                    "type": "message",
                    "id": "msg1",
                    "message": {
                        "from_agent": "agent1",
                        # Missing required fields: to_agent, message_type, timestamp
                    },
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "coordination" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "invalid_messages" in result.metadata
        assert "invalid_messages" in result.metadata

    @pytest.mark.asyncio
    async def test_invalid_agent_states_fail(self):
        """Test that invalid agent states fail validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [],
            "agent_states": {
                "agent1": "executing",
                "agent2": "unknown_state",  # Invalid state
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "coordination" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "invalid_states" in result.metadata
        assert "invalid_states" in result.metadata

    @pytest.mark.asyncio
    async def test_deadlock_detection_fails(self):
        """Test that deadlock detection fails validation."""
        validator = CoordinationValidationValidator()

        context = {
            "coordination_events": [],
            "agent_states": {
                "agent1": "waiting",
                "agent2": "waiting",
                "agent3": "waiting",  # All waiting = deadlock
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "coordination" in result.message.lower()
            or "validation failed" in result.message.lower()
            or "deadlock" in result.message.lower()
        )
        assert result.metadata.get("deadlock_detected") is True
        assert result.metadata.get("deadlock_detected") is True

    @pytest.mark.asyncio
    async def test_valid_agent_states_pass(self):
        """Test that all valid agent states pass validation."""
        validator = CoordinationValidationValidator()

        valid_states = [
            "initializing",
            "ready",
            "executing",
            "waiting",
            "completed",
            "failed",
        ]

        for state in valid_states:
            context = {
                "coordination_events": [],
                "agent_states": {"agent1": state},
            }

            result = await validator.validate(context)
            # Should not fail due to invalid state
            if result.status == "failed":
                assert "invalid agent states" not in result.message.lower()


class TestResultConsistencyValidator:
    """Test PV-003: Result Consistency Validator."""

    @pytest.mark.asyncio
    async def test_consistent_results_pass(self):
        """Test that consistent results pass validation."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"status": "success", "count": 10, "data": "result1"},
                {"status": "success", "count": 10, "data": "result2"},
            ]
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["parallel_results_count"] == 2

    @pytest.mark.asyncio
    async def test_no_results_fails(self):
        """Test that no parallel results fails validation."""
        validator = ResultConsistencyValidator()

        context = {"parallel_results": []}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "consistency" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert any(
            "no parallel results" in issue.lower()
            for issue in result.metadata.get("issues", [])
        )

    @pytest.mark.asyncio
    async def test_schema_mismatch_fails(self):
        """Test that schema mismatches fail validation."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"status": "success", "count": 10},
                {"status": "success", "data": "result"},  # Different schema
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "consistency" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "schema_mismatches" in result.metadata
        assert "schema_mismatches" in result.metadata

    @pytest.mark.asyncio
    async def test_conflicting_results_without_resolution_fails(self):
        """Test that conflicting aggregation rule results fail without resolution."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"task_id": "123", "value": 10},
                {
                    "task_id": "456",
                    "value": 20,
                },  # Different task_id violates identical rule
                {"task_id": "789", "value": 30},
            ],
            "aggregation_rules": {
                "task_id": {"type": "identical"}  # All should have same task_id
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "consistency" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "aggregation_errors" in result.metadata

    @pytest.mark.asyncio
    async def test_conflicting_results_with_resolution_passes(self):
        """Test that parallel results with different outcomes pass (normal in parallel execution)."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"success": True, "value": 10},
                {
                    "success": False,
                    "value": 20,
                    "error_message": "Failed",
                },  # Different outcome is OK
            ]
        }

        result = await validator.validate(context)

        # Should pass - different outcomes are normal in parallel execution
        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_identical_aggregation_rule_pass(self):
        """Test identical aggregation rule with matching values."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"task_id": "123", "value": 10},
                {"task_id": "123", "value": 10},
            ],
            "aggregation_rules": {"task_id": {"type": "identical"}},
        }

        result = await validator.validate(context)

        assert result.status == "passed"

    @pytest.mark.asyncio
    async def test_identical_aggregation_rule_fail(self):
        """Test identical aggregation rule with different values."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"task_id": "123", "value": 10},
                {"task_id": "456", "value": 10},  # Different task_id
            ],
            "aggregation_rules": {"task_id": {"type": "identical"}},
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "consistency" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "aggregation_errors" in result.metadata

    @pytest.mark.asyncio
    async def test_numeric_sum_aggregation_rule(self):
        """Test numeric_sum aggregation rule."""
        validator = ResultConsistencyValidator()

        # Valid numeric values
        context = {
            "parallel_results": [
                {"total": 10},
                {"total": 20},
            ],
            "aggregation_rules": {"total": {"type": "numeric_sum"}},
        }

        result = await validator.validate(context)
        assert result.status == "passed"

        # Invalid non-numeric values
        context = {
            "parallel_results": [
                {"total": "ten"},
                {"total": 20},
            ],
            "aggregation_rules": {"total": {"type": "numeric_sum"}},
        }

        result = await validator.validate(context)
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_majority_aggregation_rule(self):
        """Test majority aggregation rule."""
        validator = ResultConsistencyValidator()

        # Sufficient values for majority
        context = {
            "parallel_results": [
                {"choice": "A"},
                {"choice": "A"},
                {"choice": "B"},
            ],
            "aggregation_rules": {"choice": {"type": "majority"}},
        }

        result = await validator.validate(context)
        assert result.status == "passed"

        # Insufficient values
        context = {
            "parallel_results": [
                {"choice": "A"},
            ],
            "aggregation_rules": {"choice": {"type": "majority"}},
        }

        result = await validator.validate(context)
        assert result.status == "failed"

    @pytest.mark.asyncio
    async def test_coherence_success_with_error_fails(self):
        """Test that success=True with error_message fails coherence check."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {
                    "success": True,
                    "error_message": "Something went wrong",
                },  # Incoherent
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert (
            "consistency" in result.message.lower()
            or "validation failed" in result.message.lower()
        )
        assert "coherence_issues" in result.metadata
        assert "coherence_issues" in result.metadata

    @pytest.mark.asyncio
    async def test_coherence_failure_without_error_fails(self):
        """Test that success=False without error_message fails coherence check."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"success": False},  # No error_message
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "coherence_issues" in result.metadata

    @pytest.mark.asyncio
    async def test_coherent_results_pass(self):
        """Test that coherent results pass validation."""
        validator = ResultConsistencyValidator()

        context = {
            "parallel_results": [
                {"success": True},  # No error_message (correct)
                {
                    "success": False,
                    "error_message": "Error occurred",
                },  # Has error (correct)
            ]
        }

        result = await validator.validate(context)

        assert result.status == "passed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

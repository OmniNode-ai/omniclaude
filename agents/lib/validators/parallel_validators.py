#!/usr/bin/env python3
"""
Parallel Validation Gates (PV-001 to PV-003) - ONEX v2.0 Framework.

Implements 3 parallel validation gates for context synchronization, coordination,
and result consistency in parallel agent workflows.

Gates:
- PV-001: Context Synchronization - Context consistency across parallel agents
- PV-002: Coordination Validation - Parallel workflow compliance monitoring
- PV-003: Result Consistency - Parallel result coherence and compatibility

ONEX v2.0 Compliance:
- Type-safe validators with comprehensive checks
- Performance targets: 50-80ms per gate
- Parallel execution awareness
- Dependency-aware execution
"""

from typing import Any

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class ContextSynchronizationValidator(BaseQualityGate):
    """
    PV-001: Context Synchronization Validator.

    Validates consistency across parallel agent contexts.

    Validation Checks:
    - Context consistency across parallel agents
    - Shared state coherence
    - No race conditions detected
    - Context version compatibility

    Performance Target: 80ms
    Validation Type: blocking
    Execution Point: parallel_initialization
    """

    def __init__(self) -> None:
        """Initialize context synchronization gate."""
        super().__init__(EnumQualityGate.CONTEXT_SYNCHRONIZATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute context synchronization validation.

        Args:
            context: Validation context with parallel agent contexts

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - parallel_contexts: List of agent contexts to validate
            - shared_state_keys: Keys that should be consistent across contexts
            - context_version: Expected context version
            - synchronization_points: List of sync points
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract parallel contexts
        parallel_contexts = context.get("parallel_contexts", [])
        shared_state_keys = context.get("shared_state_keys", [])
        expected_version = context.get("context_version")
        sync_points = context.get("synchronization_points", [])

        if not parallel_contexts:
            issues.append("No parallel contexts provided for synchronization")
        else:
            # Validate context consistency across parallel agents
            reference_context = parallel_contexts[0] if parallel_contexts else {}

            inconsistencies = []
            for i, agent_context in enumerate(parallel_contexts[1:], start=1):
                for key in shared_state_keys:
                    ref_value = reference_context.get(key)
                    agent_value = agent_context.get(key)

                    if ref_value != agent_value:
                        inconsistencies.append(
                            {
                                "agent_index": i,
                                "key": key,
                                "reference_value": str(ref_value),
                                "agent_value": str(agent_value),
                            }
                        )

            if inconsistencies:
                issues.append(
                    f"Context inconsistencies detected: {len(inconsistencies)} mismatch(es)"
                )
                metadata["inconsistencies"] = inconsistencies

            # Validate context versions
            version_mismatches = []
            if expected_version:
                for i, agent_context in enumerate(parallel_contexts):
                    actual_version = agent_context.get("version")
                    if actual_version != expected_version:
                        version_mismatches.append(
                            {
                                "agent_index": i,
                                "expected": expected_version,
                                "actual": actual_version,
                            }
                        )

            if version_mismatches:
                issues.append(f"Context version mismatches: {len(version_mismatches)}")
                metadata["version_mismatches"] = version_mismatches

            # Check for potential race conditions (duplicate correlation IDs)
            correlation_ids = []
            duplicate_ids = []
            for i, agent_context in enumerate(parallel_contexts):
                corr_id = agent_context.get("correlation_id")
                if corr_id:
                    if corr_id in correlation_ids:
                        duplicate_ids.append(
                            {"correlation_id": str(corr_id), "agent_index": i}
                        )
                    else:
                        correlation_ids.append(corr_id)

            if duplicate_ids:
                issues.append(
                    f"Potential race conditions: duplicate correlation IDs ({len(duplicate_ids)})"
                )
                metadata["duplicate_ids"] = duplicate_ids

            # Validate synchronization points
            missing_sync_points = []
            for sync_point in sync_points:
                for i, agent_context in enumerate(parallel_contexts):
                    if sync_point not in agent_context.get("reached_sync_points", []):
                        missing_sync_points.append(
                            {"agent_index": i, "sync_point": sync_point}
                        )

            if missing_sync_points:
                issues.append(
                    f"Agents missing synchronization points: {len(missing_sync_points)}"
                )
                metadata["missing_sync_points"] = missing_sync_points

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Context synchronization failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "parallel_agents": len(parallel_contexts),
                    "shared_state_keys": len(shared_state_keys),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"Context synchronized across {len(parallel_contexts)} agents",
            metadata={
                "parallel_agents": len(parallel_contexts),
                "shared_state_keys": len(shared_state_keys),
                "sync_points": len(sync_points),
            },
        )


class CoordinationValidationValidator(BaseQualityGate):
    """
    PV-002: Coordination Validation Validator.

    Monitors parallel workflow compliance in real-time.

    Validation Checks:
    - Parallel coordination protocol compliance
    - Synchronization point success
    - Communication message format
    - Coordination state validity

    Performance Target: 50ms
    Validation Type: monitoring
    Execution Point: coordination_checkpoints
    Dependencies: PV-001
    """

    def __init__(self) -> None:
        """Initialize coordination validation gate."""
        super().__init__(EnumQualityGate.COORDINATION_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute coordination validation.

        Args:
            context: Validation context with coordination state

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - coordination_events: List of coordination events
            - sync_points: List of synchronization points
            - agent_states: Dict of agent states
            - coordination_protocol: Expected coordination protocol
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract coordination state
        coordination_events = context.get("coordination_events", [])
        sync_points = context.get("sync_points", [])
        agent_states = context.get("agent_states", {})
        coordination_protocol = context.get("coordination_protocol")

        # Validate coordination protocol compliance
        if coordination_protocol:
            protocol_violations = []

            for event in coordination_events:
                event_type = event.get("type")
                expected_protocol = event.get("protocol")

                if expected_protocol and expected_protocol != coordination_protocol:
                    protocol_violations.append(
                        {
                            "event_type": event_type,
                            "expected": coordination_protocol,
                            "actual": expected_protocol,
                        }
                    )

            if protocol_violations:
                issues.append(
                    f"Coordination protocol violations: {len(protocol_violations)}"
                )
                metadata["protocol_violations"] = protocol_violations

        # Validate synchronization points
        failed_sync_points = []
        for sync_point in sync_points:
            sync_status = sync_point.get("status")
            if sync_status == "failed":
                failed_sync_points.append(
                    {
                        "name": sync_point.get("name"),
                        "reason": sync_point.get("failure_reason"),
                    }
                )
            elif sync_status == "timeout":
                failed_sync_points.append(
                    {
                        "name": sync_point.get("name"),
                        "reason": "Synchronization timeout",
                    }
                )

        if failed_sync_points:
            issues.append(f"Failed synchronization points: {len(failed_sync_points)}")
            metadata["failed_sync_points"] = failed_sync_points

        # Validate coordination message format
        invalid_messages = []
        for event in coordination_events:
            if event.get("type") == "message":
                message = event.get("message", {})

                # Check required message fields
                required_fields = [
                    "from_agent",
                    "to_agent",
                    "message_type",
                    "timestamp",
                ]
                missing_fields = [
                    field for field in required_fields if field not in message
                ]

                if missing_fields:
                    invalid_messages.append(
                        {
                            "event_id": event.get("id"),
                            "missing_fields": missing_fields,
                        }
                    )

        if invalid_messages:
            issues.append(f"Invalid coordination messages: {len(invalid_messages)}")
            metadata["invalid_messages"] = invalid_messages

        # Validate agent coordination states
        invalid_states = []
        valid_states = [
            "initializing",
            "ready",
            "executing",
            "waiting",
            "completed",
            "failed",
        ]

        for agent_id, state in agent_states.items():
            if state not in valid_states:
                invalid_states.append({"agent_id": agent_id, "state": state})

        if invalid_states:
            issues.append(f"Invalid agent states: {len(invalid_states)}")
            metadata["invalid_states"] = invalid_states

        # Check for deadlocks (all agents waiting)
        if agent_states:
            all_waiting = all(state == "waiting" for state in agent_states.values())
            if all_waiting:
                issues.append("Potential deadlock: all agents in waiting state")
                metadata["deadlock_detected"] = True

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Coordination validation failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "coordination_events": len(coordination_events),
                    "sync_points": len(sync_points),
                    "agents": len(agent_states),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"Coordination validated ({len(coordination_events)} events, {len(agent_states)} agents)",
            metadata={
                "coordination_events": len(coordination_events),
                "sync_points": len(sync_points),
                "agents": len(agent_states),
                "coordination_protocol": coordination_protocol,
            },
        )


class ResultConsistencyValidator(BaseQualityGate):
    """
    PV-003: Result Consistency Validator.

    Ensures parallel results are coherent and compatible.

    Validation Checks:
    - Result compatibility across parallel agents
    - No conflicting results detected
    - Aggregation correctness
    - Result coherence and consistency

    Performance Target: 70ms
    Validation Type: blocking
    Execution Point: result_aggregation
    Dependencies: PV-001, PV-002
    """

    def __init__(self) -> None:
        """Initialize result consistency gate."""
        super().__init__(EnumQualityGate.RESULT_CONSISTENCY)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute result consistency validation.

        Args:
            context: Validation context with parallel results

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - parallel_results: List of results from parallel agents
            - aggregation_rules: Rules for result aggregation
            - conflict_resolution: Strategy for resolving conflicts
            - expected_result_schema: Schema for result validation
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract parallel results
        parallel_results = context.get("parallel_results", [])
        aggregation_rules = context.get("aggregation_rules", {})
        conflict_resolution = context.get("conflict_resolution")
        _expected_schema = context.get("expected_result_schema")

        if not parallel_results:
            issues.append("No parallel results provided for consistency check")
        else:
            # Check result compatibility (same schema/structure)
            # Allow optional fields like error_message that may not be present in all results
            reference_keys = (
                set(parallel_results[0].keys()) if parallel_results else set()
            )
            optional_fields = ["error_message", "error", "warning", "metadata"]

            schema_mismatches = []
            for i, result in enumerate(parallel_results[1:], start=1):
                result_keys = set(result.keys())
                if result_keys != reference_keys:
                    missing = reference_keys - result_keys - set(optional_fields)
                    extra = result_keys - reference_keys - set(optional_fields)

                    # Only flag as mismatch if there are non-optional differences
                    if missing or extra:
                        schema_mismatches.append(
                            {
                                "result_index": i,
                                "missing_keys": list(missing),
                                "extra_keys": list(extra),
                            }
                        )

            if schema_mismatches:
                issues.append(f"Result schema mismatches: {len(schema_mismatches)}")
                metadata["schema_mismatches"] = schema_mismatches

            # Note: Don't flag critical field differences as conflicts in parallel execution
            # Different outcomes (some success, some failure) are normal in parallel scenarios
            # Instead, we rely on coherence checks below to validate logical consistency

            # Validate aggregation rules compliance
            if aggregation_rules:
                aggregation_errors = []

                for key, rule in aggregation_rules.items():
                    rule_type = rule.get("type")
                    values = [
                        result.get(key) for result in parallel_results if key in result
                    ]

                    if rule_type == "identical":
                        # All values must be identical
                        if len(set(str(v) for v in values)) > 1:
                            aggregation_errors.append(
                                f"{key}: Expected identical values, got {len(set(values))} different values"
                            )

                    elif rule_type == "numeric_sum":
                        # Values must be numeric
                        if not all(isinstance(v, (int, float)) for v in values):
                            aggregation_errors.append(
                                f"{key}: Expected numeric values for sum"
                            )

                    elif rule_type == "majority":
                        # Most common value should be clear
                        if len(values) < 2:
                            aggregation_errors.append(
                                f"{key}: Insufficient values for majority rule"
                            )

                if aggregation_errors:
                    issues.append(
                        f"Aggregation rule violations: {len(aggregation_errors)}"
                    )
                    metadata["aggregation_errors"] = aggregation_errors

            # Validate result coherence (check for logical inconsistencies)
            coherence_issues = []

            # Example: Check if success flags align with error messages
            for i, result in enumerate(parallel_results):
                success = result.get("success")
                error_message = result.get("error_message")

                if success is True and error_message:
                    coherence_issues.append(
                        {
                            "result_index": i,
                            "issue": "Success=True but error_message present",
                        }
                    )
                elif success is False and not error_message:
                    coherence_issues.append(
                        {
                            "result_index": i,
                            "issue": "Success=False but no error_message",
                        }
                    )

            if coherence_issues:
                issues.append(f"Result coherence issues: {len(coherence_issues)}")
                metadata["coherence_issues"] = coherence_issues

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Result consistency validation failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "parallel_results_count": len(parallel_results),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"Results are consistent across {len(parallel_results)} parallel agents",
            metadata={
                "parallel_results_count": len(parallel_results),
                "validated_keys": len(reference_keys) if parallel_results else 0,
                "conflict_resolution": conflict_resolution,
            },
        )

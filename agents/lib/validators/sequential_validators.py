#!/usr/bin/env python3
"""
Sequential Validation Gates (SV-001 to SV-004) - ONEX v2.0 Framework.

Implements 4 sequential validation gates for input, process, output, and integration
validation in agent workflows.

Gates:
- SV-001: Input Validation - Schema and requirement validation
- SV-002: Process Validation - Workflow pattern compliance
- SV-003: Output Validation - Comprehensive result verification
- SV-004: Integration Testing - Agent interaction and handoff validation

ONEX v2.0 Compliance:
- Type-safe validators with Pydantic models
- Performance targets: 30-60ms per gate
- Comprehensive error handling
- Dependency-aware execution
"""

import re
from typing import Any

from pydantic import BaseModel, ValidationError

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from .base_quality_gate import BaseQualityGate


class InputValidationValidator(BaseQualityGate):
    """
    SV-001: Input Validation Validator.

    Verifies all inputs meet requirements before task execution.

    Validation Checks:
    - Schema validation (Pydantic models)
    - Required field presence
    - Type correctness (str, int, UUID, etc.)
    - Value constraints (min/max, regex patterns)
    - Null/empty checks

    Performance Target: 50ms
    Validation Type: blocking
    Execution Point: pre_task_execution
    """

    def __init__(self) -> None:
        """Initialize input validation gate."""
        super().__init__(EnumQualityGate.INPUT_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute input validation.

        Args:
            context: Validation context with inputs to validate

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - inputs: Dict of inputs to validate
            - required_fields: List of required field names
            - schema: Optional Pydantic model for validation
            - constraints: Dict of field constraints (min/max, patterns)
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract validation config
        inputs = context.get("inputs", {})
        required_fields = context.get("required_fields", [])
        schema = context.get("schema")
        constraints = context.get("constraints", {})

        # Check required fields
        missing_fields = [field for field in required_fields if field not in inputs]
        if missing_fields:
            issues.append(f"Missing required fields: {', '.join(missing_fields)}")
            metadata["missing_fields"] = missing_fields

        # Check for null/empty values in required fields
        for field in required_fields:
            if field in inputs:
                value = inputs[field]
                if value is None or (isinstance(value, str) and not value.strip()):
                    issues.append(f"Field '{field}' is null or empty")

        # Validate with Pydantic schema if provided
        if schema and isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**inputs)
            except ValidationError as e:
                issues.append(f"Schema validation failed: {len(e.errors())} errors")
                metadata["schema_errors"] = [
                    {
                        "field": err["loc"][0] if err["loc"] else "unknown",
                        "error": err["msg"],
                    }
                    for err in e.errors()
                ]

        # Validate constraints
        for field, field_constraints in constraints.items():
            if field not in inputs:
                continue

            value = inputs[field]

            # Type validation
            if "type" in field_constraints:
                expected_type = field_constraints["type"]
                if not isinstance(value, expected_type):
                    issues.append(
                        f"Field '{field}' has incorrect type: expected {expected_type.__name__}, got {type(value).__name__}"
                    )

            # Min/max validation for numeric types
            if isinstance(value, (int, float)):
                if "min" in field_constraints and value < field_constraints["min"]:
                    issues.append(
                        f"Field '{field}' value {value} below minimum {field_constraints['min']}"
                    )
                if "max" in field_constraints and value > field_constraints["max"]:
                    issues.append(
                        f"Field '{field}' value {value} above maximum {field_constraints['max']}"
                    )

            # Length validation for strings
            if isinstance(value, str):
                if (
                    "min_length" in field_constraints
                    and len(value) < field_constraints["min_length"]
                ):
                    issues.append(
                        f"Field '{field}' length {len(value)} below minimum {field_constraints['min_length']}"
                    )
                if (
                    "max_length" in field_constraints
                    and len(value) > field_constraints["max_length"]
                ):
                    issues.append(
                        f"Field '{field}' length {len(value)} above maximum {field_constraints['max_length']}"
                    )

            # Pattern validation
            if "pattern" in field_constraints and isinstance(value, str):
                pattern = field_constraints["pattern"]
                if not re.match(pattern, value):
                    issues.append(f"Field '{field}' does not match pattern {pattern}")

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,  # Will be set by execute_with_timing
                message=f"Input validation failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "validated_fields": len(inputs),
                    "required_fields": len(required_fields),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,  # Will be set by execute_with_timing
            message=f"All inputs validated successfully ({len(inputs)} fields checked)",
            metadata={
                "validated_fields": len(inputs),
                "required_fields": len(required_fields),
            },
        )


class ProcessValidationValidator(BaseQualityGate):
    """
    SV-002: Process Validation Validator.

    Ensures workflows follow established patterns during execution.

    Validation Checks:
    - Workflow pattern matching (against known patterns)
    - Stage execution order correctness
    - State transition validity
    - Anti-YOLO compliance (no skipped steps)

    Performance Target: 30ms
    Validation Type: monitoring
    Execution Point: during_execution
    Dependencies: SV-001
    """

    def __init__(self) -> None:
        """Initialize process validation gate."""
        super().__init__(EnumQualityGate.PROCESS_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute process validation.

        Args:
            context: Validation context with process state

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - current_stage: Current workflow stage
            - completed_stages: List of completed stages
            - expected_stages: Expected stage sequence
            - workflow_pattern: Expected workflow pattern name
            - state_transitions: List of state transitions
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract process state
        current_stage = context.get("current_stage")
        completed_stages = context.get("completed_stages", [])
        expected_stages = context.get("expected_stages", [])
        workflow_pattern = context.get("workflow_pattern")
        state_transitions = context.get("state_transitions", [])

        # Validate stage ordering
        if expected_stages:
            for i, expected_stage in enumerate(expected_stages):
                if i < len(completed_stages):
                    actual_stage = completed_stages[i]
                    if actual_stage != expected_stage:
                        issues.append(
                            f"Stage order violation: expected '{expected_stage}' at position {i}, got '{actual_stage}'"
                        )
                        metadata["order_violations"] = metadata.get(
                            "order_violations", []
                        ) + [
                            {
                                "position": i,
                                "expected": expected_stage,
                                "actual": actual_stage,
                            }
                        ]

            # Check for skipped stages (anti-YOLO)
            if current_stage and expected_stages:
                try:
                    current_idx = expected_stages.index(current_stage)
                    for i in range(current_idx):
                        if expected_stages[i] not in completed_stages:
                            issues.append(
                                f"Stage '{expected_stages[i]}' was skipped before '{current_stage}'"
                            )
                            metadata["skipped_stages"] = metadata.get(
                                "skipped_stages", []
                            ) + [expected_stages[i]]
                except ValueError:
                    issues.append(
                        f"Current stage '{current_stage}' not in expected stages"
                    )

        # Validate workflow pattern
        if workflow_pattern:
            known_patterns = [
                "sequential_execution",
                "parallel_execution",
                "intelligence_gathering",
                "multi_agent_coordination",
                "six_phase_generation",
            ]
            if workflow_pattern not in known_patterns:
                issues.append(f"Unknown workflow pattern: '{workflow_pattern}'")
                metadata["unknown_pattern"] = workflow_pattern

        # Validate state transitions
        invalid_transitions = []
        for transition in state_transitions:
            from_state = transition.get("from")
            to_state = transition.get("to")

            # Check for invalid transitions (e.g., completed -> pending)
            if from_state == "completed" and to_state in ["pending", "initializing"]:
                invalid_transitions.append(f"{from_state} -> {to_state}")
            elif from_state == "failed" and to_state == "in_progress":
                invalid_transitions.append(f"{from_state} -> {to_state}")

        if invalid_transitions:
            issues.append(
                f"Invalid state transitions: {', '.join(invalid_transitions)}"
            )
            metadata["invalid_transitions"] = invalid_transitions

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Process validation failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "completed_stages_count": len(completed_stages),
                    "current_stage": current_stage,
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"Process validation passed (stage {len(completed_stages) + 1}/{len(expected_stages) if expected_stages else 'unknown'})",
            metadata={
                "completed_stages_count": len(completed_stages),
                "current_stage": current_stage,
                "workflow_pattern": workflow_pattern,
            },
        )


class OutputValidationValidator(BaseQualityGate):
    """
    SV-003: Output Validation Validator.

    Comprehensive result verification before completion.

    Validation Checks:
    - Output schema validation
    - Completeness checks (all expected fields present)
    - Quality metrics validation
    - Generated file existence and validity

    Performance Target: 40ms
    Validation Type: blocking
    Execution Point: post_execution
    Dependencies: SV-002
    """

    def __init__(self) -> None:
        """Initialize output validation gate."""
        super().__init__(EnumQualityGate.OUTPUT_VALIDATION)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute output validation.

        Args:
            context: Validation context with outputs

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - outputs: Dict of outputs to validate
            - expected_outputs: List of expected output keys
            - schema: Optional Pydantic model for validation
            - generated_files: List of expected file paths
            - quality_metrics: Dict of quality metric requirements
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract validation config
        outputs = context.get("outputs", {})
        expected_outputs = context.get("expected_outputs", [])
        schema = context.get("schema")
        generated_files = context.get("generated_files", [])
        quality_metrics = context.get("quality_metrics", {})

        # Check for expected outputs
        missing_outputs = [key for key in expected_outputs if key not in outputs]
        if missing_outputs:
            issues.append(f"Missing expected outputs: {', '.join(missing_outputs)}")
            metadata["missing_outputs"] = missing_outputs

        # Check completeness (no null values in expected outputs)
        for key in expected_outputs:
            if key in outputs and outputs[key] is None:
                issues.append(f"Output '{key}' is null")

        # Validate with Pydantic schema if provided
        if schema and isinstance(schema, type) and issubclass(schema, BaseModel):
            try:
                schema(**outputs)
            except ValidationError as e:
                issues.append(
                    f"Output schema validation failed: {len(e.errors())} errors"
                )
                metadata["schema_errors"] = [
                    {
                        "field": err["loc"][0] if err["loc"] else "unknown",
                        "error": err["msg"],
                    }
                    for err in e.errors()
                ]

        # Validate generated files (check if they exist)
        import os

        missing_files = []
        for file_path in generated_files:
            if not os.path.exists(file_path):
                missing_files.append(file_path)

        if missing_files:
            issues.append(f"Generated files not found: {len(missing_files)} file(s)")
            metadata["missing_files"] = missing_files

        # Validate quality metrics
        failed_metrics = []
        for metric_name, requirement in quality_metrics.items():
            actual_value = outputs.get(metric_name)
            if actual_value is None:
                failed_metrics.append(f"{metric_name}: missing")
                continue

            # Check thresholds
            if "min" in requirement and actual_value < requirement["min"]:
                failed_metrics.append(
                    f"{metric_name}: {actual_value} < {requirement['min']} (min)"
                )
            if "max" in requirement and actual_value > requirement["max"]:
                failed_metrics.append(
                    f"{metric_name}: {actual_value} > {requirement['max']} (max)"
                )

        if failed_metrics:
            issues.append(f"Quality metrics not met: {', '.join(failed_metrics)}")
            metadata["failed_metrics"] = failed_metrics

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Output validation failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "validated_outputs": len(outputs),
                    "expected_outputs": len(expected_outputs),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"All outputs validated successfully ({len(outputs)} outputs, {len(generated_files)} files)",
            metadata={
                "validated_outputs": len(outputs),
                "expected_outputs": len(expected_outputs),
                "validated_files": len(generated_files),
            },
        )


class IntegrationTestingValidator(BaseQualityGate):
    """
    SV-004: Integration Testing Validator.

    Validates agent interactions and handoffs.

    Validation Checks:
    - Delegation handoff success
    - Context preservation during delegation
    - Inter-agent message format correctness
    - Coordination protocol compliance

    Performance Target: 60ms
    Validation Type: checkpoint
    Execution Point: delegation_points
    Dependencies: SV-001, SV-002
    """

    def __init__(self) -> None:
        """Initialize integration testing gate."""
        super().__init__(EnumQualityGate.INTEGRATION_TESTING)

    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute integration testing validation.

        Args:
            context: Validation context with delegation state

        Returns:
            ModelQualityGateResult with validation outcome

        Context Keys:
            - delegations: List of delegation events
            - context_transfers: List of context transfer events
            - messages: List of inter-agent messages
            - coordination_protocol: Expected coordination protocol
        """
        issues = []
        metadata: dict[str, Any] = {}

        # Extract delegation state
        delegations = context.get("delegations", [])
        context_transfers = context.get("context_transfers", [])
        messages = context.get("messages", [])
        coordination_protocol = context.get("coordination_protocol")

        # Validate delegations
        failed_delegations = []
        for delegation in delegations:
            if delegation.get("status") == "failed":
                failed_delegations.append(delegation.get("target_agent", "unknown"))

        if failed_delegations:
            issues.append(f"Failed delegations to: {', '.join(failed_delegations)}")
            metadata["failed_delegations"] = failed_delegations

        # Validate context preservation
        incomplete_transfers = []
        for transfer in context_transfers:
            required_keys = transfer.get("required_keys", [])
            transferred_context = transfer.get("context", {})

            missing_keys = [
                key for key in required_keys if key not in transferred_context
            ]
            if missing_keys:
                incomplete_transfers.append(
                    {
                        "agent": transfer.get("target_agent"),
                        "missing_keys": missing_keys,
                    }
                )

        if incomplete_transfers:
            issues.append(f"Incomplete context transfers: {len(incomplete_transfers)}")
            metadata["incomplete_transfers"] = incomplete_transfers

        # Validate message format
        invalid_messages = []
        for msg in messages:
            # Check required message fields
            required_fields = ["sender", "recipient", "message_type", "payload"]
            missing_fields = [field for field in required_fields if field not in msg]

            if missing_fields:
                invalid_messages.append(
                    {
                        "index": messages.index(msg),
                        "missing_fields": missing_fields,
                    }
                )

        if invalid_messages:
            issues.append(f"Invalid message format: {len(invalid_messages)} message(s)")
            metadata["invalid_messages"] = invalid_messages

        # Validate coordination protocol
        if coordination_protocol:
            protocol_violations = []

            # Check if protocol-specific requirements are met
            if coordination_protocol == "sequential":
                # Sequential coordination requires ordered execution
                if context.get("parallel_execution", False):
                    protocol_violations.append(
                        "Sequential protocol violated: parallel execution detected"
                    )

            elif coordination_protocol == "parallel":
                # Parallel coordination requires sync points
                if not context.get("sync_points"):
                    protocol_violations.append(
                        "Parallel protocol violated: no sync points defined"
                    )

            if protocol_violations:
                issues.append(
                    f"Coordination protocol violations: {len(protocol_violations)}"
                )
                metadata["protocol_violations"] = protocol_violations

        # Generate result
        if issues:
            return ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=0,
                message=f"Integration testing failed: {len(issues)} issue(s)",
                metadata={
                    **metadata,
                    "issues": issues,
                    "delegations_count": len(delegations),
                    "messages_count": len(messages),
                },
            )

        return ModelQualityGateResult(
            gate=self.gate,
            status="passed",
            execution_time_ms=0,
            message=f"Integration testing passed ({len(delegations)} delegations, {len(messages)} messages)",
            metadata={
                "delegations_count": len(delegations),
                "context_transfers_count": len(context_transfers),
                "messages_count": len(messages),
                "coordination_protocol": coordination_protocol,
            },
        )

#!/usr/bin/env python3
"""
Base Quality Gate Validator for ONEX Agent Framework.

Abstract base class for all quality gate validators with dependency checking.

ONEX v2.0 Compliance:
- Abstract base class pattern
- Type-safe validation interface
- Dependency management with execution ordering
- Event publishing for quality gate results
"""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from ..models.model_quality_gate import EnumQualityGate, ModelQualityGateResult
from ..quality_gate_publisher import (
    publish_quality_gate_failed,
    publish_quality_gate_passed,
)

logger = logging.getLogger(__name__)


class BaseQualityGate(ABC):
    """
    Abstract base class for quality gate validators.

    Provides common infrastructure for:
    - Gate execution with timing
    - Dependency checking
    - Result generation
    - Error handling

    Subclasses must implement validate() to perform actual validation logic.

    Example:
        class InputValidationGate(BaseQualityGate):
            def __init__(self):
                super().__init__(EnumQualityGate.INPUT_VALIDATION)

            async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
                # Validation logic here
                return ModelQualityGateResult(
                    gate=self.gate,
                    status="passed",
                    execution_time_ms=45,
                    message="All inputs valid"
                )
    """

    def __init__(self, gate: EnumQualityGate) -> None:
        """
        Initialize the quality gate validator.

        Args:
            gate: The quality gate enum this validator implements
        """
        self.gate = gate

    @abstractmethod
    async def validate(self, context: dict[str, Any]) -> ModelQualityGateResult:
        """
        Execute the quality gate validation.

        Subclasses must implement this method to perform the actual validation
        logic. The method should:
        1. Extract relevant data from context
        2. Perform validation checks
        3. Return a ModelQualityGateResult with status and timing

        Args:
            context: Validation context containing inputs, state, and config

        Returns:
            ModelQualityGateResult with validation outcome

        Raises:
            Exception: Validation errors should be caught and returned as failed status
        """
        pass

    def check_dependencies(
        self, results: list[ModelQualityGateResult]
    ) -> tuple[bool, list[str]]:
        """
        Check if all dependency gates have passed.

        Validates that all gates this gate depends on have been executed
        successfully before this gate can run.

        Args:
            results: List of previously executed gate results

        Returns:
            Tuple of (dependencies_met, missing_dependencies):
            - dependencies_met: True if all dependencies passed
            - missing_dependencies: List of gate IDs that failed or are missing

        Example:
            met, missing = gate.check_dependencies(previous_results)
            if not met:
                print(f"Cannot run gate: missing {missing}")
        """
        dependencies = self.gate.dependencies
        if not dependencies:
            # No dependencies, can always run
            return True, []

        # Map dependency IDs to gate results
        result_map = {self._get_gate_id(r.gate): r for r in results}

        missing = []
        for dep_id in dependencies:
            if dep_id not in result_map:
                # Dependency hasn't been executed yet
                missing.append(dep_id)
            elif result_map[dep_id].status != "passed":
                # Dependency failed or was skipped
                missing.append(dep_id)

        return len(missing) == 0, missing

    def should_skip(
        self, context: dict[str, Any], results: list[ModelQualityGateResult]
    ) -> tuple[bool, str]:
        """
        Determine if this gate should be skipped.

        Checks both dependencies and context to decide if validation should run.

        Args:
            context: Validation context
            results: Previously executed gate results

        Returns:
            Tuple of (should_skip, reason):
            - should_skip: True if gate should be skipped
            - reason: Human-readable reason for skipping

        Example:
            should_skip, reason = gate.should_skip(context, results)
            if should_skip:
                return create_skipped_result(reason)
        """
        # Check dependencies first
        deps_met, missing = self.check_dependencies(results)
        if not deps_met:
            return True, f"Dependencies not met: {', '.join(missing)}"

        # Check if gate is explicitly disabled in context
        disabled_gates = context.get("disabled_gates", [])
        if self.gate in disabled_gates:
            return True, "Gate explicitly disabled in context"

        # Check if validation type should be skipped based on context
        skip_monitoring = context.get("skip_monitoring_gates", False)
        if skip_monitoring and self.gate.validation_type == "monitoring":
            return True, "Monitoring gates disabled in context"

        return False, ""

    async def execute_with_timing(
        self, context: dict[str, Any]
    ) -> ModelQualityGateResult:
        """
        Execute validation with automatic timing, error handling, and event publishing.

        Wraps the validate() method to:
        - Measure execution time
        - Handle exceptions gracefully
        - Ensure result is properly formed
        - Publish quality gate event to Kafka

        Args:
            context: Validation context (should include correlation_id)

        Returns:
            ModelQualityGateResult with timing information

        Example:
            result = await gate.execute_with_timing(context)
            print(f"Gate {gate.gate.name} took {result.execution_time_ms}ms")
        """
        start_time = datetime.now(UTC)
        correlation_id = context.get("correlation_id")

        try:
            # Execute validation
            result = await self.validate(context)

            # Calculate actual execution time
            end_time = datetime.now(UTC)
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            # Update result with actual timing
            result.execution_time_ms = execution_time_ms
            result.timestamp = end_time

            # Publish quality gate event (non-blocking)
            await self._publish_quality_gate_event(result, correlation_id)

            return result

        except Exception as e:
            # Validation raised an exception - treat as failure
            end_time = datetime.now(UTC)
            execution_time_ms = int((end_time - start_time).total_seconds() * 1000)

            result = ModelQualityGateResult(
                gate=self.gate,
                status="failed",
                execution_time_ms=execution_time_ms,
                message=f"Validation error: {str(e)}",
                metadata={
                    "error_type": type(e).__name__,
                    "error_details": str(e),
                },
                timestamp=end_time,
            )

            # Publish quality gate event (non-blocking)
            await self._publish_quality_gate_event(result, correlation_id)

            return result

    def create_skipped_result(
        self, reason: str, execution_time_ms: int = 0
    ) -> ModelQualityGateResult:
        """
        Create a result for a skipped gate.

        Args:
            reason: Human-readable reason for skipping
            execution_time_ms: Optional execution time (defaults to 0)

        Returns:
            ModelQualityGateResult with skipped status
        """
        return ModelQualityGateResult(
            gate=self.gate,
            status="skipped",
            execution_time_ms=execution_time_ms,
            message=f"Gate skipped: {reason}",
            metadata={"skip_reason": reason},
        )

    @staticmethod
    def _get_gate_id(gate: EnumQualityGate) -> str:
        """
        Extract gate ID from enum value.

        Converts internal enum value (e.g., "sv_001_input_validation")
        to gate ID format (e.g., "SV-001").

        Args:
            gate: Quality gate enum

        Returns:
            Gate ID in format XX-NNN
        """
        # Extract prefix and number from value like "sv_001_input_validation"
        parts = gate.value.split("_")
        if len(parts) >= 2:
            prefix = parts[0].upper()  # sv -> SV
            number = parts[1]  # 001
            return f"{prefix}-{number}"  # SV-001
        return gate.value

    def get_info(self) -> dict[str, Any]:
        """
        Get metadata about this quality gate.

        Returns:
            Dictionary with gate properties and configuration
        """
        return {
            "gate": self.gate.value,
            "name": self.gate.gate_name,
            "description": self.gate.description,
            "category": self.gate.category,
            "execution_point": self.gate.execution_point,
            "validation_type": self.gate.validation_type,
            "automation_level": self.gate.automation_level,
            "performance_target_ms": self.gate.performance_target_ms,
            "is_mandatory": self.gate.is_mandatory,
            "dependencies": self.gate.dependencies,
        }

    async def _publish_quality_gate_event(
        self,
        result: ModelQualityGateResult,
        correlation_id: str | None = None,
    ) -> None:
        """
        Publish quality gate result event to Kafka.

        Publishes passed or failed events based on validation result.
        Non-blocking - errors are logged but don't fail validation.

        Args:
            result: Quality gate validation result
            correlation_id: Optional correlation ID for distributed tracing
        """
        try:
            # Normalize metadata upfront to prevent None access errors
            # This is a common case where metadata hasn't been initialized yet
            if result.metadata is None:
                result.metadata = {}

            # Extract score/threshold from metadata if available
            score = result.metadata.get("score")
            threshold = result.metadata.get("threshold")

            # Extract metrics from metadata
            metrics = {
                "execution_time_ms": result.execution_time_ms,
                "validation_type": result.gate.validation_type,
                "category": result.gate.category,
            }

            # Add any additional metadata
            if "metrics" in result.metadata:
                metrics.update(result.metadata["metrics"])

            if result.status == "passed":
                # Publish passed event
                await publish_quality_gate_passed(
                    gate_name=result.gate.value,
                    correlation_id=correlation_id,
                    score=score,
                    threshold=threshold,
                    metrics=metrics,
                )
            elif result.status == "failed":
                # Publish failed event
                failure_reasons = result.metadata.get(
                    "failure_reasons", [result.message]
                )
                recommendations = result.metadata.get("recommendations", [])

                # Ensure failure_reasons is a list
                if not isinstance(failure_reasons, list):
                    failure_reasons = [str(failure_reasons)]

                await publish_quality_gate_failed(
                    gate_name=result.gate.value,
                    correlation_id=correlation_id,
                    score=score or 0.0,
                    threshold=threshold or 1.0,
                    failure_reasons=failure_reasons,
                    recommendations=recommendations,
                )

        except Exception as e:
            # Log error but don't fail validation - observability shouldn't break execution
            logger.warning(
                f"Failed to publish quality gate event for {self.gate.value}: {e}"
            )

    def __repr__(self) -> str:
        """String representation of the validator."""
        return (
            f"{self.__class__.__name__}("
            f"gate={self.gate.value}, "
            f"category={self.gate.category})"
        )

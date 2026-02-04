"""
Transformation Validator
========================

Validates agent transformations to prevent invalid self-transformations
(polymorphic-agent -> polymorphic-agent) that indicate routing failures.

Problem:
- Many transformations are self-transformations (polly → polly)
- These often represent routing failures, not legitimate orchestration tasks
- Examples: "Frontend integration" should go to agent-frontend-developer

Solution:
- Validate self-transformations require detailed reasoning (min 50 chars)
- Warn on low confidence (<0.7) self-transformations
- Block specialized tasks from self-transforming
- Track metrics with outcome granularity for tuning

Target: Reduce executed self-transformation rate to <10%

Validator Outcomes (for metrics tuning):
- ALLOWED: Passed all checks
- WARNED: Passed with warnings (near threshold)
- BLOCKED: Failed validation

DESIGN RULE: Fail Closed on Validator Errors
=============================================
If the validator encounters an exception:
- FAIL CLOSED (block transformation)
- Emit explicit error event
- Log full stack trace
- Do NOT silently allow
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ValidatorOutcome(str, Enum):
    """
    Validator outcome for metrics tuning.

    These outcomes enable granular tracking:
    - Track raw self-transformation attempts (any outcome)
    - Track executed self-transformations (ALLOWED only)
    - Track near-misses (WARNED) for threshold tuning
    - Track blocked attempts (BLOCKED) to verify validation is working
    """

    ALLOWED = "allowed"  # Passed all checks
    WARNED = "warned"  # Passed with warnings (near threshold)
    BLOCKED = "blocked"  # Failed validation


@dataclass
class TransformationValidationResult:
    """
    Result of transformation validation.

    Attributes:
        outcome: ValidatorOutcome enum (ALLOWED/WARNED/BLOCKED)
        is_valid: Whether transformation is valid (ALLOWED or WARNED)
        error_message: Error message if blocked
        warning_message: Warning message (optional)
        metrics: Metrics dict for monitoring and tuning
    """

    outcome: ValidatorOutcome
    is_valid: bool
    error_message: str = ""
    warning_message: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allowed(
        cls,
        metrics: dict[str, Any] | None = None,
    ) -> "TransformationValidationResult":
        """Create an ALLOWED result."""
        return cls(
            outcome=ValidatorOutcome.ALLOWED,
            is_valid=True,
            metrics=metrics or {},
        )

    @classmethod
    def warned(
        cls,
        warning_message: str,
        metrics: dict[str, Any] | None = None,
    ) -> "TransformationValidationResult":
        """Create a WARNED result."""
        return cls(
            outcome=ValidatorOutcome.WARNED,
            is_valid=True,
            warning_message=warning_message,
            metrics=metrics or {},
        )

    @classmethod
    def blocked(
        cls,
        error_message: str,
        metrics: dict[str, Any] | None = None,
    ) -> "TransformationValidationResult":
        """Create a BLOCKED result."""
        return cls(
            outcome=ValidatorOutcome.BLOCKED,
            is_valid=False,
            error_message=error_message,
            metrics=metrics or {},
        )


class TransformationValidator:
    """
    Validates agent transformations to prevent invalid self-transformations.

    Usage:
        validator = TransformationValidator()
        result = validator.validate(
            from_agent="polymorphic-agent",
            to_agent="polymorphic-agent",
            reason="Multi-agent orchestration for complex workflow",
            confidence=0.85,
            user_request="orchestrate parallel execution"
        )

        if not result.is_valid:
            # Block the transformation
            raise ValueError(result.error_message)

        if result.warning_message:
            logger.warning(f"Transformation warning: {result.warning_message}")

        # result.outcome is ValidatorOutcome.ALLOWED, WARNED, or BLOCKED
        # result.metrics contains detailed tracking data
    """

    # Orchestration keywords that indicate legitimate self-transformation
    ORCHESTRATION_KEYWORDS = frozenset([
        "orchestrate",
        "coordinate",
        "workflow",
        "multi-agent",
        "parallel",
        "sequential",
        "batch",
        "pipeline",
        "dispatch",
        "polly",
        "poly",
    ])

    # Specialized task keywords that should route to specialized agents
    # NOTE: Avoid overly broad terms (e.g., "python", "sql") that appear in
    # general questions. Focus on task-oriented phrases that clearly indicate
    # specialized work requiring a domain expert.
    SPECIALIZED_KEYWORDS = frozenset([
        "api design",
        "api endpoint",
        "frontend component",
        "frontend integration",
        "backend service",
        "database schema",
        "database migration",
        "unit test",
        "integration test",
        "debug issue",
        "debug error",
        "performance optimization",
        "security audit",
        "security vulnerability",
        "deploy to",
        "deployment pipeline",
        "ui component",
        "ux design",
        "react component",
        "vue component",
        "angular component",
    ])

    def __init__(
        self,
        min_reason_length: int = 50,
        min_confidence: float = 0.7,
    ) -> None:
        """
        Initialize validator.

        Args:
            min_reason_length: Minimum reasoning length for self-transformations
            min_confidence: Minimum confidence threshold for warnings
        """
        self.min_reason_length = min_reason_length
        self.min_confidence = min_confidence

    def validate(
        self,
        from_agent: str,
        to_agent: str,
        reason: str,
        confidence: float | None = None,
        user_request: str | None = None,
    ) -> TransformationValidationResult:
        """
        Validate agent transformation.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            reason: Transformation reason/description
            confidence: Routing confidence score (0.0-1.0)
            user_request: Original user request (optional)

        Returns:
            TransformationValidationResult with validation outcome
        """
        # Only validate self-transformations (polly → polly)
        is_self_transformation = self._is_self_transformation(from_agent, to_agent)

        if not is_self_transformation:
            # Non-self transformations are always allowed
            return TransformationValidationResult.allowed(
                metrics={
                    "transformation_type": "specialized",
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "outcome": ValidatorOutcome.ALLOWED.value,
                },
            )

        # Initialize metrics for self-transformation
        metrics: dict[str, Any] = {
            "transformation_type": "self",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason_length": len(reason) if reason else 0,
            "confidence": confidence,
        }

        # Check if reasoning is provided and sufficient
        if not reason or len(reason) < self.min_reason_length:
            metrics["outcome"] = ValidatorOutcome.BLOCKED.value
            metrics["block_reason"] = "insufficient_reasoning"
            return TransformationValidationResult.blocked(
                error_message=(
                    f"Self-transformation requires detailed reasoning "
                    f"(min {self.min_reason_length} chars). "
                    f"Most tasks should route to specialized agents. "
                    f"Got: {len(reason) if reason else 0} chars"
                ),
                metrics=metrics,
            )

        # Check if this is a legitimate orchestration task
        text_to_check = user_request or reason
        is_orchestration_task = self._is_orchestration_task(text_to_check)
        is_specialized_task = self._is_specialized_task(text_to_check)

        metrics["is_orchestration_task"] = is_orchestration_task
        metrics["is_specialized_task"] = is_specialized_task

        # Block specialized tasks with low confidence (routing failure indicator)
        if confidence is not None and confidence < self.min_confidence:
            if is_specialized_task and not is_orchestration_task:
                metrics["outcome"] = ValidatorOutcome.BLOCKED.value
                metrics["block_reason"] = "specialized_task_low_confidence"
                return TransformationValidationResult.blocked(
                    error_message=(
                        f"Self-transformation blocked: Low confidence ({confidence:.2%}) "
                        f"for specialized task. Expected specialized agent routing. "
                        f"Reason: {reason}"
                    ),
                    metrics=metrics,
                )

            # Low confidence but orchestration task - warn but allow
            metrics["outcome"] = ValidatorOutcome.WARNED.value
            return TransformationValidationResult.warned(
                warning_message=(
                    f"Low confidence ({confidence:.2%}) self-transformation detected. "
                    f"This may indicate routing failure. Reason: {reason}"
                ),
                metrics=metrics,
            )

        # Passed all checks
        metrics["outcome"] = ValidatorOutcome.ALLOWED.value
        return TransformationValidationResult.allowed(metrics=metrics)

    def _is_self_transformation(self, from_agent: str, to_agent: str) -> bool:
        """Check if this is a self-transformation (polly → polly)."""
        polly_names = {"polymorphic-agent", "polly", "poly"}
        from_is_polly = from_agent.lower() in polly_names
        to_is_polly = to_agent.lower() in polly_names
        return from_is_polly and to_is_polly

    def _is_orchestration_task(self, text: str) -> bool:
        """Check if text contains orchestration keywords."""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.ORCHESTRATION_KEYWORDS)

    def _is_specialized_task(self, text: str) -> bool:
        """Check if text contains specialized task keywords."""
        if not text:
            return False
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.SPECIALIZED_KEYWORDS)


# Convenience function for quick validation
def validate_transformation(
    from_agent: str,
    to_agent: str,
    reason: str,
    confidence: float | None = None,
    user_request: str | None = None,
) -> TransformationValidationResult:
    """
    Convenience function for quick transformation validation.

    Args:
        from_agent: Source agent name
        to_agent: Target agent name
        reason: Transformation reason/description
        confidence: Routing confidence score (0.0-1.0)
        user_request: Original user request (optional)

    Returns:
        TransformationValidationResult with validation outcome
    """
    validator = TransformationValidator()
    return validator.validate(from_agent, to_agent, reason, confidence, user_request)


if __name__ == "__main__":
    # Test cases
    print("Testing TransformationValidator...")
    print()

    # Test 1: Valid self-transformation with orchestration
    print("Test 1: Valid self-transformation (orchestration)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="Multi-agent orchestration for complex workflow with parallel execution of 4 specialized agents",
        confidence=0.85,
        user_request="orchestrate parallel execution of API, frontend, and database work",
    )
    print(f"  Outcome: {result.outcome.value}")
    print(f"  Valid: {result.is_valid}")
    assert result.outcome == ValidatorOutcome.ALLOWED
    print()

    # Test 2: Invalid self-transformation (short reason)
    print("Test 2: Invalid self-transformation (short reason)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="General task",
        confidence=0.65,
    )
    print(f"  Outcome: {result.outcome.value}")
    print(f"  Valid: {result.is_valid}")
    print(f"  Error: {result.error_message[:80]}...")
    assert result.outcome == ValidatorOutcome.BLOCKED
    print()

    # Test 3: Invalid self-transformation (specialized task, low confidence)
    print("Test 3: Invalid self-transformation (specialized task, low confidence)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="Frontend integration with API endpoints and database connections",
        confidence=0.55,
        user_request="build a frontend component for the dashboard",
    )
    print(f"  Outcome: {result.outcome.value}")
    print(f"  Valid: {result.is_valid}")
    print(f"  Error: {result.error_message[:80]}...")
    assert result.outcome == ValidatorOutcome.BLOCKED
    print()

    # Test 4: Valid specialized transformation
    print("Test 4: Valid specialized transformation")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="agent-frontend-developer",
        reason="Frontend development task",
        confidence=0.92,
    )
    print(f"  Outcome: {result.outcome.value}")
    print(f"  Valid: {result.is_valid}")
    assert result.outcome == ValidatorOutcome.ALLOWED
    print()

    # Test 5: Self-transformation with warning (low confidence, orchestration)
    print("Test 5: Self-transformation with warning (low confidence, orchestration)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="Orchestrate workflow with multiple agents for complex multi-step execution",
        confidence=0.65,
        user_request="orchestrate multi-agent workflow",
    )
    print(f"  Outcome: {result.outcome.value}")
    print(f"  Valid: {result.is_valid}")
    print(f"  Warning: {result.warning_message[:80]}...")
    assert result.outcome == ValidatorOutcome.WARNED
    print()

    print("All tests passed!")

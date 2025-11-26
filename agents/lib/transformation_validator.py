"""
Transformation Validator
========================

Validates agent transformations to prevent invalid self-transformations
(polymorphic-agent -> polymorphic-agent) that indicate routing failures.

Problem:
- 45.5% of transformations are self-transformations (15/33 cases)
- Many are routing failures, not legitimate orchestration tasks
- Examples: "Frontend integration" should go to agent-frontend-developer

Solution:
- Validate self-transformations require detailed reasoning (min 50 chars)
- Warn on low confidence (<0.7) self-transformations
- Block specialized tasks from self-transforming
- Track metrics for monitoring

Target: Reduce self-transformation rate from 45.5% to <10%
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TransformationValidationResult:
    """
    Result of transformation validation.

    Attributes:
        is_valid: Whether transformation is valid
        error_message: Error message if invalid
        warning_message: Warning message (optional)
        metrics: Metrics dict for monitoring
    """

    is_valid: bool
    error_message: str = ""
    warning_message: str = ""
    metrics: dict = field(default_factory=dict)


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
            raise ValueError(result.error_message)

        if result.warning_message:
            print(f"WARNING: {result.warning_message}")
    """

    # Orchestration keywords that indicate legitimate self-transformation
    ORCHESTRATION_KEYWORDS = [
        "orchestrate",
        "coordinate",
        "workflow",
        "multi-agent",
        "parallel",
        "sequential",
        "batch",
        "pipeline",
    ]

    # Specialized task keywords that should route to specialized agents
    SPECIALIZED_KEYWORDS = [
        "api",
        "frontend",
        "backend",
        "database",
        "testing",
        "debug",
        "performance",
        "security",
        "deployment",
        "documentation",
        "ui",
        "ux",
        "css",
        "html",
        "javascript",
        "python",
        "sql",
    ]

    def __init__(self, min_reason_length: int = 50, min_confidence: float = 0.7):
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
        confidence: Optional[float] = None,
        user_request: Optional[str] = None,
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
        # Only validate self-transformations
        if from_agent != "polymorphic-agent" or to_agent != "polymorphic-agent":
            return TransformationValidationResult(
                is_valid=True,
                metrics={
                    "transformation_type": "specialized",
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                },
            )

        # Initialize metrics
        metrics = {
            "transformation_type": "self",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "reason_length": len(reason) if reason else 0,
            "confidence": confidence,
        }

        # Check if reasoning is provided and sufficient
        if not reason or len(reason) < self.min_reason_length:
            return TransformationValidationResult(
                is_valid=False,
                error_message=(
                    f"Self-transformation requires detailed reasoning "
                    f"(min {self.min_reason_length} chars). "
                    f"Most tasks should route to specialized agents. "
                    f"Got: {len(reason) if reason else 0} chars"
                ),
                metrics=metrics,
            )

        # Check if this is a legitimate orchestration task
        is_orchestration_task = self._is_orchestration_task(user_request or reason)
        metrics["is_orchestration_task"] = is_orchestration_task

        # Check if this is a specialized task
        is_specialized_task = self._is_specialized_task(user_request or reason)
        metrics["is_specialized_task"] = is_specialized_task

        # Build warning if applicable
        warning = ""
        if confidence is not None and confidence < self.min_confidence:
            warning = (
                f"Low confidence ({confidence:.2%}) self-transformation detected. "
                f"This may indicate routing failure. "
            )

            # Block specialized tasks with low confidence
            if is_specialized_task and not is_orchestration_task:
                return TransformationValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Self-transformation blocked: Low confidence ({confidence:.2%}) "
                        f"for specialized task. Expected specialized agent routing. "
                        f"Reason: {reason}"
                    ),
                    metrics=metrics,
                )

            warning += f"Reason: {reason}"

        return TransformationValidationResult(
            is_valid=True,
            warning_message=warning,
            metrics=metrics,
        )

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
    confidence: Optional[float] = None,
    user_request: Optional[str] = None,
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
    print(f"  Valid: {result.is_valid}")
    print(f"  Metrics: {result.metrics}")
    print()

    # Test 2: Invalid self-transformation (short reason)
    print("Test 2: Invalid self-transformation (short reason)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="General task",
        confidence=0.65,
    )
    print(f"  Valid: {result.is_valid}")
    print(f"  Error: {result.error_message}")
    print()

    # Test 3: Invalid self-transformation (specialized task, low confidence)
    print("Test 3: Invalid self-transformation (specialized task, low confidence)")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="polymorphic-agent",
        reason="Frontend integration with API endpoints and database connections",
        confidence=0.55,
        user_request="integrate frontend with API",
    )
    print(f"  Valid: {result.is_valid}")
    print(f"  Error: {result.error_message}")
    print(f"  Metrics: {result.metrics}")
    print()

    # Test 4: Valid specialized transformation
    print("Test 4: Valid specialized transformation")
    result = validate_transformation(
        from_agent="polymorphic-agent",
        to_agent="agent-frontend-developer",
        reason="Frontend development task",
        confidence=0.92,
    )
    print(f"  Valid: {result.is_valid}")
    print(f"  Metrics: {result.metrics}")
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
    print(f"  Valid: {result.is_valid}")
    print(f"  Warning: {result.warning_message}")
    print(f"  Metrics: {result.metrics}")
    print()

    print("All tests completed!")

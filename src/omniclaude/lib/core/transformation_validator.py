# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Transformation Validator -- Fail Closed.

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

Design Rule: Fail Closed
    If any internal error occurs during validation, this module returns
    is_valid=False (rejects the transformation) rather than allowing the
    transformation to proceed. This prevents routing failures from being
    masked by validator errors.

Target: Reduce self-transformation rate from 45.5% to <10%
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TransformationValidationResult:
    """Result of transformation validation.

    Attributes:
        is_valid: Whether transformation is valid.
        error_message: Error message if invalid.
        warning_message: Warning message (optional).
        metrics: Metrics dict for monitoring.
    """

    is_valid: bool
    error_message: str = ""
    warning_message: str = ""
    metrics: dict = field(default_factory=dict)


class TransformationValidator:
    """Validates agent transformations to prevent invalid self-transformations.

    Design Rule: Fail Closed
        If any internal error occurs during validation, the validate() method
        returns is_valid=False (rejects the transformation) rather than
        propagating the exception or allowing the transformation to proceed.
        This ensures that validator bugs never silently allow invalid
        transformations.

    Usage::

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
            logger.warning(result.warning_message)
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

    # Short keywords that need word-boundary matching to prevent false positives
    # (e.g., "capital" matching "api", "built" matching "ui", "xhtml" matching
    # "html").  Membership in this set determines boundary matching, not character
    # length.  Follows the same pattern as TaskClassifier._SHORT_KEYWORDS.
    _SHORT_KEYWORDS = frozenset({"api", "ui", "ux", "css", "html", "sql"})

    def __init__(self, min_reason_length: int = 50, min_confidence: float = 0.7):
        """Initialize validator.

        Args:
            min_reason_length: Minimum reasoning length for self-transformations.
            min_confidence: Minimum confidence threshold for warnings.
        """
        self.min_reason_length = min_reason_length
        self.min_confidence = min_confidence

    def validate(
        self,
        from_agent: str,
        to_agent: str,
        reason: str | None,
        confidence: float | None = None,
        user_request: str | None = None,
    ) -> TransformationValidationResult:
        """Validate agent transformation.

        Fail Closed: Any internal error during validation results in
        is_valid=False. The transformation is rejected, not allowed.
        This ensures validator bugs never silently permit invalid
        transformations.

        Args:
            from_agent: Source agent name.
            to_agent: Target agent name.
            reason: Transformation reason/description.
            confidence: Routing confidence score (0.0-1.0).
            user_request: Original user request (optional).

        Returns:
            TransformationValidationResult with validation outcome.
            On internal errors, returns is_valid=False with error details.
        """
        try:
            return self._validate_internal(
                from_agent=from_agent,
                to_agent=to_agent,
                reason=reason,
                confidence=confidence,
                user_request=user_request,
            )
        except Exception as exc:
            # Fail closed: internal errors reject the transformation
            logger.error(
                "Transformation validator internal error (fail closed): %s", exc
            )
            return TransformationValidationResult(
                is_valid=False,
                error_message=(
                    f"Validation failed closed due to internal error: {exc}"
                ),
                metrics={
                    "transformation_type": "error",
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "internal_error": str(exc),
                    "internal_error_type": type(exc).__name__,
                },
            )

    def _validate_internal(
        self,
        from_agent: str,
        to_agent: str,
        reason: str | None,
        confidence: float | None = None,
        user_request: str | None = None,
    ) -> TransformationValidationResult:
        """Internal validation logic, separated for fail-closed wrapping.

        Args:
            from_agent: Source agent name.
            to_agent: Target agent name.
            reason: Transformation reason/description.
            confidence: Routing confidence score (0.0-1.0).
            user_request: Original user request (optional).

        Returns:
            TransformationValidationResult with validation outcome.
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

    def _keyword_in_text(self, keyword: str, text: str) -> bool:
        """Check if keyword appears in text, using word boundaries for short keywords.

        Keywords in ``_SHORT_KEYWORDS`` (e.g., "api", "ui", "sql", "html") use
        regex word-boundary matching to prevent false positives (e.g., "capital"
        matching "api").  Follows the same pattern as
        TaskClassifier._keyword_in_text.
        """
        if keyword in self._SHORT_KEYWORDS:
            pattern = rf"\b{re.escape(keyword)}\b"
            return bool(re.search(pattern, text))
        return keyword in text

    def _is_orchestration_task(self, text: str) -> bool:
        """Check if text contains orchestration keywords."""
        if not text:
            return False

        text_lower = text.lower()
        return any(
            self._keyword_in_text(keyword, text_lower)
            for keyword in self.ORCHESTRATION_KEYWORDS
        )

    def _is_specialized_task(self, text: str) -> bool:
        """Check if text contains specialized task keywords."""
        if not text:
            return False

        text_lower = text.lower()
        return any(
            self._keyword_in_text(keyword, text_lower)
            for keyword in self.SPECIALIZED_KEYWORDS
        )


# Convenience function for quick validation
def validate_transformation(
    from_agent: str,
    to_agent: str,
    reason: str | None,
    confidence: float | None = None,
    user_request: str | None = None,
) -> TransformationValidationResult:
    """Convenience function for quick transformation validation.

    Fail Closed: Inherits fail-closed behavior from TransformationValidator.
    Any internal error returns is_valid=False.

    Args:
        from_agent: Source agent name.
        to_agent: Target agent name.
        reason: Transformation reason/description.
        confidence: Routing confidence score (0.0-1.0).
        user_request: Original user request (optional).

    Returns:
        TransformationValidationResult with validation outcome.
    """
    validator = TransformationValidator()
    return validator.validate(from_agent, to_agent, reason, confidence, user_request)

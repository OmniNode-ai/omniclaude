#!/usr/bin/env python3
"""
Model: Routing Error Payload

Pydantic model for agent routing error payloads.
Used when routing fails or encounters errors.

Event Flow:
    agent-router-service → agent.routing.failed.v1 → Agent

Examples:
    Registry load failure:
    ```python
    error = ModelRoutingError(
        correlation_id="abc-123",
        error_code="REGISTRY_LOAD_FAILED",
        error_message="Failed to load agent registry: file not found",
        fallback_recommendation=ModelFallbackRecommendation(
            agent_name="polymorphic-agent",
            reason="Fallback to polymorphic agent due to routing failure"
        )
    )
    ```

    Timeout error:
    ```python
    error = ModelRoutingError(
        correlation_id="abc-123",
        error_code="ROUTING_TIMEOUT",
        error_message="Routing decision exceeded 5000ms timeout",
        retry_after_ms=1000
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py (error handling pattern)
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelFallbackRecommendation(BaseModel):
    """
    Fallback agent recommendation when routing fails.

    Attributes:
        agent_name: Fallback agent identifier (usually "polymorphic-agent")
        reason: Reason for fallback
        confidence: Optional confidence score (default: 0.5 for fallback)
    """

    agent_name: str = Field(
        ...,
        min_length=1,
        description="Fallback agent identifier (usually 'polymorphic-agent')",
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Reason for fallback",
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score for fallback (default: 0.5)",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "agent_name": "polymorphic-agent",
                "reason": "Fallback to polymorphic agent due to routing service failure",
                "confidence": 0.5,
            }
        }
    )


class ModelRoutingError(BaseModel):
    """
    Agent routing error payload.

    This is the payload inside the event envelope when routing fails.

    Error Codes:
        - REGISTRY_LOAD_FAILED: Failed to load agent registry
        - REGISTRY_PARSE_FAILED: Failed to parse agent YAML definitions
        - ROUTING_TIMEOUT: Routing decision exceeded timeout
        - NO_AGENTS_AVAILABLE: No agents match the request criteria
        - INVALID_REQUEST: Request validation failed
        - SERVICE_UNAVAILABLE: Routing service temporarily unavailable
        - INTERNAL_ERROR: Unexpected internal error

    Attributes:
        correlation_id: Unique request identifier matching the request
        error_code: Standard error code (see Error Codes above)
        error_message: Human-readable error message
        error_details: Optional additional error details (stack trace, context)
        fallback_recommendation: Optional fallback agent recommendation
        retry_after_ms: Optional milliseconds to wait before retry
        timestamp: Optional error timestamp (ISO 8601)

    Validation:
        - correlation_id: Must be valid UUID string
        - error_code: Must be non-empty
        - error_message: Must be non-empty

    Examples:
        ```python
        # Registry load failure with fallback
        error = ModelRoutingError(
            correlation_id="abc-123",
            error_code="REGISTRY_LOAD_FAILED",
            error_message="Failed to load agent registry: /path/to/registry.yaml not found",
            error_details={
                "file_path": "/path/to/registry.yaml",
                "errno": 2,
                "exception_type": "FileNotFoundError"
            },
            fallback_recommendation=ModelFallbackRecommendation(
                agent_name="polymorphic-agent",
                reason="Using polymorphic agent as fallback due to registry failure"
            )
        )

        # Timeout error with retry
        error = ModelRoutingError(
            correlation_id="abc-123",
            error_code="ROUTING_TIMEOUT",
            error_message="Routing decision exceeded 5000ms timeout",
            retry_after_ms=1000
        )

        # No agents available
        error = ModelRoutingError(
            correlation_id="abc-123",
            error_code="NO_AGENTS_AVAILABLE",
            error_message="No agents match request criteria (min_confidence: 0.9)",
            error_details={
                "min_confidence": 0.9,
                "highest_confidence": 0.65,
                "candidates_evaluated": 15
            },
            fallback_recommendation=ModelFallbackRecommendation(
                agent_name="polymorphic-agent",
                reason="No agents met minimum confidence threshold"
            )
        )
        ```
    """

    correlation_id: str = Field(
        ...,
        description="Unique request identifier matching the request (UUID string)",
    )
    error_code: str = Field(
        ...,
        min_length=1,
        description="Standard error code (e.g., REGISTRY_LOAD_FAILED, ROUTING_TIMEOUT)",
    )
    error_message: str = Field(
        ...,
        min_length=1,
        description="Human-readable error message",
    )
    error_details: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional additional error details (stack trace, context)",
    )
    fallback_recommendation: Optional[ModelFallbackRecommendation] = Field(
        default=None,
        description="Optional fallback agent recommendation",
    )
    retry_after_ms: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional milliseconds to wait before retry",
    )
    timestamp: Optional[str] = Field(
        default=None,
        description="Optional error timestamp (ISO 8601 format)",
    )

    @field_validator("error_code")
    @classmethod
    def validate_error_code(cls, v: str) -> str:
        """Validate error_code is in uppercase snake_case."""
        if not v.isupper() or " " in v:
            raise ValueError(
                "error_code must be uppercase snake_case (e.g., REGISTRY_LOAD_FAILED)"
            )
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "correlation_id": "a2f33abd-34c2-4d63-bfe7-2cb14ded13fd",
                "error_code": "REGISTRY_LOAD_FAILED",
                "error_message": "Failed to load agent registry: /Users/jonah/.claude/agents/omniclaude/agent-registry.yaml not found",
                "error_details": {
                    "file_path": "/Users/jonah/.claude/agents/omniclaude/agent-registry.yaml",
                    "errno": 2,
                    "exception_type": "FileNotFoundError",
                    "stack_trace": "Traceback (most recent call last)...",
                },
                "fallback_recommendation": {
                    "agent_name": "polymorphic-agent",
                    "reason": "Fallback to polymorphic agent due to routing service failure",
                    "confidence": 0.5,
                },
                "retry_after_ms": 1000,
                "timestamp": "2025-10-30T14:30:00.100Z",
            }
        }
    )


# Error code constants for convenience
class ErrorCodes:
    """Standard error codes for routing failures."""

    REGISTRY_LOAD_FAILED = "REGISTRY_LOAD_FAILED"
    REGISTRY_PARSE_FAILED = "REGISTRY_PARSE_FAILED"
    ROUTING_TIMEOUT = "ROUTING_TIMEOUT"
    NO_AGENTS_AVAILABLE = "NO_AGENTS_AVAILABLE"
    INVALID_REQUEST = "INVALID_REQUEST"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


__all__ = [
    "ModelRoutingError",
    "ModelFallbackRecommendation",
    "ErrorCodes",
]

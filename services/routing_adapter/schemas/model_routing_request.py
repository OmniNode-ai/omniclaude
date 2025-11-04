#!/usr/bin/env python3
"""
Model: Routing Request Payload

Pydantic model for agent routing request payloads.
Used when agents request routing decisions via Kafka events.

Event Flow:
    Agent → agent.routing.requested.v1 → agent-router-service

Examples:
    Basic routing request:
    ```python
    request = ModelRoutingRequest(
        user_request="optimize my database queries",
        correlation_id="abc-123",
    )
    ```

    With context:
    ```python
    request = ModelRoutingRequest(
        user_request="optimize my database queries",
        correlation_id="abc-123",
        context={
            "domain": "database_optimization",
            "previous_agent": "agent-api-architect",
            "current_file": "api/database.py"
        },
        options={
            "max_recommendations": 3,
            "min_confidence": 0.7
        }
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py (proven pattern)
"""

from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelRoutingOptions(BaseModel):
    """
    Optional routing configuration.

    Attributes:
        max_recommendations: Maximum number of agent recommendations (default: 5)
        min_confidence: Minimum confidence threshold 0.0-1.0 (default: 0.6)
        routing_strategy: Strategy name (default: "enhanced_fuzzy_matching")
        timeout_ms: Response timeout in milliseconds (default: 5000)
    """

    max_recommendations: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum number of agent recommendations",
    )
    min_confidence: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    )
    routing_strategy: str = Field(
        default="enhanced_fuzzy_matching",
        description="Routing strategy name",
    )
    timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=30000,
        description="Response timeout in milliseconds",
    )


class ModelRoutingRequest(BaseModel):
    """
    Agent routing request payload.

    This is the payload inside the event envelope when requesting routing decisions.

    Attributes:
        user_request: User's input text requiring agent routing
        correlation_id: Unique request identifier for tracing
        context: Optional execution context (domain, previous_agent, current_file)
        options: Optional routing configuration
        timeout_ms: Response timeout in milliseconds (default: 5000)

    Validation:
        - user_request: Must be non-empty string
        - correlation_id: Must be valid UUID string
        - timeout_ms: Between 1000-30000ms

    Examples:
        ```python
        # Minimal request
        request = ModelRoutingRequest(
            user_request="optimize my API performance",
            correlation_id="abc-123"
        )

        # Full request with context
        request = ModelRoutingRequest(
            user_request="optimize my API performance",
            correlation_id="abc-123",
            context={
                "domain": "api_development",
                "previous_agent": "agent-frontend-developer",
                "current_file": "api/endpoints.py"
            },
            options=ModelRoutingOptions(
                max_recommendations=3,
                min_confidence=0.7,
                routing_strategy="enhanced_fuzzy_matching"
            ),
            timeout_ms=5000
        )
        ```
    """

    user_request: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User's input text requiring agent routing",
    )
    correlation_id: str = Field(
        ...,
        description="Unique request identifier for tracing (UUID string)",
    )
    context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional execution context (domain, previous_agent, current_file)",
    )
    options: ModelRoutingOptions = Field(
        default_factory=ModelRoutingOptions,
        description="Routing configuration options",
    )
    timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=30000,
        description="Response timeout in milliseconds",
    )

    @field_validator("correlation_id")
    @classmethod
    def validate_correlation_id(cls, v: str) -> str:
        """Validate correlation_id is a valid UUID string."""
        try:
            UUID(v)
        except ValueError as e:
            raise ValueError(f"correlation_id must be valid UUID string: {e}") from e
        return v

    @field_validator("user_request")
    @classmethod
    def validate_user_request(cls, v: str) -> str:
        """Validate user_request is non-empty after stripping whitespace."""
        if not v.strip():
            raise ValueError("user_request must not be empty or whitespace-only")
        return v.strip()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_request": "optimize my database queries",
                "correlation_id": "a2f33abd-34c2-4d63-bfe7-2cb14ded13fd",
                "context": {
                    "domain": "database_optimization",
                    "previous_agent": "agent-api-architect",
                    "current_file": "api/database.py",
                },
                "options": {
                    "max_recommendations": 3,
                    "min_confidence": 0.7,
                    "routing_strategy": "enhanced_fuzzy_matching",
                    "timeout_ms": 5000,
                },
                "timeout_ms": 5000,
            }
        }
    )


__all__ = [
    "ModelRoutingRequest",
    "ModelRoutingOptions",
]

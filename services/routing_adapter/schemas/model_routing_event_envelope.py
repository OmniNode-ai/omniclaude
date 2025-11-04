#!/usr/bin/env python3
"""
Model: Routing Event Envelope

Pydantic model for wrapping routing event payloads with metadata.
Follows the ModelEventEnvelope pattern from database events.

Event Flow:
    All routing events are wrapped in this envelope:
    - agent.routing.requested.v1 (wraps ModelRoutingRequest)
    - agent.routing.completed.v1 (wraps ModelRoutingResponse)
    - agent.routing.failed.v1 (wraps ModelRoutingError)

Examples:
    Routing request envelope:
    ```python
    envelope = ModelRoutingEventEnvelope(
        event_id="def-456",
        event_type="AGENT_ROUTING_REQUESTED",
        correlation_id="abc-123",
        timestamp="2025-10-30T14:30:00Z",
        service="polymorphic-agent",
        payload=ModelRoutingRequest(
            user_request="optimize my database queries",
            correlation_id="abc-123"
        )
    )
    ```

    Routing response envelope:
    ```python
    envelope = ModelRoutingEventEnvelope(
        event_id="ghi-789",
        event_type="AGENT_ROUTING_COMPLETED",
        correlation_id="abc-123",
        timestamp="2025-10-30T14:30:00.045Z",
        service="agent-router-service",
        payload=ModelRoutingResponse(
            correlation_id="abc-123",
            recommendations=[...]
        )
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py (ModelEventEnvelope pattern)
"""

from datetime import UTC, datetime
from typing import Any, Dict, Generic, TypeVar, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .model_routing_error import ModelRoutingError
from .model_routing_request import ModelRoutingRequest
from .model_routing_response import ModelRoutingResponse

# Generic payload type
TPayload = TypeVar(
    "TPayload",
    ModelRoutingRequest,
    ModelRoutingResponse,
    ModelRoutingError,
    Dict[str, Any],
)


class ModelRoutingEventEnvelope(BaseModel, Generic[TPayload]):
    """
    Event envelope for routing events.

    Wraps routing payloads with metadata for Kafka event bus.
    Follows the same pattern as database events for consistency.

    Envelope Structure:
        ```
        {
          "event_id": "unique-event-id",
          "event_type": "AGENT_ROUTING_REQUESTED|COMPLETED|FAILED",
          "correlation_id": "unique-request-id",
          "timestamp": "2025-10-30T14:30:00Z",
          "service": "polymorphic-agent|agent-router-service",
          "payload": { ... routing request/response/error ... }
        }
        ```

    Attributes:
        event_id: Unique event identifier (UUID string, auto-generated)
        event_type: Event type (AGENT_ROUTING_REQUESTED|COMPLETED|FAILED)
        correlation_id: Request correlation ID for tracing
        timestamp: Event timestamp (ISO 8601, auto-generated)
        service: Source service name
        payload: Event payload (request/response/error)
        version: Optional event schema version (default: "v1")

    Validation:
        - event_id: Must be valid UUID string
        - correlation_id: Must be valid UUID string
        - event_type: Must be valid routing event type
        - timestamp: Must be valid ISO 8601 timestamp

    Examples:
        ```python
        # Request envelope (auto-generates event_id and timestamp)
        envelope = ModelRoutingEventEnvelope(
            event_type="AGENT_ROUTING_REQUESTED",
            correlation_id="abc-123",
            service="polymorphic-agent",
            payload=ModelRoutingRequest(
                user_request="optimize my database queries",
                correlation_id="abc-123"
            )
        )

        # Response envelope
        envelope = ModelRoutingEventEnvelope(
            event_type="AGENT_ROUTING_COMPLETED",
            correlation_id="abc-123",
            service="agent-router-service",
            payload=ModelRoutingResponse(
                correlation_id="abc-123",
                recommendations=[...]
            )
        )

        # Error envelope
        envelope = ModelRoutingEventEnvelope(
            event_type="AGENT_ROUTING_FAILED",
            correlation_id="abc-123",
            service="agent-router-service",
            payload=ModelRoutingError(
                correlation_id="abc-123",
                error_code="ROUTING_TIMEOUT",
                error_message="Routing decision exceeded timeout"
            )
        )

        # Serialize to JSON for Kafka
        event_json = envelope.model_dump_json()
        ```
    """

    event_id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique event identifier (UUID string, auto-generated)",
    )
    event_type: str = Field(
        ...,
        description="Event type (AGENT_ROUTING_REQUESTED|COMPLETED|FAILED)",
    )
    correlation_id: str = Field(
        ...,
        description="Request correlation ID for tracing (UUID string)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Event timestamp (ISO 8601, auto-generated)",
    )
    service: str = Field(
        ...,
        min_length=1,
        description="Source service name",
    )
    payload: Union[
        ModelRoutingRequest, ModelRoutingResponse, ModelRoutingError, Dict[str, Any]
    ] = Field(
        ...,
        description="Event payload (request/response/error)",
    )
    version: str = Field(
        default="v1",
        description="Event schema version",
    )

    @field_validator("event_id", "correlation_id")
    @classmethod
    def validate_uuid(cls, v: str, info) -> str:
        """Validate UUID fields are valid UUID strings."""
        try:
            UUID(v)
        except ValueError as e:
            raise ValueError(f"{info.field_name} must be valid UUID string: {e}") from e
        return v

    @field_validator("event_type")
    @classmethod
    def validate_event_type(cls, v: str) -> str:
        """Validate event_type is a valid routing event type."""
        valid_types = {
            "AGENT_ROUTING_REQUESTED",
            "AGENT_ROUTING_COMPLETED",
            "AGENT_ROUTING_FAILED",
        }
        if v not in valid_types:
            raise ValueError(f"event_type must be one of {valid_types}, got: {v}")
        return v

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        """Validate timestamp is valid ISO 8601 format."""
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"timestamp must be valid ISO 8601 format: {e}") from e
        return v

    @classmethod
    def create_request(
        cls,
        user_request: str,
        correlation_id: str,
        service: str = "polymorphic-agent",
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingRequest]":
        """
        Convenience factory for creating request envelopes.

        Args:
            user_request: User's input text
            correlation_id: Request correlation ID
            service: Source service name (default: "polymorphic-agent")
            **kwargs: Additional fields for ModelRoutingRequest

        Returns:
            Request envelope with auto-generated event_id and timestamp

        Example:
            ```python
            envelope = ModelRoutingEventEnvelope.create_request(
                user_request="optimize my database queries",
                correlation_id="abc-123",
                context={"domain": "database_optimization"}
            )
            ```
        """
        payload = ModelRoutingRequest(
            user_request=user_request, correlation_id=correlation_id, **kwargs
        )
        return cls(
            event_type="AGENT_ROUTING_REQUESTED",
            correlation_id=correlation_id,
            service=service,
            payload=payload,
        )

    @classmethod
    def create_response(
        cls,
        correlation_id: str,
        recommendations: list,
        routing_metadata: dict,
        service: str = "agent-router-service",
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingResponse]":
        """
        Convenience factory for creating response envelopes.

        Args:
            correlation_id: Request correlation ID
            recommendations: List of agent recommendations
            routing_metadata: Routing metadata dictionary
            service: Source service name (default: "agent-router-service")
            **kwargs: Additional fields for ModelRoutingResponse

        Returns:
            Response envelope with auto-generated event_id and timestamp

        Example:
            ```python
            envelope = ModelRoutingEventEnvelope.create_response(
                correlation_id="abc-123",
                recommendations=[...],
                routing_metadata={
                    "routing_time_ms": 45,
                    "cache_hit": False,
                    "candidates_evaluated": 5,
                    "routing_strategy": "enhanced_fuzzy_matching"
                }
            )
            ```
        """
        from .model_routing_response import (
            ModelAgentRecommendation,
            ModelRoutingMetadata,
        )

        payload = ModelRoutingResponse(
            correlation_id=correlation_id,
            recommendations=[
                ModelAgentRecommendation(**rec) for rec in recommendations
            ],
            routing_metadata=ModelRoutingMetadata(**routing_metadata),
            **kwargs,
        )
        return cls(
            event_type="AGENT_ROUTING_COMPLETED",
            correlation_id=correlation_id,
            service=service,
            payload=payload,
        )

    @classmethod
    def create_error(
        cls,
        correlation_id: str,
        error_code: str,
        error_message: str,
        service: str = "agent-router-service",
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingError]":
        """
        Convenience factory for creating error envelopes.

        Args:
            correlation_id: Request correlation ID
            error_code: Standard error code
            error_message: Human-readable error message
            service: Source service name (default: "agent-router-service")
            **kwargs: Additional fields for ModelRoutingError

        Returns:
            Error envelope with auto-generated event_id and timestamp

        Example:
            ```python
            envelope = ModelRoutingEventEnvelope.create_error(
                correlation_id="abc-123",
                error_code="ROUTING_TIMEOUT",
                error_message="Routing decision exceeded 5000ms timeout",
                retry_after_ms=1000
            )
            ```
        """
        payload = ModelRoutingError(
            correlation_id=correlation_id,
            error_code=error_code,
            error_message=error_message,
            **kwargs,
        )
        return cls(
            event_type="AGENT_ROUTING_FAILED",
            correlation_id=correlation_id,
            service=service,
            payload=payload,
        )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "def-456",
                "event_type": "AGENT_ROUTING_REQUESTED",
                "correlation_id": "abc-123",
                "timestamp": "2025-10-30T14:30:00Z",
                "service": "polymorphic-agent",
                "payload": {
                    "user_request": "optimize my database queries",
                    "correlation_id": "abc-123",
                    "context": {"domain": "database_optimization"},
                    "options": {
                        "max_recommendations": 3,
                        "min_confidence": 0.7,
                        "routing_strategy": "enhanced_fuzzy_matching",
                        "timeout_ms": 5000,
                    },
                    "timeout_ms": 5000,
                },
                "version": "v1",
            }
        }
    )


__all__ = [
    "ModelRoutingEventEnvelope",
]

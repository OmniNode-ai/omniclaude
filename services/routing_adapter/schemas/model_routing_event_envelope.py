#!/usr/bin/env python3
"""
Model: Routing Event Envelope

Pydantic model for wrapping routing event payloads with metadata.
Follows the EVENT_BUS_INTEGRATION_GUIDE standard envelope format.

Event Flow:
    All routing events are wrapped in this envelope:
    - omninode.agent.routing.requested.v1 (wraps ModelRoutingRequest)
    - omninode.agent.routing.completed.v1 (wraps ModelRoutingResponse)
    - omninode.agent.routing.failed.v1 (wraps ModelRoutingError)

Event Naming Convention (per EVENT_BUS_INTEGRATION_GUIDE):
    Format: {tenant}.{domain}.{entity}.{action}.v{major}
    Examples:
    - omninode.agent.routing.requested.v1
    - omninode.agent.routing.completed.v1
    - omninode.agent.routing.failed.v1

Partition Key Policy:
    - Uses correlation_id as partition key
    - Cardinality: Medium (per request)
    - Ensures request→response ordering per workflow

Examples:
    Routing request envelope:
    ```python
    envelope = ModelRoutingEventEnvelope(
        event_id="def-456",
        event_type="omninode.agent.routing.requested.v1",
        correlation_id="abc-123",
        timestamp="2025-10-30T14:30:00Z",
        tenant_id="default",
        namespace="omninode",
        service="polymorphic-agent",
        causation_id=None,
        schema_ref="registry://omninode/agent/routing_requested/v1",
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
        event_type="omninode.agent.routing.completed.v1",
        correlation_id="abc-123",
        timestamp="2025-10-30T14:30:00.045Z",
        tenant_id="default",
        namespace="omninode",
        service="agent-router-service",
        causation_id="def-456",
        schema_ref="registry://omninode/agent/routing_completed/v1",
        payload=ModelRoutingResponse(
            correlation_id="abc-123",
            recommendations=[...]
        )
    )
    ```

Created: 2025-10-30
Updated: 2025-11-13 (aligned with EVENT_BUS_INTEGRATION_GUIDE)
Reference: EVENT_BUS_INTEGRATION_GUIDE.md (Event Schema Standard)
"""

from datetime import UTC, datetime
from typing import Any, Dict, Generic, Optional, TypeVar, Union
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
    Follows the EVENT_BUS_INTEGRATION_GUIDE standard envelope format.

    Envelope Structure (per EVENT_BUS_INTEGRATION_GUIDE):
        ```
        {
          "event_id": "uuid-v7",
          "event_type": "omninode.agent.routing.requested|completed|failed.v1",
          "correlation_id": "uuid-v7",
          "timestamp": "RFC3339",
          "tenant_id": "uuid",
          "namespace": "omninode",
          "service": "polymorphic-agent|agent-router-service",
          "causation_id": "uuid-v7",
          "schema_ref": "registry://omninode/agent/routing_*/v1",
          "payload": { ... routing request/response/error ... },
          "version": "v1"
        }
        ```

    Attributes:
        event_id: Unique event identifier (UUID string, auto-generated)
        event_type: Event type (omninode.agent.routing.requested|completed|failed.v1)
        correlation_id: Request correlation ID for tracing (UUID string)
        timestamp: Event timestamp (ISO 8601, auto-generated)
        tenant_id: Tenant identifier for multi-tenancy (default: "default")
        namespace: Event namespace (default: "omninode")
        service: Source service name
        causation_id: Causation event ID for event chains (optional)
        schema_ref: Schema registry reference
        payload: Event payload (request/response/error)
        version: Event schema version (default: "v1")

    Validation:
        - event_id: Must be valid UUID string
        - correlation_id: Must be valid UUID string
        - event_type: Must be valid routing event type (lowercase dot notation)
        - timestamp: Must be valid ISO 8601 timestamp

    Partition Key Policy (per EVENT_BUS_INTEGRATION_GUIDE):
        - Uses correlation_id as partition key
        - Cardinality: Medium (per request)
        - Ensures request→response ordering per workflow

    Examples:
        ```python
        # Request envelope (auto-generates event_id and timestamp)
        envelope = ModelRoutingEventEnvelope(
            event_type="omninode.agent.routing.requested.v1",
            correlation_id="abc-123",
            tenant_id="default",
            namespace="omninode",
            service="polymorphic-agent",
            schema_ref="registry://omninode/agent/routing_requested/v1",
            payload=ModelRoutingRequest(
                user_request="optimize my database queries",
                correlation_id="abc-123"
            )
        )

        # Response envelope
        envelope = ModelRoutingEventEnvelope(
            event_type="omninode.agent.routing.completed.v1",
            correlation_id="abc-123",
            tenant_id="default",
            namespace="omninode",
            service="agent-router-service",
            causation_id="def-456",
            schema_ref="registry://omninode/agent/routing_completed/v1",
            payload=ModelRoutingResponse(
                correlation_id="abc-123",
                recommendations=[...]
            )
        )

        # Error envelope
        envelope = ModelRoutingEventEnvelope(
            event_type="omninode.agent.routing.failed.v1",
            correlation_id="abc-123",
            tenant_id="default",
            namespace="omninode",
            service="agent-router-service",
            causation_id="def-456",
            schema_ref="registry://omninode/agent/routing_failed/v1",
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
        description="Event type (omninode.agent.routing.requested|completed|failed.v1)",
    )
    correlation_id: str = Field(
        ...,
        description="Request correlation ID for tracing (UUID string)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Event timestamp (ISO 8601, auto-generated)",
    )
    tenant_id: str = Field(
        default="default",
        description="Tenant identifier for multi-tenancy",
    )
    namespace: str = Field(
        default="omninode",
        description="Event namespace",
    )
    service: str = Field(
        ...,
        min_length=1,
        description="Source service name",
    )
    causation_id: Optional[str] = Field(
        None,
        description="Causation event ID (optional)",
    )
    schema_ref: str = Field(
        ...,
        description="Schema registry reference",
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
        """Validate event_type is a valid routing event type (lowercase dot notation per EVENT_BUS_INTEGRATION_GUIDE)."""
        valid_types = {
            "omninode.agent.routing.requested.v1",
            "omninode.agent.routing.completed.v1",
            "omninode.agent.routing.failed.v1",
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
        tenant_id: str = "default",
        namespace: str = "omninode",
        causation_id: Optional[str] = None,
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingRequest]":
        """
        Convenience factory for creating request envelopes.

        Args:
            user_request: User's input text
            correlation_id: Request correlation ID
            service: Source service name (default: "polymorphic-agent")
            tenant_id: Tenant identifier (default: "default")
            namespace: Event namespace (default: "omninode")
            causation_id: Causation event ID (optional)
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
            event_type="omninode.agent.routing.requested.v1",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            namespace=namespace,
            service=service,
            causation_id=causation_id,
            schema_ref="registry://omninode/agent/routing_requested/v1",
            payload=payload,
        )

    @classmethod
    def create_response(
        cls,
        correlation_id: str,
        recommendations: list,
        routing_metadata: dict,
        service: str = "agent-router-service",
        tenant_id: str = "default",
        namespace: str = "omninode",
        causation_id: Optional[str] = None,
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingResponse]":
        """
        Convenience factory for creating response envelopes.

        Args:
            correlation_id: Request correlation ID
            recommendations: List of agent recommendations
            routing_metadata: Routing metadata dictionary
            service: Source service name (default: "agent-router-service")
            tenant_id: Tenant identifier (default: "default")
            namespace: Event namespace (default: "omninode")
            causation_id: Causation event ID (optional)
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
            event_type="omninode.agent.routing.completed.v1",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            namespace=namespace,
            service=service,
            causation_id=causation_id,
            schema_ref="registry://omninode/agent/routing_completed/v1",
            payload=payload,
        )

    @classmethod
    def create_error(
        cls,
        correlation_id: str,
        error_code: str,
        error_message: str,
        service: str = "agent-router-service",
        tenant_id: str = "default",
        namespace: str = "omninode",
        causation_id: Optional[str] = None,
        **kwargs,
    ) -> "ModelRoutingEventEnvelope[ModelRoutingError]":
        """
        Convenience factory for creating error envelopes.

        Args:
            correlation_id: Request correlation ID
            error_code: Standard error code
            error_message: Human-readable error message
            service: Source service name (default: "agent-router-service")
            tenant_id: Tenant identifier (default: "default")
            namespace: Event namespace (default: "omninode")
            causation_id: Causation event ID (optional)
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
            event_type="omninode.agent.routing.failed.v1",
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            namespace=namespace,
            service=service,
            causation_id=causation_id,
            schema_ref="registry://omninode/agent/routing_failed/v1",
            payload=payload,
        )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_id": "def-456",
                "event_type": "omninode.agent.routing.requested.v1",
                "correlation_id": "abc-123",
                "timestamp": "2025-10-30T14:30:00Z",
                "tenant_id": "default",
                "namespace": "omninode",
                "service": "polymorphic-agent",
                "causation_id": None,
                "schema_ref": "registry://omninode/agent/routing_requested/v1",
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

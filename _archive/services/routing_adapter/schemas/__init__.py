#!/usr/bin/env python3
"""
Routing Adapter Schemas

Pydantic models for agent routing events via Kafka.

Event Types:
    - AGENT_ROUTING_REQUESTED: Agent requests routing decision
    - AGENT_ROUTING_COMPLETED: Routing service returns recommendations
    - AGENT_ROUTING_FAILED: Routing service encounters error

Kafka Topics:
    - agent.routing.requested.v1
    - agent.routing.completed.v1
    - agent.routing.failed.v1

Usage:
    Request routing:
    ```python
    from routing_adapter.schemas import (
        ModelRoutingEventEnvelope,
        ModelRoutingRequest
    )

    # Create request
    request = ModelRoutingRequest(
        user_request="optimize my database queries",
        correlation_id="abc-123"
    )

    # Wrap in envelope
    envelope = ModelRoutingEventEnvelope(
        event_type="AGENT_ROUTING_REQUESTED",
        correlation_id="abc-123",
        service="polymorphic-agent",
        payload=request
    )

    # Publish to Kafka
    await producer.send("omninode.agent.routing.requested.v1", envelope.model_dump())
    ```

    Or use convenience factory:
    ```python
    envelope = ModelRoutingEventEnvelope.create_request(
        user_request="optimize my database queries",
        correlation_id="abc-123",
        context={"domain": "database_optimization"}
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py (proven pattern)
"""

# Error schemas
from .model_routing_error import (
    ErrorCodes,
    ModelFallbackRecommendation,
    ModelRoutingError,
)

# Event envelope
from .model_routing_event_envelope import (
    ModelRoutingEventEnvelope,
)

# Request schemas
from .model_routing_request import (
    ModelRoutingOptions,
    ModelRoutingRequest,
)

# Response schemas
from .model_routing_response import (
    ModelAgentRecommendation,
    ModelRoutingConfidence,
    ModelRoutingMetadata,
    ModelRoutingResponse,
)

# Topics and event types
from .topics import TOPICS, EventTypes, RoutingTopics

__all__ = [
    # Request
    "ModelRoutingRequest",
    "ModelRoutingOptions",
    # Response
    "ModelRoutingResponse",
    "ModelAgentRecommendation",
    "ModelRoutingConfidence",
    "ModelRoutingMetadata",
    # Error
    "ModelRoutingError",
    "ModelFallbackRecommendation",
    "ErrorCodes",
    # Envelope
    "ModelRoutingEventEnvelope",
    # Topics
    "TOPICS",
    "EventTypes",
    "RoutingTopics",
]

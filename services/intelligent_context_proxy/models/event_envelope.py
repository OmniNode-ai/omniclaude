"""
Event envelope models for Intelligent Context Proxy.

Defines Pydantic models for all Kafka events flowing through the system.
All events follow a consistent envelope structure with correlation tracking.

Event Flow:
1. FastAPI → context.request.received.v1 → Reducer
2. Reducer → intents.persist-state.v1 → Store Effect
3. Orchestrator → context.query.requested.v1 → Intelligence Effect
4. Intelligence Effect → context.query.completed.v1 → Reducer
5. Orchestrator → context.rewrite.requested.v1 → Rewriter Compute
6. Rewriter Compute → context.rewrite.completed.v1 → Reducer
7. Orchestrator → context.forward.requested.v1 → Forwarder Effect
8. Forwarder Effect → context.forward.completed.v1 → Reducer
9. Orchestrator → context.response.completed.v1 → FastAPI
"""

from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Event types for domain events."""

    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    QUERY_REQUESTED = "QUERY_REQUESTED"
    QUERY_COMPLETED = "QUERY_COMPLETED"
    REWRITE_REQUESTED = "REWRITE_REQUESTED"
    REWRITE_COMPLETED = "REWRITE_COMPLETED"
    FORWARD_REQUESTED = "FORWARD_REQUESTED"
    FORWARD_COMPLETED = "FORWARD_COMPLETED"
    RESPONSE_COMPLETED = "RESPONSE_COMPLETED"
    FAILED = "FAILED"


class IntentType(str, Enum):
    """Intent types for coordination layer."""

    PERSIST_STATE = "PERSIST_STATE"
    QUERY_INTELLIGENCE = "QUERY_INTELLIGENCE"
    REWRITE_CONTEXT = "REWRITE_CONTEXT"
    FORWARD_ANTHROPIC = "FORWARD_ANTHROPIC"
    SEND_RESPONSE = "SEND_RESPONSE"


class BaseEventEnvelope(BaseModel):
    """
    Base event envelope for all Kafka events.

    All events follow this structure for consistency and traceability.
    """

    event_id: str = Field(default_factory=lambda: str(uuid4()), description="Unique event ID")
    event_type: EventType = Field(..., description="Event type (uppercase snake_case)")
    correlation_id: str = Field(..., description="Request correlation ID")
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp",
    )
    service: str = Field(default="intelligent-context-proxy", description="Source service")
    version: str = Field(default="v1", description="Schema version")
    payload: Dict[str, Any] = Field(..., description="Event-specific payload")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "event_id": "550e8400-e29b-41d4-a716-446655440000",
                "event_type": "REQUEST_RECEIVED",
                "correlation_id": "abc-123",
                "timestamp": "2025-11-09T14:30:00Z",
                "service": "intelligent-context-proxy",
                "version": "v1",
                "payload": {},
            }
        }


# ============================================================================
# Domain Event Models (Execution Layer)
# ============================================================================


class ContextRequestReceivedEvent(BaseEventEnvelope):
    """
    Event: context.request.received.v1

    Published by: FastAPI entry point
    Consumed by: NodeContextRequestReducer

    Payload: Original HTTP request from Claude Code
    """

    event_type: EventType = Field(default=EventType.REQUEST_RECEIVED)
    payload: Dict[str, Any] = Field(
        ...,
        description="HTTP request data (messages, system, model, oauth_token, etc.)",
    )


class ContextQueryRequestedEvent(BaseEventEnvelope):
    """
    Event: context.query.requested.v1

    Published by: NodeContextProxyOrchestrator
    Consumed by: NodeIntelligenceQueryEffect

    Payload: Request data + intent for intelligence queries
    """

    event_type: EventType = Field(default=EventType.QUERY_REQUESTED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Request data + intent for intelligence queries",
    )


class ContextQueryCompletedEvent(BaseEventEnvelope):
    """
    Event: context.query.completed.v1

    Published by: NodeIntelligenceQueryEffect
    Consumed by: NodeContextRequestReducer

    Payload: Intelligence data (patterns, debug_intelligence, memory_context)
    """

    event_type: EventType = Field(default=EventType.QUERY_COMPLETED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Intelligence data (patterns, debug_intel, memory, query_time_ms)",
    )


class ContextRewriteRequestedEvent(BaseEventEnvelope):
    """
    Event: context.rewrite.requested.v1

    Published by: NodeContextProxyOrchestrator
    Consumed by: NodeContextRewriterCompute

    Payload: Messages + system prompt + intelligence + intent
    """

    event_type: EventType = Field(default=EventType.REWRITE_REQUESTED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Messages, system_prompt, intelligence, intent",
    )


class ContextRewriteCompletedEvent(BaseEventEnvelope):
    """
    Event: context.rewrite.completed.v1

    Published by: NodeContextRewriterCompute
    Consumed by: NodeContextRequestReducer

    Payload: Rewritten messages + enhanced system prompt + metrics
    """

    event_type: EventType = Field(default=EventType.REWRITE_COMPLETED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Rewritten messages, system, tokens_before, tokens_after, processing_time_ms",
    )


class ContextForwardRequestedEvent(BaseEventEnvelope):
    """
    Event: context.forward.requested.v1

    Published by: NodeContextProxyOrchestrator
    Consumed by: NodeAnthropicForwarderEffect

    Payload: Rewritten request + OAuth token
    """

    event_type: EventType = Field(default=EventType.FORWARD_REQUESTED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Rewritten request + oauth_token",
    )


class ContextForwardCompletedEvent(BaseEventEnvelope):
    """
    Event: context.forward.completed.v1

    Published by: NodeAnthropicForwarderEffect
    Consumed by: NodeContextRequestReducer

    Payload: Anthropic API response + metrics
    """

    event_type: EventType = Field(default=EventType.FORWARD_COMPLETED)
    payload: Dict[str, Any] = Field(
        ...,
        description="Anthropic response_data, status_code, forward_time_ms",
    )


class ContextResponseCompletedEvent(BaseEventEnvelope):
    """
    Event: context.response.completed.v1

    Published by: NodeContextProxyOrchestrator
    Consumed by: FastAPI entry point

    Payload: Final response for Claude Code + metrics
    """

    event_type: EventType = Field(default=EventType.RESPONSE_COMPLETED)
    payload: Dict[str, Any] = Field(
        ...,
        description="response_data, intelligence_query_time_ms, context_rewrite_time_ms, anthropic_forward_time_ms, total_time_ms",
    )


class ContextFailedEvent(BaseEventEnvelope):
    """
    Event: context.*.failed.v1

    Published by: Any node on failure
    Consumed by: NodeContextRequestReducer + NodeContextProxyOrchestrator

    Payload: Error details
    """

    event_type: EventType = Field(default=EventType.FAILED)
    payload: Dict[str, Any] = Field(
        ...,
        description="error_message, error_code, error_context, stack_trace",
    )


# ============================================================================
# Intent Models (Coordination Layer)
# ============================================================================


class PersistStateIntent(BaseModel):
    """
    Intent: intents.persist-state.v1

    Published by: NodeContextRequestReducer
    Consumed by: Store Effect node (future)

    Purpose: FSM state persistence command
    """

    intent_type: IntentType = Field(default=IntentType.PERSIST_STATE)
    correlation_id: str = Field(..., description="Request correlation ID")
    current_state: str = Field(..., description="Current FSM state")
    previous_state: Optional[str] = Field(None, description="Previous FSM state")
    transition_history: List[Dict[str, Any]] = Field(
        default_factory=list, description="FSM transition history"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 timestamp",
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "intent_type": "PERSIST_STATE",
                "correlation_id": "abc-123",
                "current_state": "request_received",
                "previous_state": "idle",
                "transition_history": [
                    {"from": "idle", "to": "request_received", "timestamp": "2025-11-09T14:30:00Z"}
                ],
                "timestamp": "2025-11-09T14:30:00Z",
                "metadata": {},
            }
        }


# ============================================================================
# Topic Constants
# ============================================================================

class KafkaTopics:
    """Kafka topic names for intelligent context proxy."""

    # Domain event topics (execution layer)
    CONTEXT_REQUEST_RECEIVED = "context.request.received.v1"
    CONTEXT_QUERY_REQUESTED = "context.query.requested.v1"
    CONTEXT_QUERY_COMPLETED = "context.query.completed.v1"
    CONTEXT_REWRITE_REQUESTED = "context.rewrite.requested.v1"
    CONTEXT_REWRITE_COMPLETED = "context.rewrite.completed.v1"
    CONTEXT_FORWARD_REQUESTED = "context.forward.requested.v1"
    CONTEXT_FORWARD_COMPLETED = "context.forward.completed.v1"
    CONTEXT_RESPONSE_COMPLETED = "context.response.completed.v1"
    CONTEXT_FAILED = "context.failed.v1"

    # Intent topics (coordination layer)
    INTENTS_PERSIST_STATE = "intents.persist-state.v1"
    INTENTS_QUERY_INTELLIGENCE = "intents.query-intelligence.v1"
    INTENTS_REWRITE_CONTEXT = "intents.rewrite-context.v1"
    INTENTS_FORWARD_ANTHROPIC = "intents.forward-anthropic.v1"
    INTENTS_SEND_RESPONSE = "intents.send-response.v1"

    # External topics (reused from existing infrastructure)
    INTELLIGENCE_ANALYSIS_REQUESTED = (
        "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
    )
    INTELLIGENCE_ANALYSIS_COMPLETED = (
        "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
    )
    INTELLIGENCE_ANALYSIS_FAILED = (
        "dev.archon-intelligence.intelligence.code-analysis-failed.v1"
    )

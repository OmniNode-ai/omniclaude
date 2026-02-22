"""
ONEX contracts for Intelligent Context Proxy nodes.

Defines input/output contracts for:
- NodeContextRequestReducer
- NodeContextProxyOrchestrator

These contracts follow ONEX patterns but are simplified since we're using
mock base classes instead of full omnibase_core.
"""

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ============================================================================
# Reducer Contracts
# ============================================================================


class ProxyReducerInput(BaseModel):
    """
    Input contract for NodeContextRequestReducer.

    Contains event data from Kafka event.
    """

    event_type: str = Field(..., description="Event type (REQUEST_RECEIVED, QUERY_COMPLETED, etc.)")
    correlation_id: str = Field(..., description="Request correlation ID")
    input_state: Dict[str, Any] = Field(
        default_factory=dict, description="Event payload data"
    )
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "event_type": "REQUEST_RECEIVED",
                "correlation_id": "abc-123",
                "input_state": {"request_data": {}, "oauth_token": "Bearer ..."},
                "metadata": {},
            }
        }


class ProxyReducerOutput(BaseModel):
    """
    Output contract for NodeContextRequestReducer.

    Contains updated FSM state information.
    """

    result: Dict[str, Any] = Field(..., description="FSM state data")
    success: bool = Field(default=True, description="Whether transition succeeded")
    correlation_id: str = Field(..., description="Request correlation ID")
    timestamp: Optional[str] = Field(None, description="Processing timestamp")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "result": {
                    "current_state": "request_received",
                    "trigger": "REQUEST_RECEIVED",
                    "timestamp": "2025-11-09T14:30:00Z",
                },
                "success": True,
                "correlation_id": "abc-123",
                "timestamp": "2025-11-09T14:30:00Z",
            }
        }


# ============================================================================
# Orchestrator Contracts
# ============================================================================


class ProxyOrchestratorInput(BaseModel):
    """
    Input contract for NodeContextProxyOrchestrator.

    Contains request data from FastAPI entry point.
    """

    request_data: Dict[str, Any] = Field(..., description="HTTP request from Claude Code")
    oauth_token: str = Field(..., description="OAuth token for Anthropic API")
    correlation_id: str = Field(..., description="Request correlation ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "request_data": {
                    "model": "claude-sonnet-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "system": "You are a helpful assistant",
                },
                "oauth_token": "Bearer ...",
                "correlation_id": "abc-123",
                "metadata": {},
            }
        }


class ProxyOrchestratorOutput(BaseModel):
    """
    Output contract for NodeContextProxyOrchestrator.

    Contains final response for Claude Code + metrics.
    """

    response_data: Dict[str, Any] = Field(..., description="Anthropic API response")
    correlation_id: str = Field(..., description="Request correlation ID")
    intelligence_query_time_ms: int = Field(0, description="Intelligence query time")
    context_rewrite_time_ms: int = Field(0, description="Context rewrite time")
    anthropic_forward_time_ms: int = Field(0, description="Anthropic forward time")
    total_time_ms: int = Field(0, description="Total processing time")
    success: bool = Field(default=True, description="Whether workflow succeeded")

    class Config:
        """Pydantic config."""

        json_schema_extra = {
            "example": {
                "response_data": {
                    "id": "msg_123",
                    "content": [{"type": "text", "text": "Hello! How can I help you today?"}],
                    "model": "claude-sonnet-4",
                    "role": "assistant",
                },
                "correlation_id": "abc-123",
                "intelligence_query_time_ms": 1500,
                "context_rewrite_time_ms": 80,
                "anthropic_forward_time_ms": 450,
                "total_time_ms": 2030,
                "success": True,
            }
        }

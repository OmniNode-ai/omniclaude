"""Socket protocol request/response models for the embedded publisher.

Ported from omnibase_infra.runtime.emit_daemon.model_daemon_request
and model_daemon_response (OMN-1944).

Protocol: newline-delimited JSON over Unix socket.
"""

from __future__ import annotations

from typing import Annotated, Literal

from omnibase_core.types import JsonType  # noqa: TC002 - runtime use by Pydantic
from pydantic import BaseModel, ConfigDict, Field

# =============================================================================
# Request Models
# =============================================================================


class ModelDaemonPingRequest(BaseModel):
    """Ping/health check request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    command: Literal["ping"] = Field(default="ping")


class ModelDaemonEmitRequest(BaseModel):
    """Event emission request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: str = Field(..., min_length=1)
    payload: JsonType = Field(default_factory=dict)


ModelDaemonRequest = Annotated[
    ModelDaemonPingRequest | ModelDaemonEmitRequest,
    Field(description="Union of all daemon request types"),
]


def parse_daemon_request(
    data: dict[str, object],
) -> ModelDaemonPingRequest | ModelDaemonEmitRequest:
    """Parse raw dict into typed request model.

    Discriminates by field presence:
    - "command" -> ModelDaemonPingRequest
    - "event_type" -> ModelDaemonEmitRequest
    """
    if "command" in data:
        return ModelDaemonPingRequest.model_validate(data)
    elif "event_type" in data:
        return ModelDaemonEmitRequest.model_validate(data)
    else:
        raise ValueError(
            "Invalid request: must contain either 'command' or 'event_type' field"
        )


# =============================================================================
# Response Models
# =============================================================================


class ModelDaemonPingResponse(BaseModel):
    """Ping response with queue status."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok"] = Field(default="ok")
    queue_size: int = Field(..., ge=0)
    spool_size: int = Field(..., ge=0)


class ModelDaemonQueuedResponse(BaseModel):
    """Event successfully queued response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["queued"] = Field(default="queued")
    event_id: str = Field(..., min_length=1)


class ModelDaemonErrorResponse(BaseModel):
    """Error response."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["error"] = Field(default="error")
    reason: str = Field(..., min_length=1)


ModelDaemonResponse = Annotated[
    ModelDaemonPingResponse | ModelDaemonQueuedResponse | ModelDaemonErrorResponse,
    Field(discriminator="status"),
]


def parse_daemon_response(
    data: dict[str, object],
) -> ModelDaemonPingResponse | ModelDaemonQueuedResponse | ModelDaemonErrorResponse:
    """Parse raw dict into typed response model."""
    status = data.get("status")
    if status == "ok":
        return ModelDaemonPingResponse.model_validate(data)
    elif status == "queued":
        return ModelDaemonQueuedResponse.model_validate(data)
    elif status == "error":
        return ModelDaemonErrorResponse.model_validate(data)
    else:
        raise ValueError(f"Unknown response status: {status}")


__all__: list[str] = [
    "ModelDaemonEmitRequest",
    "ModelDaemonErrorResponse",
    "ModelDaemonPingRequest",
    "ModelDaemonPingResponse",
    "ModelDaemonQueuedResponse",
    "ModelDaemonRequest",
    "ModelDaemonResponse",
    "parse_daemon_request",
    "parse_daemon_response",
]

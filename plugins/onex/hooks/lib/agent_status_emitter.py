"""Agent status emitter — adapter layer for agent lifecycle status emission.

Wraps ModelAgentStatusPayload and emits via the emit daemon.
This is a thin wrapper over emit_event() following the established
omniclaude emit daemon pattern (hook → socket → daemon → Kafka).

INVARIANT: This function MUST fail open and NEVER block agent execution.
If Kafka/daemon is unavailable, log warning and return False.

Related Tickets:
    - OMN-1848: Agent Status Kafka Emitter (fail-open)
    - OMN-1847: EnumAgentState + ModelAgentStatus (blocker, models defined locally)

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def emit_agent_status(
    state: str,
    message: str,
    *,
    correlation_id: UUID | None = None,
    agent_name: str | None = None,
    session_id: str | None = None,
    agent_instance_id: str | None = None,
    progress: float | None = None,
    current_phase: str | None = None,
    current_task: str | None = None,
    blocking_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Emit agent status event via the emit daemon (non-blocking, fail-open).

    Validates input via ModelAgentStatusPayload (frozen Pydantic model),
    serializes to dict, and sends through the emit daemon to Kafka.

    INVARIANT: This function MUST fail open and NEVER block agent execution.

    Args:
        state: Agent state string (must be valid EnumAgentState value:
            idle, working, blocked, awaiting_input, finished, error).
            Accepts both str and EnumAgentState.
        message: Human-readable status message (max 500 chars).
        correlation_id: Correlation ID for tracing (auto-generated if None).
        agent_name: Name of the agent (defaults to AGENT_NAME env var).
        session_id: Session ID (defaults to SESSION_ID env var).
        agent_instance_id: Durable instance ID for parallel agent disambiguation.
        progress: Progress 0.0-1.0 (optional, monotonic within task).
        current_phase: Current workflow phase (optional).
        current_task: Current task description (optional).
        blocking_reason: Why blocked (optional, for notifications).
        metadata: Additional metadata dict (optional).

    Returns:
        True if successfully emitted to daemon socket, False otherwise.
        Note: True means accepted by daemon, not delivered to Kafka.
    """
    try:
        from omniclaude.hooks.schemas import EnumAgentState, ModelAgentStatusPayload

        # Coerce string state to enum (fail-open on invalid)
        try:
            validated_state = EnumAgentState(state)
        except ValueError:
            valid_states = [s.value for s in EnumAgentState]
            logger.error(
                "Invalid agent state: %r (valid: %s), event_type=agent.status, "
                "agent_name=%s, session_id=%s",
                state,
                valid_states,
                agent_name or os.environ.get("AGENT_NAME", "unknown"),
                session_id or os.environ.get("SESSION_ID", "unknown"),
            )
            return False

        # Resolve defaults from environment
        resolved_agent_name = agent_name or os.environ.get("AGENT_NAME", "unknown")
        resolved_session_id = session_id or os.environ.get("SESSION_ID", "unknown")

        # Build validated payload — Pydantic enforces all constraints
        payload_model = ModelAgentStatusPayload(
            agent_name=resolved_agent_name,
            session_id=resolved_session_id,
            agent_instance_id=agent_instance_id,
            state=validated_state,
            message=message,
            progress=progress,
            current_phase=current_phase,
            current_task=current_task,
            blocking_reason=blocking_reason,
            emitted_at=datetime.now(UTC),
            metadata=metadata or {},
            **(
                {"correlation_id": correlation_id} if correlation_id is not None else {}
            ),
        )

        # Serialize to flat dict for daemon transport
        payload = payload_model.model_dump(mode="json")

        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        return emit_event("agent.status", payload)

    except Exception as e:
        # Structured failure log for debugging
        logger.warning(
            "Failed to emit agent status: error_class=%s, error_message=%.200s, "
            "event_type=agent.status, agent_name=%s, session_id=%s, schema_version=1",
            type(e).__name__,
            str(e),
            agent_name or os.environ.get("AGENT_NAME", "unknown"),
            session_id or os.environ.get("SESSION_ID", "unknown"),
        )
        return False


__all__ = [
    "emit_agent_status",
]

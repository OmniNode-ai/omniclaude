# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Emit delegation events to EventBusInmemory.

Zero manual ``adapter.write_*()`` calls in business logic. All persistence flows
through event emission -> projection handler (subscribed on the bus) ->
DI-injected adapter. The same projection handler is used in production behind
the Kafka-backed pipeline; only the transport differs.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from omniclaude.hooks.topics import TopicBase

if TYPE_CHECKING:
    from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

logger = logging.getLogger(__name__)


async def emit_task_delegated(
    bus: EventBusInmemory,
    *,
    correlation_id: str,
    session_id: str,
    task_type: str,
    delegated_to: str,
    delegated_by: str,
    quality_gate_passed: bool,
    delegation_latency_ms: int,
    cost_savings_usd: float,
    quality_gate_reason: str | None = None,
    delegation_success: bool = True,
    model_name: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    repo: str | None = None,
    is_shadow: bool = False,
    llm_call_id: str = "",
) -> None:
    """Emit a task-delegated event to ``onex.evt.omniclaude.task-delegated.v1``.

    The projection handler subscribed on this topic UPSERTs the row into the
    ``delegation_events`` table via the DI-injected adapter.

    Field shape matches ``ModelTaskDelegatedEvent`` (omnimarket projection input)
    so downstream typing is preserved end-to-end.
    """
    payload: dict[str, object] = {
        "correlation_id": correlation_id,
        "session_id": session_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "task_type": task_type,
        "delegated_to": delegated_to,
        "delegated_by": delegated_by,
        "model_name": model_name or delegated_to,
        "quality_gate_passed": quality_gate_passed,
        "quality_gate_reason": quality_gate_reason,
        "quality_gates_checked": None,
        "quality_gates_failed": None,
        "delegation_success": delegation_success,
        "cost_savings_usd": cost_savings_usd,
        "cost_usd": 0.0,
        "delegation_latency_ms": delegation_latency_ms,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "repo": repo,
        "is_shadow": is_shadow,
        "llm_call_id": llm_call_id,
    }

    value = json.dumps(payload).encode("utf-8")
    await bus.publish(
        topic=TopicBase.TASK_DELEGATED,
        key=correlation_id.encode("utf-8"),
        value=value,
    )

    logger.info(
        "Emitted task-delegated event: correlation_id=%s model=%s latency=%dms",
        correlation_id,
        delegated_to,
        delegation_latency_ms,
    )


__all__: list[str] = ["emit_task_delegated"]

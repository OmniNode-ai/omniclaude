# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Bootstrap EventBusInmemory wired to the delegation projection handler.

Wires:
  onex.evt.omniclaude.task-delegated.v1 -> HandlerProjectionDelegation

This is the contract-driven projection path used in the local Claude Code
runtime (where Kafka is not available). The same projection handler runs in
production behind the Kafka-backed pipeline; this bootstrap is the in-process
substitute that keeps the architecture consistent.

Architecture:
    DelegationRunner / delegate skill
        -> emit ModelTaskDelegatedPayload to EventBusInmemory
        -> HandlerProjectionDelegation.project(event, db_adapter)
        -> db_adapter.upsert("delegation_events", "correlation_id", row)

`db_adapter` is any object satisfying ``ProtocolProjectionDatabaseSync``
(``upsert(table, conflict_key, row) -> bool``). Inject ``InmemoryDatabaseAdapter``
in unit tests, the SQLite projection shim in the customer-deployable path, or
asyncpg-backed adapters in the production path.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory
from omnibase_infra.models import ModelNodeIdentity

from omniclaude.hooks.topics import TopicBase

if TYPE_CHECKING:
    from omnibase_infra.event_bus.models import ModelEventMessage

logger = logging.getLogger(__name__)


@runtime_checkable
class ProtocolProjectionDatabaseSync(Protocol):
    """Minimal projection-database protocol consumed by the bootstrap.

    Structurally compatible with
    ``omnimarket.projection.protocol_database.ProtocolProjectionDatabaseSync``
    so the bootstrap can be type-checked and runtime-checked without a hard
    import on omnimarket at module load time.
    """

    def upsert(
        self,
        table: str,
        conflict_key: str,
        row: dict[str, object],
    ) -> bool: ...

    def query(
        self,
        table: str,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]: ...


async def bootstrap_delegation_bus(
    db_adapter: ProtocolProjectionDatabaseSync | None = None,
    *,
    environment: str = "local",
    group: str = "delegation",
) -> EventBusInmemory:
    """Create and start an EventBusInmemory with the delegation projection wired.

    Args:
        db_adapter: Database adapter satisfying ``ProtocolProjectionDatabaseSync``.
            When None, the projection handler is still subscribed but writes are
            skipped — useful for tests that only assert event flow.
        environment: Bus environment label (forwarded to EventBusInmemory).
        group: Bus group label (forwarded to EventBusInmemory).

    Returns:
        Started EventBusInmemory instance with the projection handler subscribed
        on ``onex.evt.omniclaude.task-delegated.v1``.
    """
    if db_adapter is not None and not isinstance(
        db_adapter,
        ProtocolProjectionDatabaseSync,
    ):
        raise TypeError(
            "db_adapter must implement ProtocolProjectionDatabaseSync "
            "(upsert and query methods)"
        )

    bus = EventBusInmemory(environment=environment, group=group)
    await bus.start()

    identity = ModelNodeIdentity(
        env=environment,
        service="omniclaude",
        node_name="projection-delegation",
        version="v1",
    )

    async def _handle_task_delegated(msg: ModelEventMessage) -> None:
        """Project a task-delegated event via HandlerProjectionDelegation.

        omnimarket is a soft dependency: when not installed the handler logs a
        warning and skips persistence. This mirrors the soft-import pattern used
        in plugins/onex/skills/delegate/_lib/run.py.
        """
        try:
            data = json.loads(msg.value) if msg.value else {}
        except json.JSONDecodeError:
            logger.exception("task-delegated event has invalid JSON value")
            return

        if not isinstance(data, dict):
            logger.warning(
                "task-delegated event must be a JSON object, got %s",
                type(data).__name__,
            )
            return

        if isinstance(data.get("payload"), dict):
            data = data["payload"]

        correlation_id = data.get("correlation_id", "unknown")
        logger.info(
            "Projecting task-delegated event: correlation_id=%s",
            correlation_id,
        )

        if db_adapter is None:
            return

        try:
            from omnimarket.nodes.node_projection_delegation.handlers.handler_projection_delegation import (  # noqa: PLC0415
                HandlerProjectionDelegation,
                ModelTaskDelegatedEvent,
            )
        except ImportError:
            logger.warning(
                "omnimarket not installed — skipping delegation projection "
                "(correlation_id=%s)",
                correlation_id,
            )
            return

        try:
            event = ModelTaskDelegatedEvent(**data)
            handler = HandlerProjectionDelegation()
            handler.project(event, db_adapter)
        except Exception:
            logger.exception(
                "Failed to project task-delegated event (correlation_id=%s)",
                correlation_id,
            )

    await bus.subscribe(
        topic=TopicBase.TASK_DELEGATED,
        node_identity=identity,
        on_message=_handle_task_delegated,
    )

    logger.info(
        "Delegation bus bootstrapped (topic=%s, environment=%s, group=%s)",
        TopicBase.TASK_DELEGATED,
        environment,
        group,
    )
    return bus


__all__: list[str] = [
    "ProtocolProjectionDatabaseSync",
    "bootstrap_delegation_bus",
]

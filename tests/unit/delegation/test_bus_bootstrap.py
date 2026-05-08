# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the delegation bus bootstrap (OMN-10656)."""

from __future__ import annotations

import asyncio

import pytest

from omniclaude.delegation.bus_bootstrap import (
    ProtocolProjectionDatabaseSync,
    bootstrap_delegation_bus,
)
from omniclaude.hooks.topics import TopicBase


class _CapturingAdapter:
    """ProtocolProjectionDatabaseSync stub recording every upsert call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def upsert(
        self,
        table: str,
        conflict_key: str,
        row: dict[str, object],
    ) -> bool:
        self.calls.append((table, conflict_key, row))
        return True

    def query(
        self,
        table: str,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]:
        del table, filters
        return []


@pytest.mark.unit
class TestBootstrapDelegationBus:
    """bootstrap_delegation_bus returns a started bus with the projection wired."""

    def test_bootstrap_returns_started_bus(self) -> None:
        bus = asyncio.run(bootstrap_delegation_bus())
        try:
            health = asyncio.run(bus.health_check())
            assert health.get("started") is True
        finally:
            asyncio.run(bus.close())

    def test_bootstrap_subscribes_to_task_delegated_topic(self) -> None:
        bus = asyncio.run(bootstrap_delegation_bus())
        try:
            subscribers = bus._subscribers.get(  # noqa: SLF001
                str(TopicBase.TASK_DELEGATED), []
            )
            assert len(subscribers) == 1
        finally:
            asyncio.run(bus.close())

    def test_protocol_runtime_check_accepts_capturing_adapter(self) -> None:
        adapter = _CapturingAdapter()
        assert isinstance(adapter, ProtocolProjectionDatabaseSync)

    def test_bootstrap_rejects_invalid_adapter_shape(self) -> None:
        with pytest.raises(TypeError, match="ProtocolProjectionDatabaseSync"):
            asyncio.run(bootstrap_delegation_bus(db_adapter=object()))  # type: ignore[arg-type]

    def test_environment_and_group_propagate(self) -> None:
        bus = asyncio.run(bootstrap_delegation_bus(environment="test", group="custom"))
        try:
            assert bus.environment == "test"
            assert bus.group == "custom"
        finally:
            asyncio.run(bus.close())

    def test_non_object_json_event_is_ignored_without_subscriber_failure(self) -> None:
        async def _run() -> None:
            bus = await bootstrap_delegation_bus()
            try:
                await bus.publish(
                    topic=str(TopicBase.TASK_DELEGATED),
                    key=None,
                    value=b'["not", "an", "object"]',
                )
                assert bus._subscriber_failures == {}  # noqa: SLF001
            finally:
                await bus.close()

        asyncio.run(_run())

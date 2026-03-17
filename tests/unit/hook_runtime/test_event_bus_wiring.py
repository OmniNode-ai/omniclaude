# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for EventBusInmemory wiring in hook runtime server. [OMN-5312]"""

import uuid

import pytest

from omniclaude.hook_runtime.delegation_state import DelegationConfig
from omniclaude.hook_runtime.server import HookRuntimeConfig, HookRuntimeServer


def _short_sock() -> str:
    return f"/tmp/omni-evb-{uuid.uuid4().hex[:8]}.sock"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_server_has_event_bus() -> None:
    """Server exposes an EventBusInmemory after start()."""
    from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

    socket_path = _short_sock()
    config = HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
        delegation=DelegationConfig(),
    )
    server = HookRuntimeServer(config=config)
    await server.start()
    try:
        assert server.event_bus is not None
        assert isinstance(server.event_bus, EventBusInmemory)
    finally:
        await server.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_bus_environment_is_hook_runtime() -> None:
    """EventBusInmemory is created with environment='hook-runtime'."""
    socket_path = _short_sock()
    config = HookRuntimeConfig(
        socket_path=socket_path,
        pid_path=socket_path.replace(".sock", ".pid"),
    )
    server = HookRuntimeServer(config=config)
    await server.start()
    try:
        # EventBusInmemory stores environment as an attribute
        assert server.event_bus is not None
        assert server.event_bus.environment == "hook-runtime"
    finally:
        await server.stop()

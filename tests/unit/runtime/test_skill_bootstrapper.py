# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for SkillBootstrapper lifecycle management.

Tests:
    1. Wiring called on init (handlers registered in container)
    2. Event bus started and healthy
    3. GitHub handler resolvable after init
    4. Clean shutdown (bus stopped, registry cleared)
    5. Partial-init failure: bus started, wiring fails -> shutdown closes bus, re-init succeeds
    6. initialize() -> shutdown() -> initialize() cycle
    7. ONEX_EVENT_BUS_TYPE=kafka raises NotImplementedError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from plugins.onex.runtime.handlers.handler_github import HandlerGitHub
from plugins.onex.runtime.skill_bootstrapper import SkillBootstrapper

# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_wiring_called_on_init() -> None:
    """After initialize(), handlers must be registered in the container."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        assert bootstrapper.initialized is True
        assert bootstrapper.container is not None
        registry = bootstrapper.container.service_registry
        assert HandlerGitHub.__name__ in registry._name_map
    finally:
        await bootstrapper.shutdown()


@pytest.mark.unit
async def test_event_bus_started_and_healthy() -> None:
    """After initialize(), the event bus must be started and healthy."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        assert bootstrapper.event_bus is not None
        health = await bootstrapper.event_bus.health_check()
        assert health.get("healthy") is True
    finally:
        await bootstrapper.shutdown()


@pytest.mark.unit
async def test_github_handler_resolvable() -> None:
    """HandlerGitHub must be resolvable from the container after init."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        registry = bootstrapper.container.service_registry
        assert HandlerGitHub.__name__ in registry._name_map
        reg_id = registry._name_map[HandlerGitHub.__name__]
        assert reg_id in registry._registrations
    finally:
        await bootstrapper.shutdown()


@pytest.mark.unit
async def test_clean_shutdown() -> None:
    """After shutdown(), bus and registry must be cleared."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    await bootstrapper.shutdown()

    assert bootstrapper.initialized is False
    assert bootstrapper.event_bus is None
    assert bootstrapper.container is None


@pytest.mark.unit
async def test_partial_init_failure_shutdown_closes_bus() -> None:
    """If wiring fails after bus start, shutdown() must still close the bus.

    After shutdown(), re-initialize() must succeed.
    """
    bootstrapper = SkillBootstrapper()

    # Patch wire_skill_handlers_only to fail after bus is started
    with patch(
        "plugins.onex.runtime.skill_bootstrapper.wire_skill_handlers_only",
        new_callable=AsyncMock,
        side_effect=RuntimeError("Simulated wiring failure"),
    ):
        with pytest.raises(RuntimeError, match="Simulated wiring failure"):
            await bootstrapper.initialize()

    # Bus was started but _initialized is False
    assert bootstrapper.initialized is False
    assert bootstrapper.event_bus is not None  # bus was created before failure

    # shutdown() must clean up the bus
    await bootstrapper.shutdown()
    assert bootstrapper.event_bus is None

    # Re-initialize must succeed (no patching = real wiring)
    await bootstrapper.initialize()
    try:
        assert bootstrapper.initialized is True
        assert bootstrapper.event_bus is not None
    finally:
        await bootstrapper.shutdown()


@pytest.mark.unit
async def test_init_shutdown_init_cycle() -> None:
    """initialize() -> shutdown() -> initialize() must work without error."""
    bootstrapper = SkillBootstrapper()

    await bootstrapper.initialize()
    assert bootstrapper.initialized is True

    await bootstrapper.shutdown()
    assert bootstrapper.initialized is False

    await bootstrapper.initialize()
    assert bootstrapper.initialized is True
    assert bootstrapper.event_bus is not None
    assert bootstrapper.container is not None

    await bootstrapper.shutdown()


@pytest.mark.unit
async def test_kafka_bus_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """ONEX_EVENT_BUS_TYPE=kafka must raise NotImplementedError."""
    monkeypatch.setenv("ONEX_EVENT_BUS_TYPE", "kafka")
    bootstrapper = SkillBootstrapper()
    with pytest.raises(NotImplementedError, match=r"does not support.*kafka"):
        await bootstrapper.initialize()


@pytest.mark.unit
async def test_double_initialize_raises() -> None:
    """Calling initialize() twice must raise RuntimeError."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        with pytest.raises(RuntimeError, match="already initialized"):
            await bootstrapper.initialize()
    finally:
        await bootstrapper.shutdown()

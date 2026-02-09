# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for PluginClaude — domain plugin lifecycle.

Ticket: OMN-2002 - PluginClaude + generic config-driven plugin loader

All tests mock external dependencies (Kafka, omnibase_infra) to ensure
they run without infrastructure. The test matrix covers:

- Protocol compliance
- Property accessors
- Activation gating (KAFKA_BOOTSTRAP_SERVERS)
- Publisher initialisation and failure cleanup
- Handler wiring delegation
- Dispatcher / consumer skip behaviour
- Shutdown idempotency and exception safety
- Status line reporting
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Lightweight stubs for omnibase_infra types
# ---------------------------------------------------------------------------
# These replace the real imports so tests never depend on infra installation.


@dataclass
class StubDomainPluginResult:
    """Minimal stand-in for ModelDomainPluginResult."""

    plugin_id: str
    success: bool
    message: str = ""
    resources_created: list[str] = field(default_factory=list)
    services_registered: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    error_message: str | None = None
    unsubscribe_callbacks: list[Callable[[], Awaitable[None]]] = field(
        default_factory=list
    )

    def __bool__(self) -> bool:
        return self.success

    @classmethod
    def succeeded(
        cls,
        plugin_id: str,
        message: str = "",
        duration_seconds: float = 0.0,
    ) -> StubDomainPluginResult:
        return cls(
            plugin_id=plugin_id,
            success=True,
            message=message,
            duration_seconds=duration_seconds,
        )

    @classmethod
    def failed(
        cls,
        plugin_id: str,
        error_message: str,
        message: str = "",
        duration_seconds: float = 0.0,
    ) -> StubDomainPluginResult:
        return cls(
            plugin_id=plugin_id,
            success=False,
            message=message or f"Plugin {plugin_id} failed",
            error_message=error_message,
            duration_seconds=duration_seconds,
        )

    @classmethod
    def skipped(
        cls,
        plugin_id: str,
        reason: str,
    ) -> StubDomainPluginResult:
        return cls(
            plugin_id=plugin_id,
            success=True,
            message=f"Plugin {plugin_id} skipped: {reason}",
        )


@dataclass
class StubDomainPluginConfig:
    """Minimal stand-in for ModelDomainPluginConfig."""

    container: object = None
    event_bus: object = None
    correlation_id: object = None
    input_topic: str = ""
    output_topic: str = ""
    consumer_group: str = ""
    dispatch_engine: object = None


class StubProtocolDomainPlugin:
    """Stub protocol — used for isinstance checks in tests."""

    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _patch_infra_imports():
    """Inject stubs into sys.modules so ``plugin.py`` imports resolve."""
    mock_protocol_module = MagicMock()
    mock_protocol_module.ProtocolDomainPlugin = StubProtocolDomainPlugin
    mock_protocol_module.ModelDomainPluginConfig = StubDomainPluginConfig
    mock_protocol_module.ModelDomainPluginResult = StubDomainPluginResult

    with patch.dict(
        sys.modules,
        {
            "omnibase_infra.runtime.protocol_domain_plugin": mock_protocol_module,
        },
    ):
        yield mock_protocol_module


@pytest.fixture
def plugin():
    """Return a fresh PluginClaude instance (imports under patched modules)."""
    # Force re-import so module-level protocol check uses stubs
    if "omniclaude.runtime.plugin" in sys.modules:
        del sys.modules["omniclaude.runtime.plugin"]

    from omniclaude.runtime.plugin import PluginClaude

    return PluginClaude()


@pytest.fixture
def config():
    """Return a stub ModelDomainPluginConfig."""
    return StubDomainPluginConfig(
        container=MagicMock(),
        event_bus=MagicMock(),
    )


@pytest.fixture
def mock_publisher():
    """Return a mock EmbeddedEventPublisher with async start/stop."""
    pub = AsyncMock()
    pub.start = AsyncMock()
    pub.stop = AsyncMock()
    return pub


@pytest.fixture
def mock_publisher_config():
    """Return a mock PublisherConfig."""
    return MagicMock()


# ===================================================================
# Protocol compliance
# ===================================================================


class TestProtocolCompliance:
    """Verify PluginClaude satisfies ProtocolDomainPlugin structurally."""

    def test_has_plugin_id_property(self, plugin):
        assert hasattr(plugin, "plugin_id")
        assert isinstance(plugin.plugin_id, str)

    def test_has_display_name_property(self, plugin):
        assert hasattr(plugin, "display_name")
        assert isinstance(plugin.display_name, str)

    def test_has_should_activate(self, plugin):
        assert callable(getattr(plugin, "should_activate", None))

    def test_has_initialize(self, plugin):
        assert callable(getattr(plugin, "initialize", None))

    def test_has_wire_handlers(self, plugin):
        assert callable(getattr(plugin, "wire_handlers", None))

    def test_has_wire_dispatchers(self, plugin):
        assert callable(getattr(plugin, "wire_dispatchers", None))

    def test_has_start_consumers(self, plugin):
        assert callable(getattr(plugin, "start_consumers", None))

    def test_has_shutdown(self, plugin):
        assert callable(getattr(plugin, "shutdown", None))


# ===================================================================
# Properties
# ===================================================================


class TestProperties:
    """Verify plugin_id and display_name return expected strings."""

    def test_plugin_id(self, plugin):
        assert plugin.plugin_id == "claude"

    def test_display_name(self, plugin):
        assert plugin.display_name == "Claude Code Integration"


# ===================================================================
# should_activate
# ===================================================================


class TestShouldActivate:
    """Verify activation gating on KAFKA_BOOTSTRAP_SERVERS."""

    def test_returns_true_when_kafka_set(self, plugin, config):
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "localhost:9092"}):
            assert plugin.should_activate(config) is True

    def test_returns_false_when_kafka_missing(self, plugin, config):
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k != "KAFKA_BOOTSTRAP_SERVERS"
        }
        with patch.dict("os.environ", env, clear=True):
            assert plugin.should_activate(config) is False

    def test_returns_false_when_kafka_empty(self, plugin, config):
        with patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": ""}):
            assert plugin.should_activate(config) is False


# ===================================================================
# initialize
# ===================================================================


class TestInitialize:
    """Verify publisher creation, start, and failure handling."""

    @pytest.mark.asyncio
    async def test_starts_publisher(
        self, plugin, config, mock_publisher, mock_publisher_config
    ):
        with (
            patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "localhost:9092"}),
            patch(
                "omniclaude.runtime.plugin.PublisherConfig",
                return_value=mock_publisher_config,
                create=True,
            ) as mock_cfg_cls,
            patch(
                "omniclaude.runtime.plugin.EmbeddedEventPublisher",
                return_value=mock_publisher,
                create=True,
            ) as mock_pub_cls,
        ):
            # Ensure the lazy imports inside initialize() resolve to our mocks
            with patch.dict(
                sys.modules,
                {
                    "omniclaude.publisher.publisher_config": MagicMock(
                        PublisherConfig=mock_cfg_cls
                    ),
                    "omniclaude.publisher.embedded_publisher": MagicMock(
                        EmbeddedEventPublisher=mock_pub_cls
                    ),
                },
            ):
                result = await plugin.initialize(config)

        assert result.success is True
        assert "embedded-event-publisher" in result.resources_created
        mock_publisher.start.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_skipped_when_kafka_missing(self, plugin, config):
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k != "KAFKA_BOOTSTRAP_SERVERS"
        }
        with patch.dict("os.environ", env, clear=True):
            result = await plugin.initialize(config)

        assert result.success is True
        assert "skipped" in result.message.lower()

    @pytest.mark.asyncio
    async def test_failure_cleans_up(self, plugin, config, mock_publisher):
        mock_publisher.start.side_effect = RuntimeError("Kafka unreachable")

        with (
            patch.dict("os.environ", {"KAFKA_BOOTSTRAP_SERVERS": "localhost:9092"}),
            patch.dict(
                sys.modules,
                {
                    "omniclaude.publisher.publisher_config": MagicMock(
                        PublisherConfig=MagicMock(return_value=MagicMock())
                    ),
                    "omniclaude.publisher.embedded_publisher": MagicMock(
                        EmbeddedEventPublisher=MagicMock(return_value=mock_publisher)
                    ),
                },
            ),
        ):
            result = await plugin.initialize(config)

        assert result.success is False
        assert "Kafka unreachable" in (result.error_message or "")
        # Publisher should have been cleaned up
        assert plugin._publisher is None


# ===================================================================
# wire_handlers
# ===================================================================


class TestWireHandlers:
    """Verify handler wiring delegation."""

    @pytest.mark.asyncio
    async def test_delegates_to_wire_omniclaude_services(self, plugin, config):
        mock_wire = AsyncMock()
        with (
            patch.dict(
                "os.environ",
                {"OMNICLAUDE_CONTRACTS_ROOT": "/some/path"},
            ),
            patch(
                "omniclaude.runtime.plugin.wire_omniclaude_services",
                mock_wire,
                create=True,
            ),
            patch.dict(
                sys.modules,
                {
                    "omniclaude.runtime.wiring": MagicMock(
                        wire_omniclaude_services=mock_wire
                    ),
                },
            ),
        ):
            result = await plugin.wire_handlers(config)

        assert result.success is True
        mock_wire.assert_awaited_once_with(config.container)

    @pytest.mark.asyncio
    async def test_skipped_when_contracts_root_missing(self, plugin, config):
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k != "OMNICLAUDE_CONTRACTS_ROOT"
        }
        with patch.dict("os.environ", env, clear=True):
            result = await plugin.wire_handlers(config)

        assert result.success is True
        assert "skipped" in result.message.lower()
        assert "OMNICLAUDE_CONTRACTS_ROOT" in result.message


# ===================================================================
# wire_dispatchers / start_consumers — both skip
# ===================================================================


class TestSkippedPhases:
    """Verify wire_dispatchers and start_consumers return .skipped()."""

    @pytest.mark.asyncio
    async def test_wire_dispatchers_skipped(self, plugin, config):
        result = await plugin.wire_dispatchers(config)
        assert result.success is True
        assert "skipped" in result.message.lower()

    @pytest.mark.asyncio
    async def test_start_consumers_skipped(self, plugin, config):
        result = await plugin.start_consumers(config)
        assert result.success is True
        assert "skipped" in result.message.lower()
        assert "consumer" in result.message.lower()


# ===================================================================
# shutdown
# ===================================================================


class TestShutdown:
    """Verify idempotent, exception-safe shutdown."""

    @pytest.mark.asyncio
    async def test_stops_publisher(self, plugin, config, mock_publisher):
        plugin._publisher = mock_publisher

        result = await plugin.shutdown(config)

        assert result.success is True
        mock_publisher.stop.assert_awaited_once()
        assert plugin._publisher is None

    @pytest.mark.asyncio
    async def test_idempotent_when_no_publisher(self, plugin, config):
        assert plugin._publisher is None

        result = await plugin.shutdown(config)

        assert result.success is True

    @pytest.mark.asyncio
    async def test_guard_prevents_concurrent(self, plugin, config, mock_publisher):
        """Second call while shutdown is in progress is a no-op."""
        plugin._publisher = mock_publisher

        # Simulate shutdown_in_progress being set
        plugin._shutdown_in_progress = True
        result = await plugin.shutdown(config)

        assert result.success is True
        # Publisher.stop should NOT have been called (guard short-circuited)
        mock_publisher.stop.assert_not_awaited()
        # Reset for next call
        plugin._shutdown_in_progress = False

    @pytest.mark.asyncio
    async def test_exception_clears_references(self, plugin, config, mock_publisher):
        """If stop() raises, references are still cleared."""
        mock_publisher.stop.side_effect = RuntimeError("stop failed")
        plugin._publisher = mock_publisher
        plugin._publisher_config = MagicMock()

        result = await plugin.shutdown(config)

        assert result.success is False
        assert "stop failed" in (result.error_message or "")
        # References must be cleared even on error
        assert plugin._publisher is None
        assert plugin._publisher_config is None

    @pytest.mark.asyncio
    async def test_shutdown_resets_in_progress_flag(
        self, plugin, config, mock_publisher
    ):
        """Verify _shutdown_in_progress is reset after shutdown completes."""
        plugin._publisher = mock_publisher

        await plugin.shutdown(config)

        assert plugin._shutdown_in_progress is False


# ===================================================================
# get_status_line
# ===================================================================


class TestStatusLine:
    """Verify status line reporting."""

    def test_disabled_when_no_publisher(self, plugin):
        assert plugin.get_status_line() == "disabled"

    def test_enabled_when_publisher_running(self, plugin, mock_publisher):
        plugin._publisher = mock_publisher
        assert plugin.get_status_line() == "enabled (Publisher + Kafka)"


# ===================================================================
# Module-level import
# ===================================================================


class TestModuleImport:
    """Verify PluginClaude is importable from the runtime package."""

    def test_importable_from_runtime_package(self):
        # Verify __init__.py re-exports PluginClaude
        from omniclaude.runtime import PluginClaude

        instance = PluginClaude()
        assert instance.plugin_id == "claude"

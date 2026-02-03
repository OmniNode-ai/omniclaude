# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for RoutingEventClient - Kafka-based agent routing.

These tests verify:
- RoutingEventClient initialization and configuration validation
- start() / stop() lifecycle management
- request_routing() with mocked RequestResponseWiring
- route_via_events() convenience function
- Fallback to local AgentRouter on failure

All Kafka and RequestResponseWiring operations are mocked via conftest.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Note: omnibase_infra mocking is handled by conftest.py which loads before this file
# Import the module under test
import omniclaude.lib.core.routing_event_client as routing_module
from omniclaude.lib.core.routing_event_client import (
    RoutingEventClient,
    RoutingEventClientContext,
    _format_recommendations,
    route_via_events,
)
from omniclaude.lib.errors import OnexError

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for tests."""
    settings_mock = MagicMock()
    settings_mock.get_effective_kafka_bootstrap_servers.return_value = "localhost:9092"
    settings_mock.kafka_environment = "dev"
    settings_mock.use_event_routing = True
    return settings_mock


@pytest.fixture
def mock_wiring():
    """Create mock RequestResponseWiring."""
    wiring = MagicMock()
    wiring.wire_request_response = AsyncMock()
    # Note: routing client expects response.get("payload", {}).get("recommendations", [])
    wiring.send_request = AsyncMock(return_value={"payload": {"recommendations": []}})
    wiring.cleanup = AsyncMock()
    return wiring


@pytest.fixture
def mock_event_bus():
    """Create mock EventBusKafka."""
    event_bus = MagicMock()
    event_bus.start = AsyncMock()
    event_bus.stop = AsyncMock()
    return event_bus


# ==============================================================================
# Tests
# ==============================================================================


class TestRoutingEventClientInitialization:
    """Tests for RoutingEventClient initialization."""

    def test_initialization_with_explicit_bootstrap_servers(
        self, mock_settings
    ) -> None:
        """Test client initialization with explicit bootstrap_servers."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(
                bootstrap_servers="localhost:9092",
                request_timeout_ms=3000,
            )

            assert client.bootstrap_servers == "localhost:9092"
            assert client.request_timeout_ms == 3000
            assert client._started is False
            assert client._wiring is None
            assert client._event_bus is None

    def test_initialization_with_settings_bootstrap_servers(
        self, mock_settings
    ) -> None:
        """Test client uses settings when bootstrap_servers not provided."""
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = (
            "kafka.example.com:9092"
        )

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient()

            assert client.bootstrap_servers == "kafka.example.com:9092"

    def test_initialization_fails_without_bootstrap_servers(
        self, mock_settings
    ) -> None:
        """Test client raises OnexError when no bootstrap servers configured."""
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = None

        with patch.object(routing_module, "settings", mock_settings):
            with pytest.raises(OnexError) as exc_info:
                RoutingEventClient()

            assert "bootstrap_servers" in str(exc_info.value.message)

    def test_initialization_with_custom_consumer_group(self, mock_settings) -> None:
        """Test client accepts custom consumer_group_id."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(
                bootstrap_servers="localhost:9092",
                consumer_group_id="custom-group",
            )

            assert client.bootstrap_servers == "localhost:9092"


class TestRoutingEventClientLifecycle:
    """Tests for RoutingEventClient start() and stop() lifecycle."""

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, mock_settings) -> None:
        """Test that calling start() multiple times is safe."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True  # Simulate already started

            # Should return early without error
            await client.start()

            assert client._started is True

    @pytest.mark.asyncio
    async def test_start_requires_kafka_environment(self, mock_settings) -> None:
        """Test that start() requires KAFKA_ENVIRONMENT to be set."""
        mock_settings.kafka_environment = None

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")

            with pytest.raises(OnexError) as exc_info:
                await client.start()

            assert "KAFKA_ENVIRONMENT" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_stop_cleans_up_resources(
        self, mock_settings, mock_wiring, mock_event_bus
    ) -> None:
        """Test that stop() properly cleans up all resources."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring
            client._event_bus = mock_event_bus

            await client.stop()

            assert client._started is False
            assert client._wiring is None
            assert client._event_bus is None
            mock_wiring.cleanup.assert_called_once()
            mock_event_bus.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_not_started(self, mock_settings) -> None:
        """Test that stop() is safe to call when client was never started."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")

            # Should not raise
            await client.stop()

            assert client._started is False

    @pytest.mark.asyncio
    async def test_stop_handles_partial_initialization(
        self, mock_settings, mock_event_bus
    ) -> None:
        """Test stop() works even with partial initialization (no wiring)."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = None
            client._event_bus = mock_event_bus

            await client.stop()

            assert client._started is False
            mock_event_bus.stop.assert_called_once()


class TestRoutingEventClientHealthCheck:
    """Tests for RoutingEventClient health_check()."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_started(
        self, mock_settings
    ) -> None:
        """Test health_check returns False when client not started."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_started_with_wiring(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test health_check returns True when client is started with wiring."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_wiring_is_none(
        self, mock_settings
    ) -> None:
        """Test health_check returns False when wiring is None."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = None

            result = await client.health_check()

            assert result is False


class TestRoutingEventClientRequestRouting:
    """Tests for RoutingEventClient request_routing()."""

    @pytest.mark.asyncio
    async def test_request_routing_fails_when_not_started(self, mock_settings) -> None:
        """Test request_routing raises OnexError when client not started."""
        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")

            with pytest.raises(OnexError) as exc_info:
                await client.request_routing(user_request="test request")

            assert "not started" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_request_routing_uses_wiring_send_request(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_routing delegates to wiring.send_request()."""
        expected_recommendations = [
            {
                "agent_name": "agent-api-architect",
                "agent_title": "API Architect",
                "confidence": {"total": 0.95},
                "reason": "High match for API design",
            }
        ]
        # Response must have payload.recommendations structure
        mock_wiring.send_request = AsyncMock(
            return_value={"payload": {"recommendations": expected_recommendations}}
        )

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.request_routing(
                user_request="design an API for user management",
                max_recommendations=3,
            )

            assert result == expected_recommendations
            mock_wiring.send_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_routing_passes_correct_payload_structure(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_routing sends correctly structured payload."""
        mock_wiring.send_request = AsyncMock(
            return_value={"payload": {"recommendations": []}}
        )

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_routing(
                user_request="test request",
                context={"key": "value"},
                max_recommendations=5,
                min_confidence=0.7,
                routing_strategy="fuzzy",
            )

            call_args = mock_wiring.send_request.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")

            # Verify payload structure
            assert "correlation_id" in payload
            assert "payload" in payload
            inner_payload = payload["payload"]
            assert inner_payload["user_request"] == "test request"
            assert inner_payload["context"] == {"key": "value"}
            assert inner_payload["options"]["max_recommendations"] == 5
            assert inner_payload["options"]["min_confidence"] == 0.7
            assert inner_payload["options"]["routing_strategy"] == "fuzzy"

    @pytest.mark.asyncio
    async def test_request_routing_error_wraps_in_onex_error(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_routing wraps exceptions in OnexError."""
        mock_wiring.send_request = AsyncMock(
            side_effect=Exception("Kafka connection failed")
        )

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            with pytest.raises(OnexError) as exc_info:
                await client.request_routing(user_request="test request")

            # Verify the error message contains expected text
            assert "Routing request failed" in str(exc_info.value.message)

    @pytest.mark.asyncio
    async def test_request_routing_uses_custom_timeout(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_routing respects custom timeout_ms."""
        mock_wiring.send_request = AsyncMock(
            return_value={"payload": {"recommendations": []}}
        )

        with patch.object(routing_module, "settings", mock_settings):
            client = RoutingEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_routing(
                user_request="test",
                timeout_ms=10000,
            )

            call_args = mock_wiring.send_request.call_args
            timeout_seconds = call_args.kwargs.get("timeout_seconds") or call_args[
                1
            ].get("timeout_seconds")
            assert timeout_seconds == 10  # 10000ms / 1000


class TestRoutingEventClientContext:
    """Tests for RoutingEventClientContext context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_calls_start_and_stop(self, mock_settings) -> None:
        """Test context manager calls start() on entry and stop() on exit."""
        with patch.object(routing_module, "settings", mock_settings):
            # Create context manager
            ctx = RoutingEventClientContext(bootstrap_servers="localhost:9092")

            # Mock the client methods
            ctx.client.start = AsyncMock()
            ctx.client.stop = AsyncMock()

            async with ctx as client:
                assert client is ctx.client
                ctx.client.start.assert_called_once()

            ctx.client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_stops_on_exception(self, mock_settings) -> None:
        """Test context manager calls stop() even when exception occurs."""
        with patch.object(routing_module, "settings", mock_settings):
            ctx = RoutingEventClientContext(bootstrap_servers="localhost:9092")
            ctx.client.start = AsyncMock()
            ctx.client.stop = AsyncMock()

            with pytest.raises(ValueError):
                async with ctx:
                    raise ValueError("Test exception")

            ctx.client.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_does_not_suppress_exception(
        self, mock_settings
    ) -> None:
        """Test context manager does not suppress exceptions (returns False)."""
        with patch.object(routing_module, "settings", mock_settings):
            ctx = RoutingEventClientContext(bootstrap_servers="localhost:9092")
            ctx.client.start = AsyncMock()
            ctx.client.stop = AsyncMock()

            with pytest.raises(RuntimeError) as exc_info:
                async with ctx:
                    raise RuntimeError("Should propagate")

            assert "Should propagate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_context_manager_accepts_timeout_parameter(
        self, mock_settings
    ) -> None:
        """Test context manager passes request_timeout_ms to client."""
        with patch.object(routing_module, "settings", mock_settings):
            ctx = RoutingEventClientContext(
                bootstrap_servers="localhost:9092",
                request_timeout_ms=10000,
            )

            assert ctx.client.request_timeout_ms == 10000


class TestRouteViaEvents:
    """Tests for route_via_events() convenience function."""

    @pytest.mark.asyncio
    async def test_falls_back_to_local_when_event_routing_disabled(
        self, mock_settings
    ) -> None:
        """Test route_via_events uses local AgentRouter when USE_EVENT_ROUTING=false."""
        mock_settings.use_event_routing = False

        mock_router = MagicMock()
        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-local"
        mock_recommendation.agent_title = "Local Agent"
        mock_recommendation.confidence.total = 0.85
        mock_recommendation.confidence.trigger_score = 0.8
        mock_recommendation.confidence.context_score = 0.85
        mock_recommendation.confidence.capability_score = 0.9
        mock_recommendation.confidence.historical_score = 0.85
        mock_recommendation.confidence.explanation = "Local match"
        mock_recommendation.reason = "Local reason"
        mock_recommendation.definition_path = "/path/to/local.yaml"

        mock_router.route.return_value = [mock_recommendation]

        # AgentRouter is imported locally in the function, so patch at source module
        with (
            patch.object(routing_module, "settings", mock_settings),
            patch(
                "omniclaude.lib.core.agent_router.AgentRouter", return_value=mock_router
            ),
        ):
            result = await route_via_events(
                user_request="test request",
                fallback_to_local=True,
            )

            mock_router.route.assert_called_once()
            assert result[0]["agent_name"] == "agent-local"

    @pytest.mark.asyncio
    async def test_uses_event_routing_when_enabled(self, mock_settings) -> None:
        """Test route_via_events uses event-based routing when enabled."""
        mock_settings.use_event_routing = True

        # Setup mock context manager
        mock_client = MagicMock()
        mock_client.request_routing = AsyncMock(
            return_value=[
                {
                    "agent_name": "agent-event",
                    "confidence": {"total": 0.95},
                }
            ]
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(routing_module, "settings", mock_settings),
            patch.object(
                routing_module, "RoutingEventClientContext", return_value=mock_context
            ),
        ):
            result = await route_via_events(
                user_request="test request",
                max_recommendations=5,
                min_confidence=0.6,
                timeout_ms=5000,
            )

            mock_client.request_routing.assert_called_once()
            assert result[0]["agent_name"] == "agent-event"

    @pytest.mark.asyncio
    async def test_falls_back_to_local_on_kafka_error(self, mock_settings) -> None:
        """Test route_via_events falls back to local AgentRouter on Kafka error."""
        mock_settings.use_event_routing = True

        # Setup mock context to raise error
        mock_client = MagicMock()
        mock_client.request_routing = AsyncMock(
            side_effect=OnexError(
                code="OPERATION_FAILED",
                message="Kafka error",
            )
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        # Setup mock local router
        mock_router = MagicMock()
        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-fallback"
        mock_recommendation.agent_title = "Fallback Agent"
        mock_recommendation.confidence.total = 0.75
        mock_recommendation.confidence.trigger_score = 0.7
        mock_recommendation.confidence.context_score = 0.75
        mock_recommendation.confidence.capability_score = 0.8
        mock_recommendation.confidence.historical_score = 0.75
        mock_recommendation.confidence.explanation = "Fallback match"
        mock_recommendation.reason = "Fallback reason"
        mock_recommendation.definition_path = "/path/to/fallback.yaml"

        mock_router.route.return_value = [mock_recommendation]

        # AgentRouter is imported locally in the function, so patch at source module
        with (
            patch.object(routing_module, "settings", mock_settings),
            patch.object(
                routing_module, "RoutingEventClientContext", return_value=mock_context
            ),
            patch(
                "omniclaude.lib.core.agent_router.AgentRouter", return_value=mock_router
            ),
        ):
            result = await route_via_events(
                user_request="test request",
                fallback_to_local=True,
            )

            mock_router.route.assert_called_once()
            assert result[0]["agent_name"] == "agent-fallback"

    @pytest.mark.asyncio
    async def test_raises_error_when_fallback_disabled(self, mock_settings) -> None:
        """Test route_via_events raises error when fallback disabled and event routing fails."""
        mock_settings.use_event_routing = True

        mock_client = MagicMock()
        mock_client.request_routing = AsyncMock(
            side_effect=OnexError(
                code="OPERATION_FAILED",
                message="Kafka error",
            )
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(routing_module, "settings", mock_settings),
            patch.object(
                routing_module, "RoutingEventClientContext", return_value=mock_context
            ),
        ):
            with pytest.raises(OnexError):
                await route_via_events(
                    user_request="test request",
                    fallback_to_local=False,
                )

    @pytest.mark.asyncio
    async def test_raises_combined_error_when_both_fail(self, mock_settings) -> None:
        """Test route_via_events raises OnexError with both errors when all routing fails."""
        mock_settings.use_event_routing = True

        # Event routing fails
        mock_client = MagicMock()
        mock_client.request_routing = AsyncMock(
            side_effect=OnexError(code="OPERATION_FAILED", message="Kafka error")
        )

        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(return_value=mock_client)
        mock_context.__aexit__ = AsyncMock(return_value=False)

        # Local routing also fails
        mock_router = MagicMock()
        mock_router.route.side_effect = Exception("Local router error")

        # AgentRouter is imported locally in the function, so patch at source module
        with (
            patch.object(routing_module, "settings", mock_settings),
            patch.object(
                routing_module, "RoutingEventClientContext", return_value=mock_context
            ),
            patch(
                "omniclaude.lib.core.agent_router.AgentRouter", return_value=mock_router
            ),
        ):
            with pytest.raises(OnexError) as exc_info:
                await route_via_events(
                    user_request="test request",
                    fallback_to_local=True,
                )

            # Verify the error message contains expected text
            assert "Both event-based and local routing failed" in str(
                exc_info.value.message
            )


class TestFormatRecommendations:
    """Tests for _format_recommendations() helper function."""

    def test_format_recommendations_converts_objects_to_dicts(self) -> None:
        """Test that _format_recommendations properly converts recommendation objects."""
        mock_recommendation = MagicMock()
        mock_recommendation.agent_name = "agent-test"
        mock_recommendation.agent_title = "Test Agent"
        mock_recommendation.confidence.total = 0.9
        mock_recommendation.confidence.trigger_score = 0.85
        mock_recommendation.confidence.context_score = 0.88
        mock_recommendation.confidence.capability_score = 0.92
        mock_recommendation.confidence.historical_score = 0.95
        mock_recommendation.confidence.explanation = "Good match"
        mock_recommendation.reason = "Test reason"
        mock_recommendation.definition_path = "/path/to/agent.yaml"

        result = _format_recommendations([mock_recommendation])

        assert len(result) == 1
        assert result[0]["agent_name"] == "agent-test"
        assert result[0]["agent_title"] == "Test Agent"
        assert result[0]["confidence"]["total"] == 0.9
        assert result[0]["reason"] == "Test reason"
        assert result[0]["definition_path"] == "/path/to/agent.yaml"

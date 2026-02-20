# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for IntelligenceEventClient - Kafka-based intelligence discovery.

These tests verify:
- IntelligenceEventClient initialization and configuration validation
- start() / stop() lifecycle management
- request_pattern_discovery() with mocked RequestResponseWiring
- request_code_analysis() with mocked RequestResponseWiring
- Health check functionality

All Kafka and RequestResponseWiring operations are mocked via conftest.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Note: omnibase_infra mocking is handled by conftest.py which loads before this file
# Import the module under test
import omniclaude.lib.core.intelligence_event_client as intelligence_module
from omniclaude.lib.core.intelligence_event_client import (
    IntelligenceEventClient,
    IntelligenceEventClientContext,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings for tests."""
    settings_mock = MagicMock()
    settings_mock.get_effective_kafka_bootstrap_servers.return_value = "localhost:9092"
    settings_mock.kafka_environment = "dev"
    return settings_mock


@pytest.fixture
def mock_wiring():
    """Create mock RequestResponseWiring."""
    wiring = MagicMock()
    wiring.wire_request_response = AsyncMock()
    # Intelligence client returns result.get("payload", result) from send_request
    wiring.send_request = AsyncMock(return_value={"payload": {"patterns": []}})
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


class TestIntelligenceEventClientInitialization:
    """Tests for IntelligenceEventClient initialization."""

    def test_initialization_with_explicit_bootstrap_servers(
        self, mock_settings
    ) -> None:
        """Test client initialization with explicit bootstrap_servers."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(
                bootstrap_servers="localhost:9092",
                enable_intelligence=True,
                request_timeout_ms=3000,
            )

            assert client.bootstrap_servers == "localhost:9092"
            assert client.enable_intelligence is True
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

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient()

            assert client.bootstrap_servers == "kafka.example.com:9092"

    def test_initialization_fails_without_bootstrap_servers(
        self, mock_settings
    ) -> None:
        """Test client raises OnexError when no bootstrap servers configured."""
        mock_settings.get_effective_kafka_bootstrap_servers.return_value = None

        from omniclaude.lib.errors import OnexError

        with patch.object(intelligence_module, "settings", mock_settings):
            with pytest.raises(OnexError) as exc_info:
                IntelligenceEventClient()

            assert "bootstrap_servers" in str(exc_info.value.message)

    def test_initialization_with_intelligence_disabled(self, mock_settings) -> None:
        """Test client can be initialized with intelligence disabled."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(
                bootstrap_servers="localhost:9092",
                enable_intelligence=False,
            )

            assert client.enable_intelligence is False

    def test_topic_names_follow_event_bus_convention(self, mock_settings) -> None:
        """Test that topic names follow onex.cmd/evt convention (OMN-2367)."""
        # Check class-level topic constants (no instantiation needed)
        assert (
            IntelligenceEventClient.TOPIC_REQUEST
            == "onex.cmd.omniintelligence.code-analysis.v1"
        )
        assert (
            IntelligenceEventClient.TOPIC_COMPLETED
            == "onex.evt.omniintelligence.code-analysis-completed.v1"
        )
        assert (
            IntelligenceEventClient.TOPIC_FAILED
            == "onex.evt.omniintelligence.code-analysis-failed.v1"
        )


class TestIntelligenceEventClientLifecycle:
    """Tests for IntelligenceEventClient start() and stop() lifecycle."""

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, mock_settings) -> None:
        """Test that calling start() multiple times is safe."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True

            await client.start()

            assert client._started is True

    @pytest.mark.asyncio
    async def test_start_returns_early_when_intelligence_disabled(
        self, mock_settings
    ) -> None:
        """Test that start() returns early when enable_intelligence is False."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(
                bootstrap_servers="localhost:9092",
                enable_intelligence=False,
            )

            await client.start()

            # Should not be marked as started since intelligence is disabled
            assert client._started is False
            assert client._wiring is None
            assert client._event_bus is None

    @pytest.mark.asyncio
    async def test_stop_cleans_up_resources(
        self, mock_settings, mock_wiring, mock_event_bus
    ) -> None:
        """Test that stop() properly cleans up all resources."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
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
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")

            # Should not raise
            await client.stop()

            assert client._started is False

    @pytest.mark.asyncio
    async def test_stop_handles_partial_initialization(
        self, mock_settings, mock_event_bus
    ) -> None:
        """Test stop() works even with partial initialization (no wiring)."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = None
            client._event_bus = mock_event_bus

            await client.stop()

            assert client._started is False
            mock_event_bus.stop.assert_called_once()


class TestIntelligenceEventClientHealthCheck:
    """Tests for IntelligenceEventClient health_check()."""

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_not_started(
        self, mock_settings
    ) -> None:
        """Test health_check returns False when client not started."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_intelligence_disabled(
        self, mock_settings
    ) -> None:
        """Test health_check returns False when intelligence is disabled."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(
                bootstrap_servers="localhost:9092",
                enable_intelligence=False,
            )
            client._started = True  # Even if somehow started

            result = await client.health_check()

            assert result is False

    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_started_with_wiring(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test health_check returns True when client is started with wiring."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.health_check()

            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_wiring_is_none(
        self, mock_settings
    ) -> None:
        """Test health_check returns False when wiring is None."""
        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = None

            result = await client.health_check()

            assert result is False


class TestIntelligenceEventClientRequestPatternDiscovery:
    """Tests for IntelligenceEventClient request_pattern_discovery()."""

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_fails_when_not_started(
        self, mock_settings
    ) -> None:
        """Test request_pattern_discovery raises OnexError when not started."""
        from omniclaude.lib.errors import OnexError

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")

            with pytest.raises(OnexError) as exc_info:
                await client.request_pattern_discovery(
                    source_path="node_*_effect.py",
                    language="python",
                )

            assert "not started" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_uses_wiring(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_pattern_discovery delegates to wiring.send_request()."""
        expected_patterns = [
            {"file_path": "node_foo_effect.py", "confidence": 0.95},
            {"file_path": "node_bar_effect.py", "confidence": 0.85},
        ]
        # Response structure: result.get("payload", result) then .get("patterns", [])
        mock_wiring.send_request = AsyncMock(
            return_value={"payload": {"patterns": expected_patterns}}
        )

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.request_pattern_discovery(
                source_path="node_*_effect.py",
                language="python",
                timeout_ms=5000,
            )

            mock_wiring.send_request.assert_called_once()
            assert result == expected_patterns

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_reads_file_content(
        self, mock_settings, mock_wiring, tmp_path
    ) -> None:
        """Test request_pattern_discovery reads file content if file exists."""
        test_file = tmp_path / "test_node.py"
        test_content = "class NodeTestEffect:\n    pass"
        test_file.write_text(test_content)

        mock_wiring.send_request = AsyncMock(return_value={"payload": {"patterns": []}})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_pattern_discovery(
                source_path=str(test_file),
                language="python",
            )

            # Verify that send_request was called with content
            call_args = mock_wiring.send_request.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")
            inner_payload = payload.get("payload", {})
            assert inner_payload.get("content") == test_content


class TestIntelligenceEventClientRequestCodeAnalysis:
    """Tests for IntelligenceEventClient request_code_analysis()."""

    @pytest.mark.asyncio
    async def test_request_code_analysis_fails_when_not_started(
        self, mock_settings
    ) -> None:
        """Test request_code_analysis raises OnexError when not started."""
        from omniclaude.lib.errors import OnexError

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")

            with pytest.raises(OnexError) as exc_info:
                await client.request_code_analysis(
                    content="def hello(): pass",
                    source_path="test.py",
                    language="python",
                )

            assert "not started" in str(exc_info.value.message).lower()

    @pytest.mark.asyncio
    async def test_request_code_analysis_uses_wiring(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis delegates to wiring.send_request()."""
        expected_result = {
            "quality_score": 0.85,
            "onex_compliance": 0.90,
            "patterns": [],
            "issues": [],
            "recommendations": ["Add docstring"],
        }
        # The method returns result.get("payload", result)
        mock_wiring.send_request = AsyncMock(return_value={"payload": expected_result})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                options={"operation_type": "QUALITY_ASSESSMENT"},
            )

            assert result == expected_result
            mock_wiring.send_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_code_analysis_passes_correct_payload_structure(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis sends correctly structured payload."""
        mock_wiring.send_request = AsyncMock(return_value={"payload": {}})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                options={
                    "operation_type": "PATTERN_EXTRACTION",
                    "include_patterns": True,
                },
            )

            call_args = mock_wiring.send_request.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")

            # Verify top-level structure
            assert "event_type" in payload
            assert "event_id" in payload
            assert "correlation_id" in payload
            assert "timestamp" in payload

            # Verify inner payload
            inner_payload = payload["payload"]
            assert inner_payload["source_path"] == "test.py"
            assert inner_payload["content"] == "def hello(): pass"
            assert inner_payload["language"] == "python"
            assert inner_payload["operation_type"] == "PATTERN_EXTRACTION"

    @pytest.mark.asyncio
    async def test_request_code_analysis_timeout_raises_timeout_error(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis raises TimeoutError when TimeoutError occurs."""
        # Simulate RequestResponseWiring raising TimeoutError
        mock_wiring.send_request = AsyncMock(side_effect=TimeoutError())

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            with pytest.raises(TimeoutError) as exc_info:
                await client.request_code_analysis(
                    content="def hello(): pass",
                    source_path="test.py",
                    language="python",
                    timeout_ms=100,
                )

            # The custom TimeoutError includes "timeout" and correlation_id
            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_request_code_analysis_non_timeout_error_propagates(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis re-raises non-timeout exceptions."""
        mock_wiring.send_request = AsyncMock(
            side_effect=Exception("Kafka connection failed")
        )

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            with pytest.raises(Exception) as exc_info:
                await client.request_code_analysis(
                    content="def hello(): pass",
                    source_path="test.py",
                    language="python",
                )

            # Original exception propagates
            assert "Kafka connection failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_request_code_analysis_uses_custom_timeout(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis respects custom timeout_ms."""
        mock_wiring.send_request = AsyncMock(return_value={"payload": {}})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                timeout_ms=15000,
            )

            call_args = mock_wiring.send_request.call_args
            timeout_seconds = call_args.kwargs.get("timeout_seconds") or call_args[
                1
            ].get("timeout_seconds")
            assert timeout_seconds == 15  # 15000ms / 1000

    @pytest.mark.asyncio
    async def test_request_code_analysis_uses_injected_timestamp(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_code_analysis uses emitted_at when provided (deterministic testing)."""
        fixed_ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
        mock_wiring.send_request = AsyncMock(return_value={"payload": {}})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                emitted_at=fixed_ts,
            )

            call_args = mock_wiring.send_request.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")
            assert payload["timestamp"] == fixed_ts.isoformat()

    @pytest.mark.asyncio
    async def test_request_pattern_discovery_passes_emitted_at_through(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test request_pattern_discovery forwards emitted_at to request_code_analysis."""
        fixed_ts = datetime(2025, 6, 30, 8, 0, 0, tzinfo=UTC)
        mock_wiring.send_request = AsyncMock(return_value={"payload": {"patterns": []}})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            await client.request_pattern_discovery(
                source_path="nonexistent_node.py",
                language="python",
                emitted_at=fixed_ts,
            )

            call_args = mock_wiring.send_request.call_args
            payload = call_args.kwargs.get("payload") or call_args[1].get("payload")
            assert payload["timestamp"] == fixed_ts.isoformat()


class TestIntelligenceEventClientContext:
    """Tests for IntelligenceEventClientContext context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_calls_start_and_stop(self, mock_settings) -> None:
        """Test context manager calls start() on entry and stop() on exit."""
        with patch.object(intelligence_module, "settings", mock_settings):
            # Create context manager
            ctx = IntelligenceEventClientContext(bootstrap_servers="localhost:9092")

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
        with patch.object(intelligence_module, "settings", mock_settings):
            ctx = IntelligenceEventClientContext(bootstrap_servers="localhost:9092")
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
        with patch.object(intelligence_module, "settings", mock_settings):
            ctx = IntelligenceEventClientContext(bootstrap_servers="localhost:9092")
            ctx.client.start = AsyncMock()
            ctx.client.stop = AsyncMock()

            with pytest.raises(RuntimeError) as exc_info:
                async with ctx:
                    raise RuntimeError("Should propagate")

            assert "Should propagate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_context_manager_with_custom_parameters(self, mock_settings) -> None:
        """Test context manager passes custom parameters to client."""
        with patch.object(intelligence_module, "settings", mock_settings):
            ctx = IntelligenceEventClientContext(
                bootstrap_servers="custom:9092",
                enable_intelligence=False,
                request_timeout_ms=10000,
            )

            assert ctx.client.bootstrap_servers == "custom:9092"
            assert ctx.client.enable_intelligence is False
            assert ctx.client.request_timeout_ms == 10000


class TestIntelligenceEventClientIntegration:
    """Integration-style tests for IntelligenceEventClient workflows."""

    @pytest.mark.asyncio
    async def test_full_pattern_discovery_workflow(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test complete workflow: create client, request patterns, cleanup."""
        expected_patterns = [
            {"pattern": "Effect Node", "confidence": 0.95},
            {"pattern": "Compute Node", "confidence": 0.88},
        ]
        mock_wiring.send_request = AsyncMock(
            return_value={"payload": {"patterns": expected_patterns}}
        )

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.request_pattern_discovery(
                source_path="src/nodes/",
                language="python",
            )

            assert len(result) == 2
            assert result[0]["pattern"] == "Effect Node"

    @pytest.mark.asyncio
    async def test_full_code_analysis_workflow(
        self, mock_settings, mock_wiring
    ) -> None:
        """Test complete code analysis workflow."""
        code = """
class NodeUserEffect:
    async def execute_effect(self, request):
        return await self.api.get_user(request.user_id)
"""
        expected_result = {
            "quality_score": 0.92,
            "onex_compliance": 0.95,
            "patterns": [{"name": "Effect Node", "confidence": 0.95}],
            "issues": [],
            "recommendations": [],
        }
        mock_wiring.send_request = AsyncMock(return_value={"payload": expected_result})

        with patch.object(intelligence_module, "settings", mock_settings):
            client = IntelligenceEventClient(bootstrap_servers="localhost:9092")
            client._started = True
            client._wiring = mock_wiring

            result = await client.request_code_analysis(
                content=code,
                source_path="node_user_effect.py",
                language="python",
                options={"operation_type": "QUALITY_ASSESSMENT"},
            )

            assert result["quality_score"] == 0.92
            assert result["onex_compliance"] == 0.95
            assert len(result["patterns"]) == 1

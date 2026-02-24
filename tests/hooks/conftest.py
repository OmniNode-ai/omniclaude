# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Test fixtures for hook tests.

This conftest provides fixtures specifically for hook tests, including
configuration for integration tests that require real Kafka.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from importlib import reload
from pathlib import Path

import pytest

# Ensure src is in path for imports
_src_path = str(Path(__file__).parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# =============================================================================
# Shared test data factories
# =============================================================================


@dataclass(frozen=True)
class MockPatternRecord:
    """Mock PatternRecord for testing without importing handler module."""

    pattern_id: str
    domain: str
    title: str
    description: str
    confidence: float
    usage_count: int
    success_rate: float
    example_reference: str | None = None
    lifecycle_state: str | None = None
    evidence_tier: str | None = None


def make_pattern(
    pattern_id: str = "pat-001",
    domain: str = "testing",
    title: str = "Test Pattern",
    description: str = "A test pattern description",
    confidence: float = 0.9,
    usage_count: int = 10,
    success_rate: float = 0.8,
    example_reference: str | None = None,
    lifecycle_state: str | None = None,
    evidence_tier: str | None = None,
) -> MockPatternRecord:
    """Create a mock pattern with defaults."""
    return MockPatternRecord(
        pattern_id=pattern_id,
        domain=domain,
        title=title,
        description=description,
        confidence=confidence,
        usage_count=usage_count,
        success_rate=success_rate,
        example_reference=example_reference,
        lifecycle_state=lifecycle_state,
        evidence_tier=evidence_tier,
    )


# =============================================================================
# Kafka integration test support
# =============================================================================

# Track if we've already restored the real Kafka producer
_kafka_restored = False


def _patch_event_bus_acks_conversion():
    """Patch EventBusKafka to properly convert acks string to int.

    aiokafka requires acks to be an integer (0, 1, -1) or the string "all".
    However, ModelKafkaEventBusConfig stores acks as a string ("0", "1", "all").
    This patch converts numeric strings to integers before passing to aiokafka.

    This is a workaround for a bug in omnibase_infra.EventBusKafka.
    """
    try:
        from aiokafka import AIOKafkaProducer

        original_init = AIOKafkaProducer.__init__

        def patched_init(self, *args, **kwargs):
            """Patched init that converts acks string to proper type."""
            if "acks" in kwargs:
                acks = kwargs["acks"]
                if acks == "1":
                    kwargs["acks"] = 1
                elif acks == "0":
                    kwargs["acks"] = 0
                elif acks == "-1":
                    kwargs["acks"] = -1
                # "all" is already valid as string
            return original_init(self, *args, **kwargs)

        AIOKafkaProducer.__init__ = patched_init

    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Could not patch EventBusKafka acks conversion: {e}")


def _restore_real_kafka_producer():
    """Restore the real AIOKafkaProducer for integration tests.

    The global conftest.py mocks AIOKafkaProducer to prevent real connections.
    For integration tests, we need the real producer.

    This function also reloads dependent modules to ensure they pick up
    the real producer class.
    """
    global _kafka_restored
    if _kafka_restored:
        return

    try:
        import aiokafka
        import aiokafka.producer.producer as producer_module

        # Check if it's mocked (by looking at the class source)
        # The mock returns a MagicMock instance, not the real class
        if not hasattr(aiokafka.AIOKafkaProducer, "__mro__"):
            # It's mocked, restore from the actual module
            # Re-import the real producer by reloading the module
            reload(producer_module)
            aiokafka.AIOKafkaProducer = producer_module.AIOKafkaProducer

            if "aiokafka" in sys.modules:
                sys.modules[
                    "aiokafka"
                ].AIOKafkaProducer = producer_module.AIOKafkaProducer

            # Also reload the EventBusKafka module to pick up the real producer
            # This is necessary because EventBusKafka imports AIOKafkaProducer at import time
            try:
                import omnibase_infra.event_bus.event_bus_kafka as event_bus_module

                reload(event_bus_module)
            except ImportError:
                pass

            # Reload the handler_event_emitter to pick up the reloaded EventBusKafka
            try:
                import omniclaude.hooks.handler_event_emitter as emitter_module

                reload(emitter_module)
            except ImportError:
                pass

            # Patch EventBusKafka to convert acks string to int
            # This works around a bug where aiokafka requires acks to be int (1, 0, -1) or "all"
            # but the config model stores it as string ("1", "0", "all")
            _patch_event_bus_acks_conversion()

            print("Restored real AIOKafkaProducer for integration tests")

        _kafka_restored = True
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: Could not restore real Kafka producer: {e}")


@pytest.fixture(scope="module", autouse=True)
def restore_kafka_for_integration():
    """Restore real Kafka producer for integration test modules.

    This fixture runs before each test module in the hooks/tests directory.
    If KAFKA_INTEGRATION_TESTS=1, it restores the real AIOKafkaProducer
    that was mocked by the global conftest.

    Also sets KAFKA_HOOK_TIMEOUT_SECONDS to a higher value (30s) for
    integration tests, as the default 2s timeout is too aggressive for
    remote Kafka brokers that may take longer to connect.
    """
    original_timeout = os.environ.get("KAFKA_HOOK_TIMEOUT_SECONDS")

    if os.getenv("KAFKA_INTEGRATION_TESTS") == "1":
        _restore_real_kafka_producer()
        # Set a longer timeout for integration tests (30 seconds)
        # The default 2 seconds is too short for remote brokers
        if original_timeout is None:
            os.environ["KAFKA_HOOK_TIMEOUT_SECONDS"] = "30"

    yield

    # Restore original timeout setting
    if original_timeout is None:
        os.environ.pop("KAFKA_HOOK_TIMEOUT_SECONDS", None)
    else:
        os.environ["KAFKA_HOOK_TIMEOUT_SECONDS"] = original_timeout


@pytest.fixture(scope="session")
def kafka_bootstrap_servers() -> str:
    """Get the Kafka bootstrap servers from environment.

    Raises:
        RuntimeError: If KAFKA_BOOTSTRAP_SERVERS is not set.
    """
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS environment variable is required")
    return servers


@pytest.fixture(scope="session")
def kafka_environment() -> str:
    """Get the Kafka environment prefix from environment."""
    return os.environ.get("KAFKA_ENVIRONMENT", "dev")


@pytest.fixture
def integration_test_marker():
    """Marker fixture to indicate this is an integration test.

    Use this fixture in tests that require real infrastructure.
    """
    if os.getenv("KAFKA_INTEGRATION_TESTS") != "1":
        pytest.skip("Integration tests disabled. Set KAFKA_INTEGRATION_TESTS=1 to run.")
    return True

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
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
    return os.environ.get("KAFKA_ENVIRONMENT", "")


@pytest.fixture
def integration_test_marker():
    """Marker fixture to indicate this is an integration test.

    Use this fixture in tests that require real infrastructure.
    """
    if os.getenv("KAFKA_INTEGRATION_TESTS") != "1":
        pytest.skip("Integration tests disabled. Set KAFKA_INTEGRATION_TESTS=1 to run.")
    return True


def pytest_configure(config: pytest.Config) -> None:
    """Fast-fail guard: detect missing POSTGRES_USER when a DB URL is present.

    When DATABASE_URL or OMNICLAUDE_DB_URL is set but POSTGRES_USER is not,
    psycopg2 falls back to the OS username (e.g. ``root`` on self-hosted CI
    runners), producing the opaque error ``role "root" does not exist``.

    This hook fires before any tests run and emits a clear error message so
    the developer knows exactly which variable to add.

    The check is skipped when neither DB URL var is set (unit-only run with no
    real database required).
    """
    has_db_url = bool(
        os.environ.get("DATABASE_URL") or os.environ.get("OMNICLAUDE_DB_URL")
    )
    has_postgres_user = bool(os.environ.get("POSTGRES_USER"))

    if has_db_url and not has_postgres_user:
        import warnings

        warnings.warn(
            "[OMN-4048] POSTGRES_USER is not set but DATABASE_URL/OMNICLAUDE_DB_URL is. "
            "psycopg2 will fall back to the OS username (e.g. 'root' on CI runners), "
            "causing 'role does not exist' errors. "
            "Set POSTGRES_USER in the test environment to fix this.",
            stacklevel=1,
        )


# =============================================================================
# Outbound-alert containment (OMN-17958)
# =============================================================================

#: Every environment variable that can turn a hook test into a real outbound
#: notification. Scrubbing these from ``os.environ`` covers BOTH in-process
#: harnesses (which read ``os.environ`` directly) and subprocess harnesses
#: (which inherit it), so one fixture closes the whole tree.
#:
#: Why this exists: on 2026-09-05T13:48:28-30Z a hook-suite run on a developer
#: Mac delivered twelve real HARD_BLOCK alerts into #omninode-notifications —
#: the six ``test_main_hard_blocks_*`` fixtures in ``test_bash_guard.py``
#: (``rm -rf /``, ``mkfs.ext4 /dev/sda``, ``dd of=/dev/sda1``,
#: ``base64 -d … | sh``, ``git commit --no-verify``, ``git push --no-verify``),
#: each twice because ``TestMainIntegrationViapytest`` re-runs the inherited
#: class. Those tests call ``bash_guard.main()`` for real and neither cleared
#: the environment nor patched the notifier, so the ambient developer shell's
#: ``SLACK_BOT_TOKEN`` / ``SLACK_CHANNEL_ID`` made delivery succeed.
OUTBOUND_ALERT_ENV_VARS: tuple[str, ...] = (
    "SLACK_BOT_TOKEN",
    "SLACK_CHANNEL_ID",
    "SLACK_WEBHOOK_URL",
    "SLACK_APP_TOKEN",
    "SLACK_SIGNING_SECRET",
    "SLACK_USER_TOKEN",
    "DISCORD_WEBHOOK_URL",
    "PAGERDUTY_ROUTING_KEY",
    "LINEAR_WEBHOOK_SECRET",
    "ONEX_ALERT_LOCAL_NOTIFY_CMD",
)

#: Marker the hooks read to make notification delivery a no-op. Test-only:
#: set here by the harness, never by product code or a shell wrapper.
HOOK_TEST_MODE_ENV = "ONEX_HOOK_TEST_MODE"

#: Any residual code path that still builds a Slack URL is pointed at a
#: reserved-for-documentation address (RFC 5737 TEST-NET-1) rather than the
#: real API host, so a missed call site fails to connect instead of posting.
UNREACHABLE_SLACK_API_BASE = "http://192.0.2.1:9/api"  # onex-allow-internal-ip: RFC 5737 TEST-NET-1 blackhole, deliberately unroutable


@pytest.fixture(autouse=True)
def _contain_outbound_alerts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make it impossible for a hook test to notify a live channel.

    Autouse across the whole ``tests/hooks`` tree, and deliberately belt-and-
    braces:

    1. Every credential in :data:`OUTBOUND_ALERT_ENV_VARS` is deleted, so no
       call site can authenticate — this is what actually stops delivery, and
       it protects subprocess harnesses too, since a child inherits the
       scrubbed environment.
    2. :data:`HOOK_TEST_MODE_ENV` is set, so the guards refuse to deliver even
       if a credential is ever reintroduced, and record the refusal on the
       hook ledger instead of dropping it silently.
    3. Any leftover Slack base URL points at an unroutable blackhole.

    A test that genuinely needs to exercise delivery must patch the sender
    (``patch.object(module, "_send_slack_alert")``) — never re-add a real
    token to the environment.
    """
    for var in OUTBOUND_ALERT_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(HOOK_TEST_MODE_ENV, "1")
    monkeypatch.setenv("SLACK_API_BASE_URL", UNREACHABLE_SLACK_API_BASE)

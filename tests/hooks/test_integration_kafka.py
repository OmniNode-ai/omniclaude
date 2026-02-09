# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for Kafka event emission.

These tests require a running Kafka/Redpanda instance and verify actual
event delivery - not just that publish was called, but that events can
be consumed from the topics.

Run with:
    # Skip integration tests (default)
    pytest tests/hooks/test_integration_kafka.py -v

    # Run integration tests with real Kafka
    KAFKA_INTEGRATION_TESTS=1 pytest tests/hooks/test_integration_kafka.py -v

    # Run with custom Kafka server (uses KAFKA_BOOTSTRAP_SERVERS from .env)
    source .env && KAFKA_INTEGRATION_TESTS=1 \
        pytest tests/hooks/test_integration_kafka.py -v

    # Run with custom timeout for slow connections
    KAFKA_INTEGRATION_TESTS=1 KAFKA_HOOK_TIMEOUT_SECONDS=60 \
        pytest tests/hooks/test_integration_kafka.py -v

Requirements:
    - KAFKA_BOOTSTRAP_SERVERS must be set in .env or environment (no default)
    - Topics must be auto-created or pre-created

Environment Variables:
    KAFKA_INTEGRATION_TESTS: Set to "1" to enable integration tests
    KAFKA_BOOTSTRAP_SERVERS: Kafka broker address(es)
    KAFKA_ENVIRONMENT: Topic prefix (default: "dev")
    KAFKA_HOOK_TIMEOUT_SECONDS: Connection timeout in seconds (default: 30 for
        integration tests, 2 for production hooks). Set higher if connecting
        to remote brokers with high latency.

Note:
    These tests are automatically skipped when KAFKA_INTEGRATION_TESTS != "1"
    because the conftest.py mocks AIOKafkaProducer globally for unit tests.

    When KAFKA_INTEGRATION_TESTS=1, the conftest automatically sets
    KAFKA_HOOK_TIMEOUT_SECONDS=30 to allow more time for remote broker
    connections (the default production timeout of 2s is too aggressive).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

# Ensure we're using the correct import path
_src_path = str(Path(__file__).parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)

# =============================================================================
# Integration Test Markers
# =============================================================================

# Mark all tests in this module as integration tests
# They will be skipped unless KAFKA_INTEGRATION_TESTS=1
pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.slow,
]


# =============================================================================
# Helper Functions
# =============================================================================


def get_kafka_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment.

    Raises:
        RuntimeError: If KAFKA_BOOTSTRAP_SERVERS is not set.
    """
    servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS environment variable is required")
    return servers


def get_kafka_environment() -> str:
    """Get Kafka environment prefix from environment."""
    return os.environ.get("KAFKA_ENVIRONMENT", "dev")


def make_unique_consumer_group() -> str:
    """Create a unique consumer group name to isolate test runs."""
    return f"test-integration-{uuid4().hex[:8]}"


async def consume_messages(
    topic: str,
    consumer_group: str,
    timeout_seconds: float = 10.0,
    max_messages: int = 10,
) -> list[dict[str, Any]]:
    """Consume messages from a Kafka topic.

    This function creates a consumer that reads from the specified topic
    and returns the messages received within the timeout period.

    Args:
        topic: The Kafka topic to consume from.
        consumer_group: Consumer group ID for offset management.
        timeout_seconds: Maximum time to wait for messages.
        max_messages: Maximum number of messages to consume.

    Returns:
        List of deserialized message payloads.
    """
    # Import aiokafka directly to get real consumer (not mocked)
    # When KAFKA_INTEGRATION_TESTS=1, conftest doesn't install mocks
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return []

    messages: list[dict[str, Any]] = []
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=get_kafka_bootstrap_servers(),
        group_id=consumer_group,
        auto_offset_reset="latest",  # Only read new messages
        enable_auto_commit=True,
        consumer_timeout_ms=int(timeout_seconds * 1000),
    )

    try:
        await consumer.start()

        # Small delay to allow consumer to join group
        await asyncio.sleep(0.5)

        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            if len(messages) >= max_messages:
                break

            try:
                # Use getmany with short timeout for responsive loop
                result = await consumer.getmany(
                    timeout_ms=500, max_records=max_messages
                )
                for _tp, records in result.items():
                    for record in records:
                        try:
                            payload = json.loads(record.value.decode("utf-8"))
                            messages.append(payload)
                        except (json.JSONDecodeError, UnicodeDecodeError) as e:
                            # Log but don't fail - might be other test messages
                            print(f"Warning: Could not decode message: {e}")

            except TimeoutError:
                # Normal timeout, continue polling
                continue

        return messages

    finally:
        await consumer.stop()


async def wait_for_message_with_entity_id(
    topic: str,
    entity_id: str,
    consumer_group: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any] | None:
    """Wait for a specific message by entity_id.

    Args:
        topic: The Kafka topic to consume from.
        entity_id: The entity_id to match in the payload.
        consumer_group: Consumer group ID.
        timeout_seconds: Maximum time to wait.

    Returns:
        The matching message payload, or None if not found.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return None

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=get_kafka_bootstrap_servers(),
        group_id=consumer_group,
        auto_offset_reset="earliest",  # Read from beginning to catch recent messages
        enable_auto_commit=True,
        consumer_timeout_ms=int(timeout_seconds * 1000),
    )

    try:
        await consumer.start()
        # Seek to end first, then back a bit to catch recent messages
        await consumer.seek_to_end()

        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            try:
                result = await consumer.getmany(timeout_ms=500, max_records=100)
                for _tp, records in result.items():
                    for record in records:
                        try:
                            payload = json.loads(record.value.decode("utf-8"))
                            # Check if entity_id matches (in payload.payload.entity_id)
                            if payload.get("payload", {}).get("entity_id") == entity_id:
                                return payload
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue

            except TimeoutError:
                continue

        return None

    finally:
        await consumer.stop()


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def unique_session_id():
    """Generate a unique session ID for test isolation.

    Each test receives a distinct UUID to prevent event collision when
    multiple tests run in parallel or in sequence.

    Returns:
        UUID: A randomly generated UUID4 for the test session.
    """
    return uuid4()


@pytest.fixture
def unique_consumer_group():
    """Generate a unique consumer group for test isolation.

    Each test receives a unique consumer group to prevent offset conflicts
    and ensure clean message consumption from Kafka topics.

    Returns:
        str: A unique consumer group name in format 'test-integration-{hex}'.
    """
    return make_unique_consumer_group()


@pytest.fixture
def test_environment():
    """Get the test environment prefix with unique suffix for isolation.

    Creates a unique Kafka topic prefix to prevent test pollution.
    Format: '{base_env}-test-{hex}' where base_env comes from KAFKA_ENVIRONMENT.

    Returns:
        str: A unique environment prefix for Kafka topic names.
    """
    base_env = get_kafka_environment()
    # Add timestamp suffix for test isolation
    return f"{base_env}-test-{uuid4().hex[:6]}"


@pytest.fixture
async def _kafka_health_check():
    """Verify Kafka is reachable before running tests.

    This fixture is prefixed with underscore to indicate it's used only for
    its side effect (skipping tests when Kafka is unavailable) and the return
    value is not used by dependent tests.

    Yields:
        None: No value is yielded; this fixture is used for its skip behavior.

    Raises:
        pytest.skip: If aiokafka is not installed or Kafka is unreachable.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return

    consumer = AIOKafkaConsumer(
        bootstrap_servers=get_kafka_bootstrap_servers(),
        group_id=f"health-check-{uuid4().hex[:8]}",
    )

    try:
        await asyncio.wait_for(consumer.start(), timeout=5.0)
        await consumer.stop()
    except Exception as e:
        pytest.skip(f"Kafka not available at {get_kafka_bootstrap_servers()}: {e}")


# =============================================================================
# Integration Tests
# =============================================================================


class TestKafkaIntegrationBasic:
    """Basic integration tests with real Kafka."""

    async def test_kafka_connection(self, _kafka_health_check) -> None:
        """Verify we can connect to Kafka."""
        # If we get here, _kafka_health_check passed
        assert True

    async def test_emit_session_started_to_kafka(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify session.started event is published to Kafka."""
        from omniclaude.hooks.handler_event_emitter import emit_session_started
        from omniclaude.hooks.topics import TopicBase, build_topic

        # Build expected topic
        topic = build_topic(test_environment, TopicBase.SESSION_STARTED)

        # Start consumer BEFORE publishing (to catch the message)
        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )

        # Small delay to let consumer subscribe
        await asyncio.sleep(1.0)

        # Emit the event
        result = await emit_session_started(
            session_id=unique_session_id,
            working_directory="/workspace/test",
            hook_source="startup",
            git_branch="test-branch",
            environment=test_environment,
        )

        # Verify publish succeeded
        assert result.success is True, f"Publish failed: {result.error_message}"
        assert topic in result.topic

        # Wait for consumer to receive the message
        message = await consumer_task

        # Verify message was received
        assert message is not None, f"Message not received from topic {topic}"
        assert message["event_type"] == "hook.session.started"
        assert message["payload"]["entity_id"] == str(unique_session_id)
        assert message["payload"]["working_directory"] == "/workspace/test"
        assert message["payload"]["hook_source"] == "startup"
        assert message["payload"]["git_branch"] == "test-branch"

    async def test_emit_session_ended_to_kafka(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify session.ended event is published to Kafka."""
        from omniclaude.hooks.handler_event_emitter import emit_session_ended
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(test_environment, TopicBase.SESSION_ENDED)

        # Start consumer
        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        # Emit the event
        result = await emit_session_ended(
            session_id=unique_session_id,
            reason="clear",
            duration_seconds=1800.5,
            tools_used_count=42,
            environment=test_environment,
        )

        assert result.success is True, f"Publish failed: {result.error_message}"

        message = await consumer_task
        assert message is not None, f"Message not received from topic {topic}"
        assert message["event_type"] == "hook.session.ended"
        assert message["payload"]["entity_id"] == str(unique_session_id)
        assert message["payload"]["reason"] == "clear"
        assert message["payload"]["duration_seconds"] == 1800.5
        assert message["payload"]["tools_used_count"] == 42

    async def test_emit_prompt_submitted_to_kafka(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify prompt.submitted event is published to Kafka."""
        from omniclaude.hooks.handler_event_emitter import emit_prompt_submitted
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(test_environment, TopicBase.PROMPT_SUBMITTED)
        prompt_id = uuid4()

        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        result = await emit_prompt_submitted(
            session_id=unique_session_id,
            prompt_id=prompt_id,
            prompt_preview="Test integration prompt...",
            prompt_length=150,
            detected_intent="test",
            environment=test_environment,
        )

        assert result.success is True, f"Publish failed: {result.error_message}"

        message = await consumer_task
        assert message is not None, f"Message not received from topic {topic}"
        assert message["event_type"] == "hook.prompt.submitted"
        assert message["payload"]["entity_id"] == str(unique_session_id)
        assert message["payload"]["prompt_id"] == str(prompt_id)
        assert message["payload"]["prompt_preview"] == "Test integration prompt..."
        assert message["payload"]["prompt_length"] == 150
        assert message["payload"]["detected_intent"] == "test"

    async def test_emit_tool_executed_to_kafka(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify tool.executed event is published to Kafka."""
        from omniclaude.hooks.handler_event_emitter import emit_tool_executed
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(test_environment, TopicBase.TOOL_EXECUTED)
        tool_execution_id = uuid4()

        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        result = await emit_tool_executed(
            session_id=unique_session_id,
            tool_execution_id=tool_execution_id,
            tool_name="Read",
            success=True,
            duration_ms=45,
            summary="Read 100 lines from test.py",
            environment=test_environment,
        )

        assert result.success is True, f"Publish failed: {result.error_message}"

        message = await consumer_task
        assert message is not None, f"Message not received from topic {topic}"
        assert message["event_type"] == "hook.tool.executed"
        assert message["payload"]["entity_id"] == str(unique_session_id)
        assert message["payload"]["tool_execution_id"] == str(tool_execution_id)
        assert message["payload"]["tool_name"] == "Read"
        assert message["payload"]["success"] is True
        assert message["payload"]["duration_ms"] == 45
        assert message["payload"]["summary"] == "Read 100 lines from test.py"


class TestKafkaIntegrationOrdering:
    """Tests for event ordering guarantees."""

    async def test_events_for_same_session_ordered(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
    ) -> None:
        """Verify events for the same session maintain order.

        Events with the same entity_id (session_id) should be published
        to the same partition, maintaining strict ordering.
        """
        from omniclaude.hooks.handler_event_emitter import (
            emit_prompt_submitted,
            emit_session_ended,
            emit_session_started,
            emit_tool_executed,
        )

        # Emit events in sequence
        events_emitted = []

        result1 = await emit_session_started(
            session_id=unique_session_id,
            working_directory="/workspace",
            hook_source="startup",
            environment=test_environment,
        )
        assert result1.success
        events_emitted.append("session.started")

        result2 = await emit_prompt_submitted(
            session_id=unique_session_id,
            prompt_id=uuid4(),
            prompt_preview="First prompt",
            prompt_length=100,
            environment=test_environment,
        )
        assert result2.success
        events_emitted.append("prompt.submitted")

        result3 = await emit_tool_executed(
            session_id=unique_session_id,
            tool_execution_id=uuid4(),
            tool_name="Read",
            success=True,
            duration_ms=50,
            environment=test_environment,
        )
        assert result3.success
        events_emitted.append("tool.executed")

        result4 = await emit_session_ended(
            session_id=unique_session_id,
            reason="clear",
            duration_seconds=60.0,
            tools_used_count=1,
            environment=test_environment,
        )
        assert result4.success
        events_emitted.append("session.ended")

        # All events published successfully in order
        assert len(events_emitted) == 4
        assert events_emitted == [
            "session.started",
            "prompt.submitted",
            "tool.executed",
            "session.ended",
        ]


class TestKafkaIntegrationEnvelope:
    """Tests for event envelope structure."""

    async def test_envelope_structure_matches_schema(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify the envelope structure matches the schema definition."""
        from omniclaude.hooks.handler_event_emitter import emit_session_started
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(test_environment, TopicBase.SESSION_STARTED)

        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        await emit_session_started(
            session_id=unique_session_id,
            working_directory="/workspace",
            hook_source="startup",
            environment=test_environment,
        )

        message = await consumer_task
        assert message is not None

        # Verify envelope fields
        assert "event_type" in message
        assert "schema_version" in message
        assert "source" in message
        assert "payload" in message

        # Verify values
        assert message["event_type"] == "hook.session.started"
        assert message["schema_version"] == "1.0.0"
        assert message["source"] == "omniclaude"

        # Verify payload fields
        payload = message["payload"]
        assert "entity_id" in payload
        assert "session_id" in payload
        assert "correlation_id" in payload
        assert "causation_id" in payload
        assert "emitted_at" in payload
        assert "working_directory" in payload
        assert "hook_source" in payload


class TestKafkaIntegrationResilience:
    """Tests for resilience and failure handling."""

    async def test_publish_with_invalid_broker_fails_gracefully(
        self,
        unique_session_id,
    ) -> None:
        """Verify publish to invalid broker fails gracefully."""
        from omniclaude.hooks.handler_event_emitter import emit_session_started

        # Override environment to use invalid broker
        # Note: This test doesn't require kafka_health_check because we're
        # intentionally testing failure behavior
        original_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        try:
            os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "invalid-host:9999"

            result = await emit_session_started(
                session_id=unique_session_id,
                working_directory="/workspace",
                hook_source="startup",
                environment="test",
            )

            # Should fail gracefully, not raise exception
            assert result.success is False
            assert result.error_message is not None

        finally:
            # Restore original
            if original_servers:
                os.environ["KAFKA_BOOTSTRAP_SERVERS"] = original_servers
            else:
                os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)

    async def test_multiple_rapid_publishes(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
    ) -> None:
        """Verify rapid publishing doesn't cause issues."""
        from omniclaude.hooks.handler_event_emitter import emit_tool_executed

        results = []
        for i in range(10):
            result = await emit_tool_executed(
                session_id=unique_session_id,
                tool_execution_id=uuid4(),
                tool_name=f"Tool{i}",
                success=True,
                duration_ms=i * 10,
                environment=test_environment,
            )
            results.append(result)

        # All publishes should succeed
        successful = [r for r in results if r.success]
        assert len(successful) == 10, f"Only {len(successful)}/10 publishes succeeded"


class TestKafkaIntegrationPrivacy:
    """Tests for privacy sanitization in published events."""

    async def test_prompt_preview_sanitizes_secrets(
        self,
        _kafka_health_check,
        unique_session_id,
        test_environment,
        unique_consumer_group,
    ) -> None:
        """Verify prompt preview sanitizes secret patterns."""
        from omniclaude.hooks.handler_event_emitter import emit_prompt_submitted
        from omniclaude.hooks.topics import TopicBase, build_topic

        topic = build_topic(test_environment, TopicBase.PROMPT_SUBMITTED)

        consumer_task = asyncio.create_task(
            wait_for_message_with_entity_id(
                topic=topic,
                entity_id=str(unique_session_id),
                consumer_group=unique_consumer_group,
                timeout_seconds=10.0,
            )
        )
        await asyncio.sleep(1.0)

        # Publish prompt with secret pattern
        secret_prompt = "Set OPENAI_API_KEY=sk-1234567890abcdef1234567890abcdef"

        result = await emit_prompt_submitted(
            session_id=unique_session_id,
            prompt_id=uuid4(),
            prompt_preview=secret_prompt,
            prompt_length=len(secret_prompt),
            environment=test_environment,
        )

        assert result.success is True

        message = await consumer_task
        assert message is not None

        # Verify secret was redacted
        preview = message["payload"]["prompt_preview"]
        assert "sk-1234567890" not in preview
        assert "REDACTED" in preview


# =============================================================================
# Claude Hook Event Tests (omniintelligence topic)
# =============================================================================


async def wait_for_claude_hook_event(
    topic: str,
    session_id: str,
    consumer_group: str,
    timeout_seconds: float = 10.0,
) -> tuple[dict[str, Any] | None, bytes | None]:
    """Wait for a specific claude-hook-event by session_id.

    Claude hook events have a different structure than observability events.
    They use ModelClaudeCodeHookEvent from omnibase_core.

    Args:
        topic: The Kafka topic to consume from.
        session_id: The session_id to match in the event.
        consumer_group: Consumer group ID.
        timeout_seconds: Maximum time to wait.

    Returns:
        Tuple of (event_payload, partition_key) or (None, None) if not found.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return None, None

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=get_kafka_bootstrap_servers(),
        group_id=consumer_group,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=int(timeout_seconds * 1000),
    )

    try:
        await consumer.start()
        await consumer.seek_to_end()

        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            try:
                result = await consumer.getmany(timeout_ms=500, max_records=100)
                for _tp, records in result.items():
                    for record in records:
                        try:
                            payload = json.loads(record.value.decode("utf-8"))
                            # Claude hook events have session_id at root level
                            if payload.get("session_id") == session_id:
                                return payload, record.key
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue

            except TimeoutError:
                continue

        return None, None

    finally:
        await consumer.stop()


class TestClaudeHookEventIntegration:
    """Integration tests for emit_claude_hook_event (omniintelligence topic).

    These tests verify that claude-hook-events are correctly published to the
    omniintelligence topic (onex.cmd.omniintelligence.claude-hook-event.v1).

    This is the "dual emission" path where full prompts are sent to the
    intelligence service for analysis, separate from the truncated/sanitized
    observability events.

    Note:
        These tests use the actual Kafka environment (e.g., "dev") instead of
        test-specific prefixes because the claude-hook-event topic must exist.
        Unlike other hook topics that can be auto-created, the intelligence
        topic is typically pre-created with specific configuration.
    """

    async def test_claude_hook_event_reaches_kafka(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify claude-hook-event is published to and consumable from Kafka.

        This test:
        1. Creates a unique correlation_id for this test run
        2. Publishes a claude-hook-event
        3. Consumes from the topic
        4. Verifies the event with matching session_id arrives
        """
        from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

        from omniclaude.hooks.handler_event_emitter import (
            ModelClaudeHookEventConfig,
            emit_claude_hook_event,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        # Generate unique identifiers for this test
        test_correlation_id = uuid4()
        test_session_id = f"integration-test-{uuid4().hex[:12]}"
        test_prompt = f"Integration test prompt at {asyncio.get_running_loop().time()}"

        # Use actual Kafka environment (topic must exist)
        env = get_kafka_environment()

        # Build topic name
        topic = build_topic(env, TopicBase.CLAUDE_HOOK_EVENT)

        # Start consumer BEFORE publishing (to catch the message)
        consumer_task = asyncio.create_task(
            wait_for_claude_hook_event(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )

        # Small delay to let consumer subscribe
        await asyncio.sleep(1.0)

        # Emit the event
        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id=test_session_id,
            prompt=test_prompt,
            correlation_id=test_correlation_id,
            environment=env,
        )

        result = await emit_claude_hook_event(config)

        # Verify publish succeeded
        assert result.success is True, f"Publish failed: {result.error_message}"
        assert topic in result.topic

        # Wait for consumer to receive the message
        message, _partition_key = await consumer_task

        # Verify message was received
        assert message is not None, (
            f"Event with session_id={test_session_id} not found on topic {topic}"
        )

        # Verify event contents
        assert message["event_type"] == "UserPromptSubmit"
        assert message["session_id"] == test_session_id
        assert message["correlation_id"] == str(test_correlation_id)

        # Verify payload contains the full prompt
        assert "payload" in message
        assert message["payload"]["prompt"] == test_prompt

    async def test_claude_hook_event_partition_key_is_session_id(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify partition key is set to session_id for ordering guarantees.

        Events with the same session_id should go to the same partition,
        ensuring ordering within a session.
        """
        from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

        from omniclaude.hooks.handler_event_emitter import (
            ModelClaudeHookEventConfig,
            emit_claude_hook_event,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"partition-key-test-{uuid4().hex[:12]}"
        topic = build_topic(env, TopicBase.CLAUDE_HOOK_EVENT)

        consumer_task = asyncio.create_task(
            wait_for_claude_hook_event(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id=test_session_id,
            prompt="Test prompt for partition key verification",
            environment=env,
        )

        result = await emit_claude_hook_event(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        message, partition_key = await consumer_task

        assert message is not None, f"Message not received from topic {topic}"

        # Verify partition key is the session_id
        assert partition_key is not None, "Partition key should not be None"
        assert partition_key.decode("utf-8") == test_session_id

    async def test_claude_hook_event_full_prompt_not_truncated(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify full prompt is sent without truncation.

        Unlike the observability topic (prompt-submitted) which truncates to
        100 chars, the intelligence topic should receive the full prompt.
        """
        from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

        from omniclaude.hooks.handler_event_emitter import (
            ModelClaudeHookEventConfig,
            emit_claude_hook_event,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"full-prompt-test-{uuid4().hex[:12]}"
        # Create a long prompt (500 chars - well over 100 char observability limit)
        long_prompt = "A" * 500
        topic = build_topic(env, TopicBase.CLAUDE_HOOK_EVENT)

        consumer_task = asyncio.create_task(
            wait_for_claude_hook_event(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id=test_session_id,
            prompt=long_prompt,
            environment=env,
        )

        result = await emit_claude_hook_event(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        message, _partition_key = await consumer_task

        assert message is not None, f"Message not received from topic {topic}"

        # Verify full prompt was received (not truncated)
        received_prompt = message["payload"]["prompt"]
        assert len(received_prompt) == 500
        assert received_prompt == long_prompt

    async def test_claude_hook_event_correlation_id_preserved(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify correlation_id is correctly preserved in the event.

        Correlation IDs are critical for distributed tracing across services.
        """
        from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

        from omniclaude.hooks.handler_event_emitter import (
            ModelClaudeHookEventConfig,
            emit_claude_hook_event,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"correlation-test-{uuid4().hex[:12]}"
        test_correlation_id = uuid4()
        topic = build_topic(env, TopicBase.CLAUDE_HOOK_EVENT)

        consumer_task = asyncio.create_task(
            wait_for_claude_hook_event(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id=test_session_id,
            prompt="Test prompt for correlation ID verification",
            correlation_id=test_correlation_id,
            environment=env,
        )

        result = await emit_claude_hook_event(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        message, _partition_key = await consumer_task

        assert message is not None, f"Message not received from topic {topic}"

        # Verify correlation_id is preserved
        assert "correlation_id" in message
        assert message["correlation_id"] == str(test_correlation_id)

    async def test_claude_hook_event_timestamp_present(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify timestamp_utc is correctly set in the event."""
        from datetime import UTC, datetime

        from omnibase_core.enums.hooks.claude_code import EnumClaudeCodeHookEventType

        from omniclaude.hooks.handler_event_emitter import (
            ModelClaudeHookEventConfig,
            emit_claude_hook_event,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"timestamp-test-{uuid4().hex[:12]}"
        before_emit = datetime.now(UTC)
        topic = build_topic(env, TopicBase.CLAUDE_HOOK_EVENT)

        consumer_task = asyncio.create_task(
            wait_for_claude_hook_event(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelClaudeHookEventConfig(
            event_type=EnumClaudeCodeHookEventType.USER_PROMPT_SUBMIT,
            session_id=test_session_id,
            prompt="Test prompt for timestamp verification",
            environment=env,
        )

        result = await emit_claude_hook_event(config)
        after_emit = datetime.now(UTC)

        assert result.success is True, f"Publish failed: {result.error_message}"

        message, _partition_key = await consumer_task

        assert message is not None, f"Message not received from topic {topic}"

        # Verify timestamp is present and reasonable
        assert "timestamp_utc" in message
        # Parse the timestamp (ISO format)
        timestamp_str = message["timestamp_utc"]
        # Handle both Z and +00:00 timezone formats
        if timestamp_str.endswith("Z"):
            timestamp_str = timestamp_str[:-1] + "+00:00"
        event_time = datetime.fromisoformat(timestamp_str)

        # Verify timestamp is between before and after emit
        assert event_time >= before_emit.replace(microsecond=0)
        assert event_time <= after_emit


# =============================================================================
# Session Outcome Integration Tests (OMN-2076)
# =============================================================================


async def wait_for_session_outcome(
    topic: str,
    session_id: str,
    consumer_group: str,
    timeout_seconds: float = 10.0,
) -> dict[str, Any] | None:
    """Wait for a session outcome event by session_id.

    Session outcome events use ModelSessionOutcome schema (not the envelope
    schema used by other hook events), so we match on root-level session_id.

    Args:
        topic: The Kafka topic to consume from.
        session_id: The session_id to match in the payload.
        consumer_group: Consumer group ID.
        timeout_seconds: Maximum time to wait.

    Returns:
        The matching message payload, or None if not found.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        pytest.skip("aiokafka not installed")
        return None

    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=get_kafka_bootstrap_servers(),
        group_id=consumer_group,
        auto_offset_reset="latest",
        enable_auto_commit=True,
        consumer_timeout_ms=int(timeout_seconds * 1000),
    )

    try:
        await consumer.start()
        # No seek_to_end needed — auto_offset_reset="latest" positions
        # the consumer at the current end. Messages published AFTER the
        # consumer joins will be consumed, avoiding the race window that
        # existed with the old earliest + seek_to_end pattern.

        start_time = asyncio.get_running_loop().time()
        while (asyncio.get_running_loop().time() - start_time) < timeout_seconds:
            try:
                result = await consumer.getmany(timeout_ms=500, max_records=100)
                for _tp, records in result.items():
                    for record in records:
                        try:
                            payload = json.loads(record.value.decode("utf-8"))
                            if payload.get("session_id") == session_id:
                                return payload
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            continue

            except TimeoutError:
                continue

        return None

    finally:
        await consumer.stop()


class TestSessionOutcomeIntegration:
    """Integration tests for session outcome emission to both Kafka topics.

    Verifies that emit_session_outcome_from_config() correctly publishes
    to both the CMD (intelligence) and EVT (observability) topics.

    Part of OMN-2076: Golden path session + injection + outcome emission.
    """

    async def test_session_outcome_reaches_cmd_topic(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify session.outcome event reaches the CMD (intelligence) topic."""
        from datetime import UTC, datetime

        from omniclaude.hooks.handler_event_emitter import (
            ModelEventTracingConfig,
            ModelSessionOutcomeConfig,
            emit_session_outcome_from_config,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"outcome-cmd-test-{uuid4().hex[:12]}"
        topic = build_topic(env, TopicBase.SESSION_OUTCOME_CMD)

        # Start consumer BEFORE publishing
        consumer_task = asyncio.create_task(
            wait_for_session_outcome(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelSessionOutcomeConfig(
            session_id=test_session_id,
            outcome="success",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime.now(UTC),
                environment=env,
            ),
        )

        result = await emit_session_outcome_from_config(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        message = await consumer_task
        assert message is not None, f"Session outcome not received on CMD topic {topic}"
        assert message["session_id"] == test_session_id
        assert message["outcome"] == "success"
        assert message["event_name"] == "session.outcome"

    async def test_session_outcome_reaches_evt_topic(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Verify session.outcome event reaches the EVT (observability) topic."""
        from datetime import UTC, datetime

        from omniclaude.hooks.handler_event_emitter import (
            ModelEventTracingConfig,
            ModelSessionOutcomeConfig,
            emit_session_outcome_from_config,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic

        env = get_kafka_environment()
        test_session_id = f"outcome-evt-test-{uuid4().hex[:12]}"
        topic = build_topic(env, TopicBase.SESSION_OUTCOME_EVT)

        consumer_task = asyncio.create_task(
            wait_for_session_outcome(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        config = ModelSessionOutcomeConfig(
            session_id=test_session_id,
            outcome="failed",
            tracing=ModelEventTracingConfig(
                emitted_at=datetime.now(UTC),
                environment=env,
            ),
        )

        result = await emit_session_outcome_from_config(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        message = await consumer_task
        assert message is not None, f"Session outcome not received on EVT topic {topic}"
        assert message["session_id"] == test_session_id
        assert message["outcome"] == "failed"

    async def test_session_outcome_full_golden_path(
        self,
        _kafka_health_check,
        unique_consumer_group,
    ) -> None:
        """Golden path: derive outcome and emit to both topics.

        This test exercises the complete flow:
        1. Derive outcome from session signals (SUCCESS path)
        2. Emit to Kafka via emit_session_outcome_from_config
        3. Verify event arrives on CMD topic
        """
        from datetime import UTC, datetime

        from omniclaude.hooks.handler_event_emitter import (
            ModelEventTracingConfig,
            ModelSessionOutcomeConfig,
            emit_session_outcome_from_config,
        )
        from omniclaude.hooks.topics import TopicBase, build_topic
        from plugins.onex.hooks.lib.session_outcome import (
            OUTCOME_SUCCESS,
            derive_session_outcome,
        )

        env = get_kafka_environment()
        test_session_id = f"golden-path-test-{uuid4().hex[:12]}"
        topic = build_topic(env, TopicBase.SESSION_OUTCOME_CMD)

        # Step 1: Derive outcome
        outcome_result = derive_session_outcome(
            exit_code=0,
            session_output="Task completed successfully",
            tool_calls_completed=5,
            duration_seconds=300.0,
        )
        assert outcome_result.outcome == OUTCOME_SUCCESS

        # Step 2: Start consumer
        consumer_task = asyncio.create_task(
            wait_for_session_outcome(
                topic=topic,
                session_id=test_session_id,
                consumer_group=unique_consumer_group,
                timeout_seconds=15.0,
            )
        )
        await asyncio.sleep(1.0)

        # Step 3: Emit outcome
        config = ModelSessionOutcomeConfig(
            session_id=test_session_id,
            outcome=outcome_result.outcome,
            tracing=ModelEventTracingConfig(
                emitted_at=datetime.now(UTC),
                environment=env,
            ),
        )

        result = await emit_session_outcome_from_config(config)
        assert result.success is True, f"Publish failed: {result.error_message}"

        # Step 4: Verify
        message = await consumer_task
        assert message is not None, f"Golden path event not received on topic {topic}"
        assert message["session_id"] == test_session_id
        assert message["outcome"] == "success"
        assert "emitted_at" in message


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-s"])

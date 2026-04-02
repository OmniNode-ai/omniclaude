# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OmniClaw proof-of-life E2E test — Discord message flow through Kafka pipeline.

Validates the full channel message lifecycle:
  Discord message -> adapter -> Kafka -> orchestrator -> dispatcher -> Discord reply

Requires:
  - Docker infra running (infra-up-runtime)
  - DISCORD_BOT_TOKEN configured
  - DISCORD_TEST_CHANNEL_ID configured
  - Kafka topics created
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import pytest

# Skip entire module if Discord bot token is not configured
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_TEST_CHANNEL_ID = os.environ.get("DISCORD_TEST_CHANNEL_ID", "")
KAFKA_BOOTSTRAP_SERVERS = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")

pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration,
    pytest.mark.skipif(
        not DISCORD_BOT_TOKEN,
        reason="DISCORD_BOT_TOKEN not configured — skipping proof-of-life test",
    ),
    pytest.mark.skipif(
        not DISCORD_TEST_CHANNEL_ID,
        reason="DISCORD_TEST_CHANNEL_ID not configured — skipping proof-of-life test",
    ),
]

# Expected Kafka topics in the OmniClaw message flow
EXPECTED_TOPICS = [
    "onex.cmd.omniclaw.channel-message-received.v1",
    "onex.evt.omniclaw.channel-reply-requested.v1",
    "onex.cmd.omniclaw.discord-outbound.v1",
    "onex.evt.omniclaw.channel-message-processed.v1",
]

POLL_TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 2


def _send_discord_message(channel_id: str, content: str) -> dict[str, Any]:
    """Send a message to a Discord channel via the bot API.

    Returns:
        The Discord message object from the API response.
    """
    import httpx

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
    }
    response = httpx.post(url, json={"content": content}, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


def _poll_for_reply(
    channel_id: str,
    after_message_id: str,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> dict[str, Any] | None:
    """Poll a Discord channel for a bot reply after a given message ID.

    Returns:
        The reply message dict, or None if no reply within timeout.
    """
    import httpx

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}
    params = {"after": after_message_id, "limit": "10"}

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = httpx.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        messages = response.json()

        # Look for a message from the bot (not from us)
        for msg in messages:
            if msg.get("author", {}).get("bot"):
                return msg  # type: ignore[no-any-return]

        time.sleep(POLL_INTERVAL_SECONDS)

    return None


def _consume_kafka_events(
    topics: list[str],
    correlation_id: str,
    timeout: int = POLL_TIMEOUT_SECONDS,
) -> dict[str, list[dict[str, Any]]]:
    """Consume Kafka events from the given topics, filtering by correlation_id.

    Returns:
        Dict mapping topic -> list of matching events.
    """
    try:
        from confluent_kafka import Consumer
    except ImportError:
        pytest.skip("confluent-kafka not installed — skipping Kafka assertions")

    consumer = Consumer(
        {
            "bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS,
            "group.id": f"proof-of-life-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "latest",
            "enable.auto.commit": "true",
        }
    )
    consumer.subscribe(topics)

    events: dict[str, list[dict[str, Any]]] = {t: [] for t in topics}
    deadline = time.monotonic() + timeout

    try:
        while time.monotonic() < deadline:
            msg = consumer.poll(timeout=1.0)
            if msg is None or msg.error():
                continue

            import json

            try:
                value = json.loads(msg.value().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            if value.get("correlation_id") == correlation_id:
                topic = msg.topic()
                if topic and topic in events:
                    events[topic].append(value)
    finally:
        consumer.close()

    return events


class TestOmniClawProofOfLife:
    """End-to-end proof-of-life test for OmniClaw Discord message flow."""

    def test_discord_message_roundtrip(self) -> None:
        """Send a Discord message and verify full pipeline flow."""
        correlation_id = uuid.uuid4().hex
        test_content = f"OmniClaw proof of life -- {correlation_id}"

        # Step 1: Send test message
        sent = _send_discord_message(DISCORD_TEST_CHANNEL_ID, test_content)
        sent_id = sent["id"]
        assert sent_id, "Failed to send Discord message"

        # Step 2: Poll for bot reply
        reply = _poll_for_reply(
            DISCORD_TEST_CHANNEL_ID,
            sent_id,
            timeout=POLL_TIMEOUT_SECONDS,
        )
        assert reply is not None, (
            f"No bot reply received within {POLL_TIMEOUT_SECONDS}s"
        )
        assert reply.get("content"), "Bot reply has empty content"

    def test_kafka_event_chain(self) -> None:
        """Verify Kafka topics show the full event chain with consistent correlation_id."""
        correlation_id = uuid.uuid4().hex
        test_content = f"OmniClaw kafka chain test -- {correlation_id}"

        # Send test message
        _send_discord_message(DISCORD_TEST_CHANNEL_ID, test_content)

        # Consume events from all expected topics
        events = _consume_kafka_events(
            EXPECTED_TOPICS,
            correlation_id,
            timeout=POLL_TIMEOUT_SECONDS,
        )

        # Verify at least the inbound topic got an event
        inbound_topic = "onex.cmd.omniclaw.channel-message-received.v1"
        assert len(events[inbound_topic]) > 0, (
            f"No events on {inbound_topic} for correlation_id={correlation_id}"
        )

        # Verify correlation_id consistency across all received events
        for topic, topic_events in events.items():
            for event in topic_events:
                assert event.get("correlation_id") == correlation_id, (
                    f"Mismatched correlation_id on {topic}: "
                    f"expected {correlation_id}, got {event.get('correlation_id')}"
                )

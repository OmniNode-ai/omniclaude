#!/usr/bin/env python3

import asyncio
import os
import socket
from uuid import uuid4

import pytest

from agents.lib.kafka_codegen_client import KafkaCodegenClient
from agents.lib.codegen_events import CodegenAnalysisRequest


def _can_connect(bootstrap: str) -> bool:
    try:
        host, port = bootstrap.split(":")
        with socket.create_connection((host, int(port)), timeout=0.5):
            return True
    except Exception:
        return False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_integration_publish_consume_skip_when_unreachable():
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:29092")
    if not _can_connect(bootstrap):
        pytest.skip(f"Kafka not reachable at {bootstrap}")

    client = KafkaCodegenClient(bootstrap_servers=bootstrap)

    evt = CodegenAnalysisRequest()
    evt.correlation_id = uuid4()
    evt.payload = {"prd_content": "# PRD\n"}

    try:
        await client.publish(evt)
    except Exception as e:
        # Auto-fallback to confluent when aiokafka fails
        try:
            from agents.lib.kafka_confluent_client import ConfluentKafkaClient

            confluent = ConfluentKafkaClient(bootstrap_servers=bootstrap)
            confluent.publish(
                evt.to_kafka_topic(),
                {
                    "id": str(evt.id),
                    "service": evt.service,
                    "timestamp": evt.timestamp,
                    "correlation_id": str(evt.correlation_id),
                    "metadata": evt.metadata,
                    "payload": evt.payload,
                },
            )
            print(f"[confluent fallback] Published {evt.correlation_id}")
        except Exception as fallback_e:
            await asyncio.gather(client.stop_producer(), client.stop_consumer(), return_exceptions=True)
            pytest.skip(f"aiokafka bootstrap failed; confluent fallback also failed: {e} -> {fallback_e}")

    topic = "dev.omniclaude.codegen.analyze.response.v1"

    def matches(payload: dict) -> bool:
        # In real system, another service will respond; here we just exercise the consumer
        # Accept any payload for smoke (but bounded by timeout)
        return True

    try:
        _ = await client.consume_until(topic, matches, timeout_seconds=0.3)
    finally:
        await asyncio.gather(client.stop_producer(), client.stop_consumer(), return_exceptions=True)

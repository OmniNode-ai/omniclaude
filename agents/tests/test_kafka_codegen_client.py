#!/usr/bin/env python3

import asyncio
import json
import types
from uuid import uuid4

import pytest

from agents.lib.kafka_codegen_client import KafkaCodegenClient
from agents.lib.codegen_events import CodegenAnalysisRequest


class DummyProducer:
    def __init__(self):
        self.sent = []

    async def start(self):
        return None

    async def stop(self):
        return None

    async def send_and_wait(self, topic, payload):
        self.sent.append((topic, payload))


def test_rewrite_bootstrap_mapping():
    client = KafkaCodegenClient(bootstrap_servers="omninode-bridge-redpanda:9092")
    # Private helper validation
    rewritten = client._rewrite_bootstrap(client.bootstrap_servers)
    assert "localhost:" in rewritten


@pytest.mark.asyncio
async def test_publish_message_shape_and_topic(monkeypatch):
    client = KafkaCodegenClient(bootstrap_servers="localhost:29092")
    dummy = DummyProducer()

    async def fake_start_producer():
        client._producer = dummy

    monkeypatch.setattr(client, "start_producer", fake_start_producer)

    evt = CodegenAnalysisRequest()
    evt.correlation_id = uuid4()
    evt.payload = {"prd_content": "# PRD\n"}

    await client.publish(evt)

    assert len(dummy.sent) == 1
    topic, payload = dummy.sent[0]
    assert topic == evt.to_kafka_topic()
    data = json.loads(payload.decode("utf-8"))
    # required fields present
    assert data["id"]
    assert data["service"] == "omniclaude"
    assert data["correlation_id"] == str(evt.correlation_id)
    assert "payload" in data and "prd_content" in data["payload"]


@pytest.mark.asyncio
async def test_publish_confluent_fallback(monkeypatch):
    # Force start_producer to raise to trigger fallback
    client = KafkaCodegenClient(bootstrap_servers="localhost:29092")

    async def boom():
        raise RuntimeError("fail aiokafka")

    monkeypatch.setattr(client, "start_producer", boom)

    published = {}

    class DummyConfluent:
        def __init__(self, *_args, **_kwargs):
            pass

        def publish(self, topic, payload):
            published["topic"] = topic
            published["payload"] = payload

    import agents.lib.kafka_codegen_client as mod
    monkeypatch.setattr(mod, "ConfluentKafkaClient", DummyConfluent)

    evt = CodegenAnalysisRequest()
    evt.correlation_id = uuid4()
    evt.payload = {"prd_content": "x"}

    await client.publish(evt)

    assert published["topic"] == evt.to_kafka_topic()
    assert published["payload"]["correlation_id"] == str(evt.correlation_id)



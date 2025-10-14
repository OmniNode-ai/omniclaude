#!/usr/bin/env python3

import asyncio
from uuid import uuid4

import pytest

from agents.lib.prd_intelligence_client import PRDIntelligenceClient


class DummyKafka:
    def __init__(self):
        self.published = []
        self.response = None

    async def publish(self, evt):
        self.published.append(evt)

    async def consume_until(self, topic, predicate, timeout_seconds=0.1):
        # Immediately return response if predicate matches
        if self.response and predicate(self.response):
            return self.response
        return None

    async def stop_consumer(self):
        return None

    async def stop_producer(self):
        return None


@pytest.mark.asyncio
async def test_analyze_roundtrip_success(monkeypatch):
    client = PRDIntelligenceClient(bootstrap_servers="localhost:29092")

    dummy = DummyKafka()
    # Patch internal kafka client instance
    monkeypatch.setattr(client, "_kafka", dummy)

    # Prepare a matching response
    # We don't know the correlation id until after publish, so capture it
    captured = {}

    async def capture_publish(evt):
        captured["correlation_id"] = str(evt.correlation_id)
        await DummyKafka.publish(dummy, evt)

    monkeypatch.setattr(dummy, "publish", capture_publish)

    # After publish, provide a response that matches the correlation id
    async def fake_consume_until(topic, predicate, timeout_seconds=0.1):
        payload = {"correlation_id": captured.get("correlation_id"), "analysis": {"node_type_hints": {"EFFECT": 0.9}}}
        if predicate(payload):
            return payload
        return None

    monkeypatch.setattr(dummy, "consume_until", fake_consume_until)

    resp = await client.analyze("# PRD", workspace_context={"k": "v"}, timeout_seconds=0.1)
    assert resp is not None
    assert resp.get("analysis") is not None



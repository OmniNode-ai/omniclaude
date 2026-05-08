# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for the delegation event emitter (OMN-10656)."""

from __future__ import annotations

import asyncio
import json

import pytest
from omnibase_infra.event_bus.event_bus_inmemory import EventBusInmemory

from omniclaude.delegation.emitter import emit_task_delegated
from omniclaude.hooks.topics import TopicBase


def _start_bus() -> EventBusInmemory:
    bus = EventBusInmemory(environment="test", group="emitter-test")
    asyncio.run(bus.start())
    return bus


@pytest.mark.unit
class TestEmitTaskDelegated:
    """emit_task_delegated publishes the canonical task-delegated event."""

    def test_publishes_to_task_delegated_topic(self) -> None:
        bus = _start_bus()
        try:
            asyncio.run(
                emit_task_delegated(
                    bus=bus,
                    correlation_id="corr-001",
                    session_id="sess-A",
                    task_type="document",
                    delegated_to="Qwen3-Coder-30B",
                    delegated_by="onex.delegate-skill.test",
                    quality_gate_passed=True,
                    delegation_latency_ms=250,
                    cost_savings_usd=0.01,
                )
            )
            history = asyncio.run(
                bus.get_event_history(topic=str(TopicBase.TASK_DELEGATED))
            )
            assert len(history) == 1
            payload = json.loads(history[0].value)
            assert payload["correlation_id"] == "corr-001"
            assert payload["task_type"] == "document"
            assert payload["delegated_to"] == "Qwen3-Coder-30B"
            assert payload["quality_gate_passed"] is True
            assert payload["delegation_latency_ms"] == 250
            assert payload["cost_savings_usd"] == pytest.approx(0.01)
        finally:
            asyncio.run(bus.close())

    def test_token_counts_propagate(self) -> None:
        bus = _start_bus()
        try:
            asyncio.run(
                emit_task_delegated(
                    bus=bus,
                    correlation_id="corr-tokens",
                    session_id="sess-tokens",
                    task_type="test",
                    delegated_to="Qwen3-Coder-30B",
                    delegated_by="onex.delegate-skill.test",
                    quality_gate_passed=True,
                    delegation_latency_ms=300,
                    cost_savings_usd=0.02,
                    tokens_input=312,
                    tokens_output=87,
                )
            )
            history = asyncio.run(
                bus.get_event_history(topic=str(TopicBase.TASK_DELEGATED))
            )
            payload = json.loads(history[0].value)
            assert payload["tokens_input"] == 312
            assert payload["tokens_output"] == 87
        finally:
            asyncio.run(bus.close())

    def test_default_model_name_falls_back_to_delegated_to(self) -> None:
        bus = _start_bus()
        try:
            asyncio.run(
                emit_task_delegated(
                    bus=bus,
                    correlation_id="corr-model",
                    session_id="sess-model",
                    task_type="research",
                    delegated_to="DeepSeek-R1-32B",
                    delegated_by="onex.delegate-skill.test",
                    quality_gate_passed=False,
                    delegation_latency_ms=1500,
                    cost_savings_usd=0.0,
                    quality_gate_reason="response too short",
                    delegation_success=False,
                )
            )
            history = asyncio.run(
                bus.get_event_history(topic=str(TopicBase.TASK_DELEGATED))
            )
            payload = json.loads(history[0].value)
            assert payload["model_name"] == "DeepSeek-R1-32B"
            assert payload["quality_gate_reason"] == "response too short"
            assert payload["delegation_success"] is False
        finally:
            asyncio.run(bus.close())

    def test_message_key_is_correlation_id(self) -> None:
        bus = _start_bus()
        try:
            asyncio.run(
                emit_task_delegated(
                    bus=bus,
                    correlation_id="corr-key",
                    session_id="sess-key",
                    task_type="document",
                    delegated_to="Qwen3-Coder-30B",
                    delegated_by="onex.delegate-skill.test",
                    quality_gate_passed=True,
                    delegation_latency_ms=100,
                    cost_savings_usd=0.001,
                )
            )
            history = asyncio.run(
                bus.get_event_history(topic=str(TopicBase.TASK_DELEGATED))
            )
            assert history[0].key == b"corr-key"
        finally:
            asyncio.run(bus.close())

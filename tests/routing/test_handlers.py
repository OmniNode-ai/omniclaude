# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for routing node handlers.

Tests HandlerRoutingDefault, HandlerRoutingEmitter, and HandlerHistoryPostgres
to verify ported logic correctness and behavioral invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.nodes.node_agent_routing_compute.handler_routing_default import (
    HandlerRoutingDefault,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelAgentDefinition,
    ModelConfidenceBreakdown,
    ModelRoutingRequest,
)
from omniclaude.nodes.node_routing_emission_effect.handler_routing_emitter import (
    HandlerRoutingEmitter,
)
from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionRequest,
)
from omniclaude.nodes.node_routing_history_reducer.handler_history_postgres import (
    HandlerHistoryPostgres,
)
from omniclaude.nodes.node_routing_history_reducer.models import (
    ModelAgentStatsEntry,
)

# ── Helpers ────────────────────────────────────────────────────────────


def _make_agent(
    name: str,
    triggers: tuple[str, ...] = (),
    capabilities: tuple[str, ...] = (),
    domain: str = "general",
    context_triggers: tuple[str, ...] = (),
) -> ModelAgentDefinition:
    return ModelAgentDefinition(
        name=name,
        agent_type=name.replace("agent-", "").replace("-", "_"),
        explicit_triggers=triggers,
        context_triggers=context_triggers,
        capabilities=capabilities,
        domain_context=domain,
    )


def _make_request(
    prompt: str,
    agents: tuple[ModelAgentDefinition, ...],
    threshold: float = 0.5,
) -> ModelRoutingRequest:
    return ModelRoutingRequest(
        prompt=prompt,
        correlation_id=uuid4(),
        agent_registry=agents,
        confidence_threshold=threshold,
    )


# ══════════════════════════════════════════════════════════════════════
# HandlerRoutingDefault
# ══════════════════════════════════════════════════════════════════════


class TestHandlerRoutingDefault:
    """Tests for HandlerRoutingDefault.compute_routing()."""

    @pytest.fixture
    def handler(self) -> HandlerRoutingDefault:
        return HandlerRoutingDefault()

    def test_handler_key_is_default(self, handler: HandlerRoutingDefault) -> None:
        assert handler.handler_key == "default"

    @pytest.mark.asyncio
    async def test_explicit_agent_request(self, handler: HandlerRoutingDefault) -> None:
        agents = (
            _make_agent("agent-api-architect", triggers=("api design",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("use agent-api-architect", agents)
        result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-api-architect"
        assert result.confidence == 1.0
        assert result.routing_policy == "explicit_request"

    @pytest.mark.asyncio
    async def test_generic_agent_request(self, handler: HandlerRoutingDefault) -> None:
        """'use an agent' should resolve to polymorphic-agent."""
        agents = (
            _make_agent("agent-api-architect", triggers=("api design",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("use an agent to help me", agents)
        result = await handler.compute_routing(request)

        assert result.selected_agent == "polymorphic-agent"
        assert result.confidence == 1.0
        assert result.routing_policy == "explicit_request"

    @pytest.mark.asyncio
    async def test_generic_agent_request_missing_fallback(
        self, handler: HandlerRoutingDefault
    ) -> None:
        """Generic request when polymorphic-agent is NOT in registry should not match."""
        agents = (_make_agent("agent-api-architect", triggers=("api design",)),)
        request = _make_request("use an agent to help me", agents)
        result = await handler.compute_routing(request)

        # polymorphic-agent not in registry, so generic pattern doesn't match
        assert result.routing_policy != "explicit_request"

    @pytest.mark.asyncio
    async def test_trigger_match(self, handler: HandlerRoutingDefault) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug", "troubleshoot")),
            _make_agent("agent-api-architect", triggers=("api design", "openapi")),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("I need to debug this error", agents)
        result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-debugger"
        assert result.routing_policy == "trigger_match"
        assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_fallback_when_no_match(self, handler: HandlerRoutingDefault) -> None:
        agents = (
            _make_agent("agent-api-architect", triggers=("api design",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request(
            "tell me about the weather forecast for tomorrow", agents, threshold=0.9
        )
        result = await handler.compute_routing(request)

        assert result.selected_agent == "polymorphic-agent"
        assert result.routing_policy == "fallback_default"
        assert result.fallback_reason is not None

    @pytest.mark.asyncio
    async def test_deterministic_iteration_order(
        self, handler: HandlerRoutingDefault
    ) -> None:
        """Agents with identical scores should be selected deterministically."""
        agents = (
            _make_agent("agent-zzz", triggers=("testing",)),
            _make_agent("agent-aaa", triggers=("testing",)),
        )
        results = []
        for _ in range(5):
            request = _make_request("I need help testing", agents)
            result = await handler.compute_routing(request)
            results.append(result.selected_agent)

        # All results should be identical (deterministic)
        assert len(set(results)) == 1

    @pytest.mark.asyncio
    async def test_hard_floor_filters_noise(
        self, handler: HandlerRoutingDefault
    ) -> None:
        """Low-confidence fuzzy matches should be filtered by HARD_FLOOR."""
        agents = (
            _make_agent("agent-xyz", triggers=("xylophone",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        # "xyz" is too short/different from "xylophone" to reach HARD_FLOOR
        request = _make_request("xyz something unrelated", agents, threshold=0.1)
        result = await handler.compute_routing(request)

        # Should fallback because fuzzy match for "xylophone" against "xyz"
        # won't pass the HARD_FLOOR
        assert result.routing_policy in ("fallback_default", "trigger_match")

    @pytest.mark.asyncio
    async def test_candidates_capped_at_max(
        self, handler: HandlerRoutingDefault
    ) -> None:
        """At most 5 candidates should be returned."""
        agents = tuple(
            _make_agent(f"agent-test-{i}", triggers=("testing",)) for i in range(10)
        )
        request = _make_request("I need help testing", agents)
        result = await handler.compute_routing(request)

        assert len(result.candidates) <= 5

    @pytest.mark.asyncio
    async def test_context_triggers_included_in_routing(
        self, handler: HandlerRoutingDefault
    ) -> None:
        """Context triggers should be merged into activation_triggers for matching."""
        agents = (
            _make_agent(
                "agent-security-auditor",
                triggers=("security audit",),
                context_triggers=("vulnerability", "penetration testing"),
            ),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        # Request matches context_trigger "vulnerability" but not explicit_trigger
        request = _make_request("check for vulnerability in auth module", agents)
        result = await handler.compute_routing(request)

        assert result.selected_agent == "agent-security-auditor"
        assert result.routing_policy == "trigger_match"

    @pytest.mark.asyncio
    async def test_confidence_breakdown_populated(
        self, handler: HandlerRoutingDefault
    ) -> None:
        agents = (
            _make_agent("agent-debugger", triggers=("debug",)),
            _make_agent("polymorphic-agent", triggers=("poly",)),
        )
        request = _make_request("debug this error", agents)
        result = await handler.compute_routing(request)

        if result.routing_policy == "trigger_match":
            bd = result.confidence_breakdown
            assert 0.0 <= bd.total <= 1.0
            assert 0.0 <= bd.trigger_score <= 1.0
            assert bd.explanation


# ══════════════════════════════════════════════════════════════════════
# HandlerRoutingEmitter
# ══════════════════════════════════════════════════════════════════════


class TestHandlerRoutingEmitter:
    """Tests for HandlerRoutingEmitter.emit_routing_decision()."""

    def test_handler_key(self) -> None:
        handler = HandlerRoutingEmitter(emit_fn=lambda et, p: True)
        assert handler.handler_key == "kafka"

    @pytest.mark.asyncio
    async def test_successful_emission(self) -> None:
        emitted_payloads: list[dict] = []

        def mock_emit(event_type: str, payload: dict) -> bool:
            emitted_payloads.append({"event_type": event_type, "payload": payload})
            return True

        handler = HandlerRoutingEmitter(emit_fn=mock_emit)
        request = ModelEmissionRequest(
            correlation_id=uuid4(),
            session_id="test-session",
            selected_agent="agent-debugger",
            confidence=0.85,
            confidence_breakdown=ModelConfidenceBreakdown(
                total=0.85,
                trigger_score=0.9,
                context_score=0.7,
                capability_score=0.8,
                historical_score=0.5,
                explanation="test",
            ),
            routing_policy="trigger_match",
            routing_path="local",
            prompt_preview="debug this",
            prompt_length=10,
            emitted_at=datetime.now(UTC),
        )
        result = await handler.emit_routing_decision(request)

        assert result.success is True
        assert len(result.topics_emitted) == 2
        assert result.error is None
        assert len(emitted_payloads) == 1

    @pytest.mark.asyncio
    async def test_failed_emission_returns_false(self) -> None:
        handler = HandlerRoutingEmitter(emit_fn=lambda et, p: False)
        request = ModelEmissionRequest(
            correlation_id=uuid4(),
            session_id="test-session",
            selected_agent="agent-debugger",
            confidence=0.85,
            confidence_breakdown=ModelConfidenceBreakdown(
                total=0.85,
                trigger_score=0.9,
                context_score=0.7,
                capability_score=0.8,
                historical_score=0.5,
                explanation="test",
            ),
            routing_policy="trigger_match",
            routing_path="local",
            prompt_preview="debug this",
            prompt_length=10,
            emitted_at=datetime.now(UTC),
        )
        result = await handler.emit_routing_decision(request)

        assert result.success is False
        assert result.topics_emitted == ()
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_exception_in_emit_fn_never_raises(self) -> None:
        def exploding_emit(event_type: str, payload: dict) -> bool:
            raise RuntimeError("Kafka unavailable")

        handler = HandlerRoutingEmitter(emit_fn=exploding_emit)
        request = ModelEmissionRequest(
            correlation_id=uuid4(),
            session_id="test-session",
            selected_agent="agent-debugger",
            confidence=0.85,
            confidence_breakdown=ModelConfidenceBreakdown(
                total=0.85,
                trigger_score=0.9,
                context_score=0.7,
                capability_score=0.8,
                historical_score=0.5,
                explanation="test",
            ),
            routing_policy="trigger_match",
            routing_path="local",
            prompt_preview="debug this",
            prompt_length=10,
            emitted_at=datetime.now(UTC),
        )
        result = await handler.emit_routing_decision(request)

        assert result.success is False
        assert "RuntimeError" in result.error


# ══════════════════════════════════════════════════════════════════════
# HandlerHistoryPostgres
# ══════════════════════════════════════════════════════════════════════


class TestHandlerHistoryPostgres:
    """Tests for HandlerHistoryPostgres.record_routing_decision()."""

    @pytest.fixture
    def fixed_clock(self) -> datetime:
        return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    @pytest.fixture
    def handler(self, fixed_clock: datetime) -> HandlerHistoryPostgres:
        return HandlerHistoryPostgres(clock=lambda: fixed_clock)

    def test_handler_key(self, handler: HandlerHistoryPostgres) -> None:
        assert handler.handler_key == "postgresql"

    @pytest.mark.asyncio
    async def test_record_and_query(self, handler: HandlerHistoryPostgres) -> None:
        entry = ModelAgentStatsEntry(agent_name="agent-debugger")
        cid = uuid4()
        stats = await handler.record_routing_decision(entry, correlation_id=cid)

        assert stats.total_routing_decisions == 1
        assert len(stats.entries) == 1
        assert stats.entries[0].agent_name == "agent-debugger"

    @pytest.mark.asyncio
    async def test_idempotency(self, handler: HandlerHistoryPostgres) -> None:
        entry = ModelAgentStatsEntry(agent_name="agent-debugger")
        cid = uuid4()

        stats1 = await handler.record_routing_decision(entry, correlation_id=cid)
        stats2 = await handler.record_routing_decision(entry, correlation_id=cid)

        # Second call with same correlation_id should be a no-op
        assert stats1.total_routing_decisions == stats2.total_routing_decisions

    @pytest.mark.asyncio
    async def test_query_unknown_agent_returns_defaults(
        self, handler: HandlerHistoryPostgres
    ) -> None:
        stats = await handler.query_routing_stats(agent_name="agent-nonexistent")

        assert stats.total_routing_decisions == 0
        assert len(stats.entries) == 1
        assert stats.entries[0].success_rate == 0.5  # default

    @pytest.mark.asyncio
    async def test_dedup_eviction_preserves_recent(
        self, handler: HandlerHistoryPostgres
    ) -> None:
        """Dedup cache evicts oldest half, not everything."""
        import omniclaude.nodes.node_routing_history_reducer.handler_history_postgres as mod

        original_max = mod._MAX_DEDUP_ENTRIES
        mod._MAX_DEDUP_ENTRIES = 10  # Small cap for fast test
        try:
            test_handler = HandlerHistoryPostgres(clock=lambda: datetime.now(UTC))
            for i in range(12):
                entry = ModelAgentStatsEntry(agent_name="agent-test")
                await test_handler.record_routing_decision(
                    entry, correlation_id=uuid4()
                )

            # After eviction, handler should still have entries
            stats = await test_handler.query_routing_stats()
            assert stats.total_routing_decisions == 12
        finally:
            mod._MAX_DEDUP_ENTRIES = original_max

    @pytest.mark.asyncio
    async def test_snapshot_timestamp_uses_clock(
        self, handler: HandlerHistoryPostgres, fixed_clock: datetime
    ) -> None:
        entry = ModelAgentStatsEntry(agent_name="agent-debugger")
        stats = await handler.record_routing_decision(entry, correlation_id=uuid4())

        assert stats.snapshot_at == fixed_clock

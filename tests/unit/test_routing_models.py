# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for routing_models re-export package and underlying model validation.

Covers:
    - All re-exports from omniclaude.routing_models
    - ModelAgentDefinition construction and field constraints
    - ModelConfidenceBreakdown construction and validation
    - ModelRoutingRequest construction and validation
    - ModelRoutingResult and ModelRoutingCandidate construction
    - ModelEmissionRequest timezone-aware validator
    - ModelEmissionResult construction
    - ModelAgentRoutingStats and ModelAgentStatsEntry validators
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from omniclaude.routing_models import (
    ModelAgentDefinition,
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
    ModelConfidenceBreakdown,
    ModelEmissionRequest,
    ModelEmissionResult,
    ModelRoutingCandidate,
    ModelRoutingRequest,
    ModelRoutingResult,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_breakdown(**overrides: object) -> ModelConfidenceBreakdown:
    defaults = {
        "total": 0.8,
        "trigger_score": 0.9,
        "context_score": 0.7,
        "capability_score": 0.8,
        "historical_score": 0.6,
        "explanation": "High trigger match",
    }
    defaults.update(overrides)
    return ModelConfidenceBreakdown(**defaults)  # type: ignore[arg-type]


def _make_agent(**overrides: object) -> ModelAgentDefinition:
    defaults = {
        "name": "agent-test",
        "agent_type": "test_agent",
    }
    defaults.update(overrides)
    return ModelAgentDefinition(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ModelAgentDefinition
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAgentDefinition:
    def test_minimal_construction(self) -> None:
        agent = ModelAgentDefinition(name="agent-x", agent_type="x_type")
        assert agent.name == "agent-x"
        assert agent.agent_type == "x_type"
        assert agent.description == ""
        assert agent.domain_context == "general"
        assert agent.explicit_triggers == ()
        assert agent.capabilities == ()

    def test_full_construction(self) -> None:
        agent = ModelAgentDefinition(
            name="agent-api-architect",
            agent_type="api_architect",
            description="Designs APIs",
            domain_context="debugging",
            explicit_triggers=("design api", "create endpoint"),
            context_triggers=("rest", "graphql"),
            capabilities=("api_design", "schema_validation"),
            definition_path="/agents/api-architect.yaml",
        )
        assert len(agent.explicit_triggers) == 2
        assert agent.definition_path == "/agents/api-architect.yaml"

    def test_frozen(self) -> None:
        agent = _make_agent()
        with pytest.raises(Exception):
            agent.name = "changed"  # type: ignore[misc]

    def test_extra_forbidden(self) -> None:
        with pytest.raises(Exception):
            ModelAgentDefinition(name="x", agent_type="y", unknown_field="bad")

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(Exception):
            ModelAgentDefinition(name="", agent_type="x")


# ---------------------------------------------------------------------------
# ModelConfidenceBreakdown
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelConfidenceBreakdown:
    def test_construction(self) -> None:
        bd = _make_breakdown()
        assert bd.total == 0.8
        assert bd.trigger_score == 0.9

    def test_score_bounds(self) -> None:
        with pytest.raises(Exception):
            _make_breakdown(total=1.5)

    def test_negative_score_rejected(self) -> None:
        with pytest.raises(Exception):
            _make_breakdown(context_score=-0.1)


# ---------------------------------------------------------------------------
# ModelRoutingRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelRoutingRequest:
    def test_construction(self) -> None:
        agent = _make_agent()
        req = ModelRoutingRequest(
            prompt="Deploy the new API",
            correlation_id=uuid4(),
            agent_registry=(agent,),
        )
        assert req.confidence_threshold == 0.5
        assert req.historical_stats is None

    def test_empty_prompt_rejected(self) -> None:
        with pytest.raises(Exception):
            ModelRoutingRequest(
                prompt="",
                correlation_id=uuid4(),
                agent_registry=(_make_agent(),),
            )

    def test_confidence_threshold_bounds(self) -> None:
        with pytest.raises(Exception):
            ModelRoutingRequest(
                prompt="test",
                correlation_id=uuid4(),
                agent_registry=(_make_agent(),),
                confidence_threshold=1.5,
            )


# ---------------------------------------------------------------------------
# ModelRoutingResult / ModelRoutingCandidate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelRoutingResult:
    def test_construction(self) -> None:
        bd = _make_breakdown()
        result = ModelRoutingResult(
            selected_agent="agent-test",
            confidence=0.9,
            confidence_breakdown=bd,
            routing_policy="trigger_match",
            routing_path="local",
        )
        assert result.candidates == ()
        assert result.fallback_reason is None
        assert result.prompt_tokens == 0
        assert result.omninode_enabled is False

    def test_with_candidates(self) -> None:
        bd = _make_breakdown()
        candidate = ModelRoutingCandidate(
            agent_name="agent-test",
            confidence=0.9,
            confidence_breakdown=bd,
            match_reason="Trigger match on deploy",
        )
        result = ModelRoutingResult(
            selected_agent="agent-test",
            confidence=0.9,
            confidence_breakdown=bd,
            routing_policy="trigger_match",
            routing_path="event",
            candidates=(candidate,),
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].match_reason == "Trigger match on deploy"

    def test_invalid_routing_policy(self) -> None:
        with pytest.raises(Exception):
            ModelRoutingResult(
                selected_agent="agent-test",
                confidence=0.9,
                confidence_breakdown=_make_breakdown(),
                routing_policy="invalid",  # type: ignore[arg-type]
                routing_path="local",
            )


# ---------------------------------------------------------------------------
# ModelEmissionRequest
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelEmissionRequest:
    def test_construction(self) -> None:
        req = ModelEmissionRequest(
            correlation_id=uuid4(),
            session_id="sess-123",
            selected_agent="agent-test",
            confidence=0.85,
            confidence_breakdown=_make_breakdown(),
            routing_policy="trigger_match",
            routing_path="local",
            prompt_preview="Deploy new API...",
            prompt_length=42,
            emitted_at=datetime.now(UTC),
        )
        assert req.confidence == 0.85

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(Exception, match="timezone-aware"):
            ModelEmissionRequest(
                correlation_id=uuid4(),
                session_id="sess-123",
                selected_agent="agent-test",
                confidence=0.85,
                confidence_breakdown=_make_breakdown(),
                routing_policy="trigger_match",
                routing_path="local",
                prompt_preview="test",
                prompt_length=4,
                emitted_at=datetime(2026, 1, 1, 0, 0, 0),  # naive  # noqa: DTZ001
            )


# ---------------------------------------------------------------------------
# ModelEmissionResult
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelEmissionResult:
    def test_success(self) -> None:
        result = ModelEmissionResult(
            success=True,
            correlation_id=uuid4(),
            topics_emitted=("routing.decisions.v1",),
            duration_ms=12.5,
        )
        assert result.error is None

    def test_failure(self) -> None:
        result = ModelEmissionResult(
            success=False,
            correlation_id=uuid4(),
            error="Kafka connection refused",
        )
        assert result.error == "Kafka connection refused"
        assert result.topics_emitted == ()


# ---------------------------------------------------------------------------
# ModelAgentStatsEntry
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAgentStatsEntry:
    def test_construction(self) -> None:
        entry = ModelAgentStatsEntry(
            agent_name="agent-test",
            total_routings=100,
            successful_routings=90,
            success_rate=0.9,
            avg_confidence=0.85,
            last_routed_at=datetime.now(UTC),
        )
        assert entry.agent_name == "agent-test"

    def test_successful_exceeds_total_rejected(self) -> None:
        with pytest.raises(Exception, match="cannot exceed"):
            ModelAgentStatsEntry(
                agent_name="agent-test",
                total_routings=5,
                successful_routings=10,
            )

    def test_naive_datetime_rejected(self) -> None:
        with pytest.raises(Exception, match="timezone-aware"):
            ModelAgentStatsEntry(
                agent_name="agent-test",
                last_routed_at=datetime(2026, 1, 1),  # naive  # noqa: DTZ001
            )


# ---------------------------------------------------------------------------
# ModelAgentRoutingStats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelAgentRoutingStats:
    def test_empty_construction(self) -> None:
        stats = ModelAgentRoutingStats()
        assert stats.entries == ()
        assert stats.total_routing_decisions == 0
        assert stats.snapshot_at is None

    def test_with_entries(self) -> None:
        entry = ModelAgentStatsEntry(agent_name="agent-test", total_routings=10)
        stats = ModelAgentRoutingStats(
            entries=(entry,),
            total_routing_decisions=10,
            snapshot_at=datetime.now(UTC),
        )
        assert len(stats.entries) == 1

    def test_naive_snapshot_rejected(self) -> None:
        with pytest.raises(Exception, match="timezone-aware"):
            ModelAgentRoutingStats(
                snapshot_at=datetime(2026, 1, 1),  # naive  # noqa: DTZ001
            )


# ---------------------------------------------------------------------------
# Re-export completeness
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRoutingModelsReexports:
    def test_all_exports_importable(self) -> None:
        from omniclaude import routing_models

        expected = {
            "ModelAgentDefinition",
            "ModelAgentRoutingStats",
            "ModelAgentStatsEntry",
            "ModelConfidenceBreakdown",
            "ModelEmissionRequest",
            "ModelEmissionResult",
            "ModelRoutingCandidate",
            "ModelRoutingRequest",
            "ModelRoutingResult",
        }
        assert expected == set(routing_models.__all__)

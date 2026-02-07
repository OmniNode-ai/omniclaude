# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for routing models (OMN-1924).

Validates Pydantic model constraints for all routing models:
- ModelConfidenceBreakdown
- ModelAgentDefinition
- ModelRoutingRequest
- ModelRoutingResult
- ModelEmissionRequest
- ModelEmissionResult
- ModelAgentStatsEntry
- ModelAgentRoutingStats

Tests cover: frozen enforcement, extra fields rejection,
field validation (bounds, types), and serialization roundtrips.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from omniclaude.nodes.routing_models import (
    ModelAgentDefinition,
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
    ModelConfidenceBreakdown,
    ModelEmissionRequest,
    ModelEmissionResult,
    ModelRoutingRequest,
    ModelRoutingResult,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Helper Factories
# =============================================================================


def make_confidence_breakdown(**overrides: object) -> ModelConfidenceBreakdown:
    """Create a valid confidence breakdown with sensible defaults."""
    defaults: dict[str, object] = {
        "total": 0.85,
        "trigger_score": 0.9,
        "context_score": 0.8,
        "capability_score": 0.7,
        "historical_score": 0.6,
        "explanation": "Strong trigger match on 'debug'",
    }
    defaults.update(overrides)
    return ModelConfidenceBreakdown(**defaults)  # type: ignore[arg-type]


def make_agent_definition(**overrides: object) -> ModelAgentDefinition:
    """Create a valid agent definition with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "agent-debug",
        "agent_type": "debug",
        "description": "Debug and troubleshoot issues",
        "explicit_triggers": ("debug", "error", "troubleshoot"),
        "context_triggers": ("debugging an issue",),
        "domain": "debugging",
    }
    defaults.update(overrides)
    return ModelAgentDefinition(**defaults)  # type: ignore[arg-type]


def make_stats_entry(**overrides: object) -> ModelAgentStatsEntry:
    """Create a valid agent stats entry with sensible defaults."""
    defaults: dict[str, object] = {
        "agent_name": "agent-debug",
        "total_routes": 100,
        "success_count": 90,
        "success_rate": 0.9,
        "avg_confidence": 0.85,
    }
    defaults.update(overrides)
    return ModelAgentStatsEntry(**defaults)  # type: ignore[arg-type]


def make_routing_stats(**overrides: object) -> ModelAgentRoutingStats:
    """Create valid routing stats with sensible defaults."""
    defaults: dict[str, object] = {
        "entries": (make_stats_entry(),),
        "total_decisions": 100,
        "stats_window_seconds": 3600,
    }
    defaults.update(overrides)
    return ModelAgentRoutingStats(**defaults)  # type: ignore[arg-type]


def make_routing_request(**overrides: object) -> ModelRoutingRequest:
    """Create a valid routing request with sensible defaults."""
    defaults: dict[str, object] = {
        "prompt": "help me debug this error",
        "correlation_id": uuid4(),
        "agent_registry": (make_agent_definition(),),
        "confidence_threshold": 0.5,
    }
    defaults.update(overrides)
    return ModelRoutingRequest(**defaults)  # type: ignore[arg-type]


def make_routing_result(**overrides: object) -> ModelRoutingResult:
    """Create a valid routing result with sensible defaults."""
    defaults: dict[str, object] = {
        "selected_agent": "agent-debug",
        "confidence": 0.85,
        "confidence_breakdown": make_confidence_breakdown(),
        "routing_policy": "trigger_match",
        "routing_path": "local",
    }
    defaults.update(overrides)
    return ModelRoutingResult(**defaults)  # type: ignore[arg-type]


def make_emission_request(**overrides: object) -> ModelEmissionRequest:
    """Create a valid emission request with sensible defaults."""
    defaults: dict[str, object] = {
        "correlation_id": uuid4(),
        "session_id": "test-session-123",
        "selected_agent": "agent-debug",
        "confidence": 0.85,
        "confidence_breakdown": make_confidence_breakdown(),
        "routing_policy": "trigger_match",
        "routing_path": "local",
        "topic": "evt",
        "prompt_preview": "help me debug this error",
    }
    defaults.update(overrides)
    return ModelEmissionRequest(**defaults)  # type: ignore[arg-type]


def make_emission_result(**overrides: object) -> ModelEmissionResult:
    """Create a valid emission result with sensible defaults."""
    defaults: dict[str, object] = {
        "correlation_id": uuid4(),
        "emitted": True,
        "topic_name": "onex.evt.omniclaude.routing-decision.v1",
    }
    defaults.update(overrides)
    return ModelEmissionResult(**defaults)  # type: ignore[arg-type]


# =============================================================================
# ModelConfidenceBreakdown Tests
# =============================================================================


class TestModelConfidenceBreakdownValid:
    """Tests for valid ModelConfidenceBreakdown construction."""

    def test_all_required_fields(self) -> None:
        breakdown = make_confidence_breakdown()
        assert breakdown.total == 0.85
        assert breakdown.trigger_score == 0.9
        assert breakdown.context_score == 0.8
        assert breakdown.capability_score == 0.7
        assert breakdown.historical_score == 0.6
        assert breakdown.explanation == "Strong trigger match on 'debug'"

    def test_boundary_zero(self) -> None:
        breakdown = make_confidence_breakdown(
            total=0.0,
            trigger_score=0.0,
            context_score=0.0,
            capability_score=0.0,
            historical_score=0.0,
        )
        assert breakdown.total == 0.0

    def test_boundary_one(self) -> None:
        breakdown = make_confidence_breakdown(
            total=1.0,
            trigger_score=1.0,
            context_score=1.0,
            capability_score=1.0,
            historical_score=1.0,
        )
        assert breakdown.total == 1.0


class TestModelConfidenceBreakdownValidation:
    """Tests for ModelConfidenceBreakdown field validation."""

    def test_score_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_confidence_breakdown(total=-0.1)

    def test_score_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_confidence_breakdown(trigger_score=1.1)

    def test_empty_explanation_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_confidence_breakdown(explanation="")


class TestModelConfidenceBreakdownImmutability:
    """Tests for ModelConfidenceBreakdown frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        breakdown = make_confidence_breakdown()
        with pytest.raises(ValidationError):
            breakdown.total = 0.5  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelConfidenceBreakdown(
                total=0.85,
                trigger_score=0.9,
                context_score=0.8,
                capability_score=0.7,
                historical_score=0.6,
                explanation="test",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelConfidenceBreakdownSerialization:
    """Tests for ModelConfidenceBreakdown serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_confidence_breakdown()
        json_str = original.model_dump_json()
        restored = ModelConfidenceBreakdown.model_validate_json(json_str)
        assert restored == original

    def test_dict_roundtrip(self) -> None:
        original = make_confidence_breakdown()
        data = original.model_dump()
        restored = ModelConfidenceBreakdown.model_validate(data)
        assert restored == original


# =============================================================================
# ModelAgentDefinition Tests
# =============================================================================


class TestModelAgentDefinitionValid:
    """Tests for valid ModelAgentDefinition construction."""

    def test_all_fields(self) -> None:
        agent = make_agent_definition()
        assert agent.name == "agent-debug"
        assert agent.agent_type == "debug"
        assert agent.description == "Debug and troubleshoot issues"
        assert agent.explicit_triggers == ("debug", "error", "troubleshoot")
        assert agent.context_triggers == ("debugging an issue",)
        assert agent.domain == "debugging"

    def test_defaults(self) -> None:
        agent = ModelAgentDefinition(
            name="agent-test",
            agent_type="test",
            description="Test agent",
        )
        assert agent.explicit_triggers == ()
        assert agent.context_triggers == ()
        assert agent.domain == "general"


class TestModelAgentDefinitionValidation:
    """Tests for ModelAgentDefinition field validation."""

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_agent_definition(name="")

    def test_empty_description_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_agent_definition(description="")


class TestModelAgentDefinitionImmutability:
    """Tests for ModelAgentDefinition frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        agent = make_agent_definition()
        with pytest.raises(ValidationError):
            agent.name = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelAgentDefinition(
                name="agent-test",
                agent_type="test",
                description="Test agent",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelAgentDefinitionSerialization:
    """Tests for ModelAgentDefinition serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_agent_definition()
        json_str = original.model_dump_json()
        restored = ModelAgentDefinition.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# ModelAgentStatsEntry Tests
# =============================================================================


class TestModelAgentStatsEntryValid:
    """Tests for valid ModelAgentStatsEntry construction."""

    def test_all_fields(self) -> None:
        entry = make_stats_entry()
        assert entry.agent_name == "agent-debug"
        assert entry.total_routes == 100
        assert entry.success_count == 90
        assert entry.success_rate == 0.9
        assert entry.avg_confidence == 0.85

    def test_zero_routes(self) -> None:
        entry = make_stats_entry(
            total_routes=0,
            success_count=0,
            success_rate=0.0,
            avg_confidence=0.0,
        )
        assert entry.total_routes == 0


class TestModelAgentStatsEntryValidation:
    """Tests for ModelAgentStatsEntry field validation."""

    def test_negative_routes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_stats_entry(total_routes=-1)

    def test_success_rate_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_stats_entry(success_rate=1.1)


class TestModelAgentStatsEntryImmutability:
    """Tests for ModelAgentStatsEntry frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        entry = make_stats_entry()
        with pytest.raises(ValidationError):
            entry.agent_name = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelAgentStatsEntry(
                agent_name="agent-test",
                total_routes=10,
                success_count=9,
                success_rate=0.9,
                avg_confidence=0.8,
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelAgentStatsEntrySerialization:
    """Tests for ModelAgentStatsEntry serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_stats_entry()
        json_str = original.model_dump_json()
        restored = ModelAgentStatsEntry.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# ModelAgentRoutingStats Tests
# =============================================================================


class TestModelAgentRoutingStatsValid:
    """Tests for valid ModelAgentRoutingStats construction."""

    def test_with_entries(self) -> None:
        stats = make_routing_stats()
        assert len(stats.entries) == 1
        assert stats.total_decisions == 100
        assert stats.stats_window_seconds == 3600

    def test_empty_entries(self) -> None:
        stats = make_routing_stats(entries=(), total_decisions=0)
        assert len(stats.entries) == 0


class TestModelAgentRoutingStatsImmutability:
    """Tests for ModelAgentRoutingStats frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        stats = make_routing_stats()
        with pytest.raises(ValidationError):
            stats.total_decisions = 200  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelAgentRoutingStats(
                entries=(),
                total_decisions=0,
                stats_window_seconds=3600,
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelAgentRoutingStatsSerialization:
    """Tests for ModelAgentRoutingStats serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_routing_stats()
        json_str = original.model_dump_json()
        restored = ModelAgentRoutingStats.model_validate_json(json_str)
        assert restored == original

    def test_nested_serialization(self) -> None:
        """Verify nested ModelAgentStatsEntry survives roundtrip."""
        entry1 = make_stats_entry(agent_name="agent-debug")
        entry2 = make_stats_entry(agent_name="agent-testing", total_routes=50)
        stats = make_routing_stats(entries=(entry1, entry2), total_decisions=150)
        json_str = stats.model_dump_json()
        restored = ModelAgentRoutingStats.model_validate_json(json_str)
        assert len(restored.entries) == 2
        assert restored.entries[0].agent_name == "agent-debug"
        assert restored.entries[1].agent_name == "agent-testing"


# =============================================================================
# ModelRoutingRequest Tests
# =============================================================================


class TestModelRoutingRequestValid:
    """Tests for valid ModelRoutingRequest construction."""

    def test_minimal_request(self) -> None:
        req = make_routing_request()
        assert req.prompt == "help me debug this error"
        assert req.confidence_threshold == 0.5
        assert req.historical_stats is None

    def test_with_historical_stats(self) -> None:
        stats = make_routing_stats()
        req = make_routing_request(historical_stats=stats)
        assert req.historical_stats is not None
        assert req.historical_stats.total_decisions == 100

    def test_custom_threshold(self) -> None:
        req = make_routing_request(confidence_threshold=0.8)
        assert req.confidence_threshold == 0.8

    def test_multiple_agents_in_registry(self) -> None:
        agents = (
            make_agent_definition(name="agent-debug", agent_type="debug"),
            make_agent_definition(name="agent-testing", agent_type="testing"),
        )
        req = make_routing_request(agent_registry=agents)
        assert len(req.agent_registry) == 2


class TestModelRoutingRequestValidation:
    """Tests for ModelRoutingRequest field validation."""

    def test_empty_prompt_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_request(prompt="")

    def test_threshold_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_request(confidence_threshold=1.1)

    def test_threshold_below_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_request(confidence_threshold=-0.1)


class TestModelRoutingRequestImmutability:
    """Tests for ModelRoutingRequest frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        req = make_routing_request()
        with pytest.raises(ValidationError):
            req.prompt = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                prompt="test",
                correlation_id=uuid4(),
                agent_registry=(),
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelRoutingRequestSerialization:
    """Tests for ModelRoutingRequest serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_routing_request()
        json_str = original.model_dump_json()
        restored = ModelRoutingRequest.model_validate_json(json_str)
        assert restored == original

    def test_deep_nested_roundtrip(self) -> None:
        """Verify deeply nested models survive roundtrip."""
        stats = make_routing_stats()
        req = make_routing_request(historical_stats=stats)
        json_str = req.model_dump_json()
        restored = ModelRoutingRequest.model_validate_json(json_str)
        assert restored.historical_stats is not None
        assert restored.historical_stats.entries[0].agent_name == "agent-debug"


# =============================================================================
# ModelRoutingResult Tests
# =============================================================================


class TestModelRoutingResultValid:
    """Tests for valid ModelRoutingResult construction."""

    def test_trigger_match(self) -> None:
        result = make_routing_result()
        assert result.selected_agent == "agent-debug"
        assert result.confidence == 0.85
        assert result.routing_policy == "trigger_match"
        assert result.routing_path == "local"

    def test_all_routing_policies(self) -> None:
        for policy in ("trigger_match", "explicit_request", "fallback_default"):
            result = make_routing_result(routing_policy=policy)
            assert result.routing_policy == policy

    def test_all_routing_paths(self) -> None:
        for path in ("event", "local", "hybrid"):
            result = make_routing_result(routing_path=path)
            assert result.routing_path == path


class TestModelRoutingResultValidation:
    """Tests for ModelRoutingResult field validation."""

    def test_invalid_routing_policy_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_result(routing_policy="invalid_policy")

    def test_invalid_routing_path_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_result(routing_path="invalid_path")

    def test_confidence_above_one_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_result(confidence=1.1)

    def test_empty_agent_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_routing_result(selected_agent="")


class TestModelRoutingResultImmutability:
    """Tests for ModelRoutingResult frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        result = make_routing_result()
        with pytest.raises(ValidationError):
            result.selected_agent = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingResult(
                selected_agent="agent-test",
                confidence=0.85,
                confidence_breakdown=make_confidence_breakdown(),
                routing_policy="trigger_match",
                routing_path="local",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelRoutingResultSerialization:
    """Tests for ModelRoutingResult serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_routing_result()
        json_str = original.model_dump_json()
        restored = ModelRoutingResult.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# ModelEmissionRequest Tests
# =============================================================================


class TestModelEmissionRequestValid:
    """Tests for valid ModelEmissionRequest construction."""

    def test_evt_topic(self) -> None:
        req = make_emission_request(topic="evt")
        assert req.topic == "evt"

    def test_cmd_topic(self) -> None:
        req = make_emission_request(topic="cmd")
        assert req.topic == "cmd"


class TestModelEmissionRequestValidation:
    """Tests for ModelEmissionRequest field validation."""

    def test_invalid_topic_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_emission_request(topic="invalid")

    def test_prompt_preview_max_length(self) -> None:
        req = make_emission_request(prompt_preview="x" * 100)
        assert len(req.prompt_preview) == 100

    def test_prompt_preview_over_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_emission_request(prompt_preview="x" * 101)


class TestModelEmissionRequestImmutability:
    """Tests for ModelEmissionRequest frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        req = make_emission_request()
        with pytest.raises(ValidationError):
            req.session_id = "different"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelEmissionRequest(
                correlation_id=uuid4(),
                session_id="test",
                selected_agent="agent-test",
                confidence=0.85,
                confidence_breakdown=make_confidence_breakdown(),
                routing_policy="trigger_match",
                routing_path="local",
                topic="evt",
                prompt_preview="test",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelEmissionRequestSerialization:
    """Tests for ModelEmissionRequest serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_emission_request()
        json_str = original.model_dump_json()
        restored = ModelEmissionRequest.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# ModelEmissionResult Tests
# =============================================================================


class TestModelEmissionResultValid:
    """Tests for valid ModelEmissionResult construction."""

    def test_success(self) -> None:
        result = make_emission_result()
        assert result.emitted is True
        assert result.error is None

    def test_failure(self) -> None:
        result = make_emission_result(
            emitted=False,
            error="Kafka unavailable",
        )
        assert result.emitted is False
        assert result.error == "Kafka unavailable"


class TestModelEmissionResultImmutability:
    """Tests for ModelEmissionResult frozen enforcement."""

    def test_frozen_prevents_mutation(self) -> None:
        result = make_emission_result()
        with pytest.raises(ValidationError):
            result.emitted = False  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            ModelEmissionResult(
                correlation_id=uuid4(),
                emitted=True,
                topic_name="test.topic",
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra_field" in str(exc_info.value)


class TestModelEmissionResultSerialization:
    """Tests for ModelEmissionResult serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = make_emission_result()
        json_str = original.model_dump_json()
        restored = ModelEmissionResult.model_validate_json(json_str)
        assert restored == original


# =============================================================================
# Cross-Model Integration Tests
# =============================================================================


class TestCrossModelIntegration:
    """Tests for model composition and nesting."""

    def test_full_routing_pipeline_roundtrip(self) -> None:
        """Verify a full request->result pipeline serializes correctly."""
        request = make_routing_request(
            historical_stats=make_routing_stats(
                entries=(
                    make_stats_entry(agent_name="agent-debug"),
                    make_stats_entry(agent_name="agent-testing"),
                ),
                total_decisions=200,
            ),
        )
        result = make_routing_result()

        # Both should survive JSON roundtrip independently
        req_json = request.model_dump_json()
        res_json = result.model_dump_json()

        restored_req = ModelRoutingRequest.model_validate_json(req_json)
        restored_res = ModelRoutingResult.model_validate_json(res_json)

        assert restored_req == request
        assert restored_res == result
        assert restored_req.historical_stats is not None
        assert len(restored_req.historical_stats.entries) == 2

    def test_emission_request_from_routing_result(self) -> None:
        """Verify emission request can carry routing result data."""
        result = make_routing_result()
        emission = make_emission_request(
            selected_agent=result.selected_agent,
            confidence=result.confidence,
            confidence_breakdown=result.confidence_breakdown,
            routing_policy=result.routing_policy,
            routing_path=result.routing_path,
        )
        assert emission.selected_agent == result.selected_agent
        assert emission.confidence == result.confidence

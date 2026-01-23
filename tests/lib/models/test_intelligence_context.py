# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for IntelligenceContext models.

These tests verify the Pydantic models for intelligence context:
- IntelligenceContext: Main intelligence context model with validation
- NodeTypeIntelligence: Node type-specific intelligence patterns
- DEFAULT_NODE_TYPE_INTELLIGENCE: Default patterns for each node type
- get_default_intelligence(): Factory function for default contexts
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.lib.models.intelligence_context import (
    DEFAULT_NODE_TYPE_INTELLIGENCE,
    IntelligenceContext,
    NodeTypeIntelligence,
    get_default_intelligence,
)


class TestIntelligenceContextDefaults:
    """Tests for IntelligenceContext default field values."""

    def test_all_list_fields_default_to_empty_list(self) -> None:
        """Test that all list fields default to empty lists."""
        context = IntelligenceContext()

        assert context.node_type_patterns == []
        assert context.common_operations == []
        assert context.required_mixins == []
        assert context.error_scenarios == []
        assert context.domain_best_practices == []
        assert context.code_examples == []
        assert context.anti_patterns == []
        assert context.recommended_dependencies == []
        assert context.testing_recommendations == []
        assert context.security_considerations == []
        assert context.rag_sources == []

    def test_performance_targets_defaults_to_empty_dict(self) -> None:
        """Test that performance_targets defaults to empty dict."""
        context = IntelligenceContext()

        assert context.performance_targets == {}

    def test_confidence_score_defaults_to_zero(self) -> None:
        """Test that confidence_score defaults to 0.0."""
        context = IntelligenceContext()

        assert context.confidence_score == 0.0

    def test_can_create_context_with_no_arguments(self) -> None:
        """Test that IntelligenceContext can be instantiated with no arguments."""
        context = IntelligenceContext()

        # Should be a valid instance
        assert isinstance(context, IntelligenceContext)


class TestIntelligenceContextValidation:
    """Tests for IntelligenceContext validation behavior."""

    def test_confidence_score_accepts_zero(self) -> None:
        """Test that confidence_score accepts 0.0."""
        context = IntelligenceContext(confidence_score=0.0)
        assert context.confidence_score == 0.0

    def test_confidence_score_accepts_one(self) -> None:
        """Test that confidence_score accepts 1.0."""
        context = IntelligenceContext(confidence_score=1.0)
        assert context.confidence_score == 1.0

    def test_confidence_score_accepts_value_between_zero_and_one(self) -> None:
        """Test that confidence_score accepts values between 0.0 and 1.0."""
        context = IntelligenceContext(confidence_score=0.5)
        assert context.confidence_score == 0.5

        context = IntelligenceContext(confidence_score=0.75)
        assert context.confidence_score == 0.75

    def test_confidence_score_rejects_negative_value(self) -> None:
        """Test that confidence_score rejects values below 0.0."""
        with pytest.raises(ValidationError) as exc_info:
            IntelligenceContext(confidence_score=-0.1)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("confidence_score",)
        assert "greater than or equal to 0" in errors[0]["msg"]

    def test_confidence_score_rejects_value_above_one(self) -> None:
        """Test that confidence_score rejects values above 1.0."""
        with pytest.raises(ValidationError) as exc_info:
            IntelligenceContext(confidence_score=1.1)

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["loc"] == ("confidence_score",)
        assert "less than or equal to 1" in errors[0]["msg"]

    def test_rejects_extra_fields(self) -> None:
        """Test that IntelligenceContext rejects extra fields (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            IntelligenceContext(unknown_field="value")  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["type"] == "extra_forbidden"

    def test_validate_assignment_enabled(self) -> None:
        """Test that validate_assignment is enabled for IntelligenceContext."""
        context = IntelligenceContext()

        # Should raise when assigning invalid confidence_score
        with pytest.raises(ValidationError):
            context.confidence_score = 1.5


class TestIntelligenceContextWithData:
    """Tests for IntelligenceContext with actual data."""

    def test_can_set_all_fields(self) -> None:
        """Test that all fields can be set with valid data."""
        context = IntelligenceContext(
            node_type_patterns=["Use connection pooling"],
            common_operations=["create", "read"],
            required_mixins=["MixinRetry"],
            performance_targets={"max_response_time_ms": 500},
            error_scenarios=["Connection timeout"],
            domain_best_practices=["Use prepared statements"],
            code_examples=[{"name": "example", "code": "pass"}],
            anti_patterns=["Avoid N+1 queries"],
            recommended_dependencies=[{"name": "PostgreSQL", "type": "database"}],
            testing_recommendations=["Use integration tests"],
            security_considerations=["Sanitize inputs"],
            rag_sources=["code_analysis"],
            confidence_score=0.8,
        )

        assert context.node_type_patterns == ["Use connection pooling"]
        assert context.common_operations == ["create", "read"]
        assert context.required_mixins == ["MixinRetry"]
        assert context.performance_targets == {"max_response_time_ms": 500}
        assert context.error_scenarios == ["Connection timeout"]
        assert context.domain_best_practices == ["Use prepared statements"]
        assert context.code_examples == [{"name": "example", "code": "pass"}]
        assert context.anti_patterns == ["Avoid N+1 queries"]
        assert context.recommended_dependencies == [{"name": "PostgreSQL", "type": "database"}]
        assert context.testing_recommendations == ["Use integration tests"]
        assert context.security_considerations == ["Sanitize inputs"]
        assert context.rag_sources == ["code_analysis"]
        assert context.confidence_score == 0.8


class TestNodeTypeIntelligenceDefaults:
    """Tests for NodeTypeIntelligence default field values."""

    def test_node_type_is_required(self) -> None:
        """Test that node_type is a required field."""
        with pytest.raises(ValidationError) as exc_info:
            NodeTypeIntelligence()  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("node_type",) for e in errors)

    def test_default_patterns_defaults_to_empty_list(self) -> None:
        """Test that default_patterns defaults to empty list."""
        intel = NodeTypeIntelligence(node_type="TEST")
        assert intel.default_patterns == []

    def test_typical_operations_defaults_to_empty_list(self) -> None:
        """Test that typical_operations defaults to empty list."""
        intel = NodeTypeIntelligence(node_type="TEST")
        assert intel.typical_operations == []

    def test_common_mixins_defaults_to_empty_list(self) -> None:
        """Test that common_mixins defaults to empty list."""
        intel = NodeTypeIntelligence(node_type="TEST")
        assert intel.common_mixins == []

    def test_performance_baseline_defaults_to_empty_dict(self) -> None:
        """Test that performance_baseline defaults to empty dict."""
        intel = NodeTypeIntelligence(node_type="TEST")
        assert intel.performance_baseline == {}


class TestNodeTypeIntelligenceValidation:
    """Tests for NodeTypeIntelligence validation behavior."""

    def test_can_create_with_node_type_only(self) -> None:
        """Test that NodeTypeIntelligence can be created with only node_type."""
        intel = NodeTypeIntelligence(node_type="EFFECT")
        assert intel.node_type == "EFFECT"

    def test_can_create_with_all_fields(self) -> None:
        """Test that NodeTypeIntelligence can be created with all fields."""
        intel = NodeTypeIntelligence(
            node_type="COMPUTE",
            default_patterns=["Ensure pure functions"],
            typical_operations=["calculate", "transform"],
            common_mixins=["MixinCaching"],
            performance_baseline={"cpu_bound": True},
        )

        assert intel.node_type == "COMPUTE"
        assert intel.default_patterns == ["Ensure pure functions"]
        assert intel.typical_operations == ["calculate", "transform"]
        assert intel.common_mixins == ["MixinCaching"]
        assert intel.performance_baseline == {"cpu_bound": True}

    def test_rejects_extra_fields(self) -> None:
        """Test that NodeTypeIntelligence rejects extra fields (extra='forbid')."""
        with pytest.raises(ValidationError) as exc_info:
            NodeTypeIntelligence(node_type="TEST", extra_field="value")  # type: ignore[call-arg]

        errors = exc_info.value.errors()
        assert len(errors) == 1
        assert errors[0]["type"] == "extra_forbidden"


class TestDefaultNodeTypeIntelligenceDict:
    """Tests for DEFAULT_NODE_TYPE_INTELLIGENCE dictionary."""

    def test_contains_effect_key(self) -> None:
        """Test that DEFAULT_NODE_TYPE_INTELLIGENCE contains EFFECT key."""
        assert "EFFECT" in DEFAULT_NODE_TYPE_INTELLIGENCE

    def test_contains_compute_key(self) -> None:
        """Test that DEFAULT_NODE_TYPE_INTELLIGENCE contains COMPUTE key."""
        assert "COMPUTE" in DEFAULT_NODE_TYPE_INTELLIGENCE

    def test_contains_reducer_key(self) -> None:
        """Test that DEFAULT_NODE_TYPE_INTELLIGENCE contains REDUCER key."""
        assert "REDUCER" in DEFAULT_NODE_TYPE_INTELLIGENCE

    def test_contains_orchestrator_key(self) -> None:
        """Test that DEFAULT_NODE_TYPE_INTELLIGENCE contains ORCHESTRATOR key."""
        assert "ORCHESTRATOR" in DEFAULT_NODE_TYPE_INTELLIGENCE

    def test_contains_exactly_four_keys(self) -> None:
        """Test that DEFAULT_NODE_TYPE_INTELLIGENCE contains exactly 4 node types."""
        assert len(DEFAULT_NODE_TYPE_INTELLIGENCE) == 4

    def test_all_values_are_node_type_intelligence(self) -> None:
        """Test that all values are NodeTypeIntelligence instances."""
        for key, value in DEFAULT_NODE_TYPE_INTELLIGENCE.items():
            assert isinstance(value, NodeTypeIntelligence), f"Key {key} is not NodeTypeIntelligence"

    def test_effect_has_appropriate_patterns(self) -> None:
        """Test that EFFECT has appropriate patterns for I/O operations."""
        effect = DEFAULT_NODE_TYPE_INTELLIGENCE["EFFECT"]

        assert effect.node_type == "EFFECT"
        # Should have patterns related to external I/O
        patterns_text = " ".join(effect.default_patterns).lower()
        assert "connection" in patterns_text or "retry" in patterns_text
        # Should have CRUD-like operations
        assert any(op in effect.typical_operations for op in ["create", "read", "update", "delete"])
        # Should have retry/event mixins
        assert "MixinRetry" in effect.common_mixins or "MixinEventBus" in effect.common_mixins

    def test_compute_has_appropriate_patterns(self) -> None:
        """Test that COMPUTE has appropriate patterns for pure computations."""
        compute = DEFAULT_NODE_TYPE_INTELLIGENCE["COMPUTE"]

        assert compute.node_type == "COMPUTE"
        # Should have patterns related to pure functions
        patterns_text = " ".join(compute.default_patterns).lower()
        assert "pure" in patterns_text or "deterministic" in patterns_text
        # Should have computational operations
        assert any(
            op in compute.typical_operations for op in ["calculate", "transform", "validate"]
        )
        # Should have caching/validation mixins
        assert "MixinCaching" in compute.common_mixins or "MixinValidation" in compute.common_mixins

    def test_reducer_has_appropriate_patterns(self) -> None:
        """Test that REDUCER has appropriate patterns for aggregation."""
        reducer = DEFAULT_NODE_TYPE_INTELLIGENCE["REDUCER"]

        assert reducer.node_type == "REDUCER"
        # Should have patterns related to state aggregation
        patterns_text = " ".join(reducer.default_patterns).lower()
        assert "aggregate" in patterns_text or "state" in patterns_text
        # Should have aggregation operations
        assert any(op in reducer.typical_operations for op in ["aggregate", "reduce", "merge"])

    def test_orchestrator_has_appropriate_patterns(self) -> None:
        """Test that ORCHESTRATOR has appropriate patterns for coordination."""
        orchestrator = DEFAULT_NODE_TYPE_INTELLIGENCE["ORCHESTRATOR"]

        assert orchestrator.node_type == "ORCHESTRATOR"
        # Should have patterns related to coordination
        patterns_text = " ".join(orchestrator.default_patterns).lower()
        assert (
            "coordinate" in patterns_text or "workflow" in patterns_text or "lease" in patterns_text
        )
        # Should have coordination operations
        assert any(
            op in orchestrator.typical_operations
            for op in ["coordinate", "orchestrate", "schedule"]
        )


class TestGetDefaultIntelligence:
    """Tests for get_default_intelligence() factory function."""

    def test_returns_intelligence_context_for_effect(self) -> None:
        """Test that get_default_intelligence returns IntelligenceContext for EFFECT."""
        result = get_default_intelligence("EFFECT")

        assert result is not None
        assert isinstance(result, IntelligenceContext)

    def test_returns_intelligence_context_for_compute(self) -> None:
        """Test that get_default_intelligence returns IntelligenceContext for COMPUTE."""
        result = get_default_intelligence("COMPUTE")

        assert result is not None
        assert isinstance(result, IntelligenceContext)

    def test_returns_intelligence_context_for_reducer(self) -> None:
        """Test that get_default_intelligence returns IntelligenceContext for REDUCER."""
        result = get_default_intelligence("REDUCER")

        assert result is not None
        assert isinstance(result, IntelligenceContext)

    def test_returns_intelligence_context_for_orchestrator(self) -> None:
        """Test that get_default_intelligence returns IntelligenceContext for ORCHESTRATOR."""
        result = get_default_intelligence("ORCHESTRATOR")

        assert result is not None
        assert isinstance(result, IntelligenceContext)

    def test_returns_none_for_unknown_node_type(self) -> None:
        """Test that get_default_intelligence returns None for unknown node types."""
        result = get_default_intelligence("UNKNOWN")
        assert result is None

    def test_returns_none_for_empty_string(self) -> None:
        """Test that get_default_intelligence returns None for empty string."""
        result = get_default_intelligence("")
        assert result is None

    def test_returns_none_for_lowercase_node_type(self) -> None:
        """Test that get_default_intelligence returns None for lowercase node types.

        Node types are case-sensitive and must be uppercase.
        """
        result = get_default_intelligence("effect")
        assert result is None

    def test_sets_confidence_score_to_half_for_defaults(self) -> None:
        """Test that default intelligence has confidence_score of 0.5."""
        result = get_default_intelligence("EFFECT")

        assert result is not None
        assert result.confidence_score == 0.5

    def test_includes_default_node_type_intelligence_as_rag_source(self) -> None:
        """Test that default intelligence includes 'default_node_type_intelligence' in rag_sources."""
        result = get_default_intelligence("COMPUTE")

        assert result is not None
        assert "default_node_type_intelligence" in result.rag_sources

    def test_populates_node_type_patterns_from_default_patterns(self) -> None:
        """Test that node_type_patterns is populated from NodeTypeIntelligence.default_patterns."""
        result = get_default_intelligence("EFFECT")

        assert result is not None
        expected = DEFAULT_NODE_TYPE_INTELLIGENCE["EFFECT"].default_patterns
        assert result.node_type_patterns == expected

    def test_populates_common_operations_from_typical_operations(self) -> None:
        """Test that common_operations is populated from NodeTypeIntelligence.typical_operations."""
        result = get_default_intelligence("COMPUTE")

        assert result is not None
        expected = DEFAULT_NODE_TYPE_INTELLIGENCE["COMPUTE"].typical_operations
        assert result.common_operations == expected

    def test_populates_required_mixins_from_common_mixins(self) -> None:
        """Test that required_mixins is populated from NodeTypeIntelligence.common_mixins."""
        result = get_default_intelligence("REDUCER")

        assert result is not None
        expected = DEFAULT_NODE_TYPE_INTELLIGENCE["REDUCER"].common_mixins
        assert result.required_mixins == expected

    def test_populates_performance_targets_from_performance_baseline(self) -> None:
        """Test that performance_targets is populated from NodeTypeIntelligence.performance_baseline."""
        result = get_default_intelligence("ORCHESTRATOR")

        assert result is not None
        expected = DEFAULT_NODE_TYPE_INTELLIGENCE["ORCHESTRATOR"].performance_baseline
        assert result.performance_targets == expected


class TestIntelligenceContextSerialization:
    """Tests for IntelligenceContext serialization."""

    def test_model_dump_returns_dict(self) -> None:
        """Test that model_dump returns a dictionary."""
        context = IntelligenceContext(confidence_score=0.7)
        result = context.model_dump()

        assert isinstance(result, dict)
        assert result["confidence_score"] == 0.7

    def test_model_dump_json_returns_string(self) -> None:
        """Test that model_dump_json returns a JSON string."""
        context = IntelligenceContext(confidence_score=0.7)
        result = context.model_dump_json()

        assert isinstance(result, str)
        assert "0.7" in result

    def test_can_recreate_from_dict(self) -> None:
        """Test that IntelligenceContext can be recreated from model_dump output."""
        original = IntelligenceContext(
            node_type_patterns=["pattern1"],
            confidence_score=0.8,
        )
        data = original.model_dump()
        recreated = IntelligenceContext(**data)

        assert recreated.node_type_patterns == original.node_type_patterns
        assert recreated.confidence_score == original.confidence_score

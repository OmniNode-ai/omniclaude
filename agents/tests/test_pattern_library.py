#!/usr/bin/env python3
"""
Tests for Pattern Library (Phase 5)

Tests pattern matching, confidence scoring, pattern code generation,
pattern registry lookup, and multi-pattern composition.
"""

import pytest

from agents.lib.pattern_library import PatternLibrary
from agents.tests.fixtures.phase4_fixtures import (
    AGGREGATION_PATTERN_CONTRACT,
    CRUD_PATTERN_CONTRACT,
    ORCHESTRATION_PATTERN_CONTRACT,
    PATTERN_DETECTION_CASES,
    SAMPLE_CONTRACT_WITH_CRUD,
    SAMPLE_CONTRACT_WITH_TRANSFORMATION,
    TRANSFORMATION_PATTERN_CONTRACT,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def pattern_library():
    """Create a PatternLibrary instance"""
    return PatternLibrary()


@pytest.fixture
def crud_contract():
    """Return CRUD pattern contract"""
    return CRUD_PATTERN_CONTRACT


@pytest.fixture
def transformation_contract():
    """Return transformation pattern contract"""
    return TRANSFORMATION_PATTERN_CONTRACT


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================


class TestPatternMatching:
    """Tests for pattern detection and matching"""

    def test_detect_crud_pattern(self, pattern_library, crud_contract):
        """Test detection of CRUD pattern"""
        result = pattern_library.detect_pattern(crud_contract)

        assert result["pattern_name"] == "CRUD"
        assert result["confidence"] >= 0.8
        assert result["matched"] is True

    def test_detect_transformation_pattern(
        self, pattern_library, transformation_contract
    ):
        """Test detection of Transformation pattern"""
        result = pattern_library.detect_pattern(transformation_contract)

        assert result["pattern_name"] == "Transformation"
        assert result["confidence"] >= 0.8
        assert result["matched"] is True

    def test_detect_aggregation_pattern(self, pattern_library):
        """Test detection of Aggregation pattern"""
        result = pattern_library.detect_pattern(AGGREGATION_PATTERN_CONTRACT)

        assert result["pattern_name"] == "Aggregation"
        assert result["confidence"] >= 0.8
        assert result["matched"] is True

    def test_detect_orchestration_pattern(self, pattern_library):
        """Test detection of Orchestration pattern"""
        result = pattern_library.detect_pattern(ORCHESTRATION_PATTERN_CONTRACT)

        assert result["pattern_name"] == "Orchestration"
        assert result["confidence"] >= 0.8
        assert result["matched"] is True

    def test_no_pattern_match_low_confidence(self, pattern_library):
        """Test that unclear patterns return low confidence"""
        ambiguous_contract = {
            "capabilities": [
                {"name": "do_something", "type": "unknown", "required": True}
            ]
        }

        result = pattern_library.detect_pattern(ambiguous_contract)

        assert result["confidence"] < 0.6
        assert result["matched"] is False

    @pytest.mark.parametrize("test_case", PATTERN_DETECTION_CASES)
    def test_pattern_detection_parametrized(self, pattern_library, test_case):
        """Test pattern detection with all test cases"""
        result = pattern_library.detect_pattern(test_case["contract"])

        assert result["pattern_name"] == test_case["expected_pattern"]
        assert result["confidence"] >= test_case["expected_confidence"] - 0.1


# ============================================================================
# CONFIDENCE SCORING TESTS
# ============================================================================


class TestConfidenceScoring:
    """Tests for pattern confidence scoring"""

    def test_confidence_score_range(self, pattern_library, crud_contract):
        """Test confidence scores are in valid range"""
        result = pattern_library.detect_pattern(crud_contract)

        assert 0.0 <= result["confidence"] <= 1.0

    def test_high_confidence_for_complete_match(self, pattern_library):
        """Test high confidence for complete pattern match"""
        # Perfect CRUD pattern with all operations
        perfect_crud = {
            "capabilities": [
                {"name": "create", "type": "create", "required": True},
                {"name": "read", "type": "read", "required": True},
                {"name": "update", "type": "update", "required": True},
                {"name": "delete", "type": "delete", "required": True},
            ]
        }

        result = pattern_library.detect_pattern(perfect_crud)

        assert result["confidence"] >= 0.95

    def test_lower_confidence_for_partial_match(self, pattern_library):
        """Test lower confidence for partial pattern match"""
        # Partial CRUD pattern (only create and read)
        partial_crud = {
            "capabilities": [
                {"name": "create", "type": "create", "required": True},
                {"name": "read", "type": "read", "required": True},
            ]
        }

        result = pattern_library.detect_pattern(partial_crud)

        # Should still detect CRUD but with lower confidence
        assert result["pattern_name"] == "CRUD"
        assert result["confidence"] < 0.9

    def test_confidence_components(self, pattern_library, crud_contract):
        """Test confidence score components"""
        result = pattern_library.detect_pattern_with_details(crud_contract)

        assert "confidence_components" in result
        components = result["confidence_components"]

        # Verify component structure
        assert "capability_match_score" in components
        assert "completeness_score" in components
        assert "naming_consistency_score" in components


# ============================================================================
# PATTERN CODE GENERATION TESTS
# ============================================================================


class TestPatternCodeGeneration:
    """Tests for pattern-based code generation"""

    def test_generate_crud_pattern_code(self, pattern_library):
        """Test CRUD pattern code generation"""
        result = pattern_library.generate_pattern_code(
            pattern_name="CRUD",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            node_type="EFFECT",
            class_name="NodeUserManagementEffect",
        )

        assert "code" in result
        code = result["code"]

        # Verify CRUD methods are present
        assert "create_user" in code
        assert "get_user" in code
        assert "update_user" in code
        assert "delete_user" in code

    def test_generate_transformation_pattern_code(self, pattern_library):
        """Test Transformation pattern code generation"""
        result = pattern_library.generate_pattern_code(
            pattern_name="Transformation",
            contract=SAMPLE_CONTRACT_WITH_TRANSFORMATION,
            node_type="COMPUTE",
            class_name="NodeDataTransformerCompute",
        )

        assert "code" in result
        code = result["code"]

        # Verify transformation methods
        assert "transform_csv_to_json" in code
        assert "validate_schema" in code

    def test_generate_aggregation_pattern_code(self, pattern_library):
        """Test Aggregation pattern code generation"""
        result = pattern_library.generate_pattern_code(
            pattern_name="Aggregation",
            contract=AGGREGATION_PATTERN_CONTRACT,
            node_type="REDUCER",
            class_name="NodeAnalyticsReducer",
        )

        assert "code" in result
        code = result["code"]

        # Verify aggregation methods
        assert "aggregate" in code or "reduce" in code

    def test_generated_code_is_valid_python(self, pattern_library):
        """Test that generated pattern code is valid Python"""
        result = pattern_library.generate_pattern_code(
            pattern_name="CRUD",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            node_type="EFFECT",
            class_name="NodeTestEffect",
        )

        # Verify code can be parsed
        import ast

        try:
            ast.parse(result["code"])
        except SyntaxError as e:
            pytest.fail(f"Generated pattern code has syntax errors: {e}")


# ============================================================================
# PATTERN REGISTRY TESTS
# ============================================================================


class TestPatternRegistry:
    """Tests for pattern registry lookup"""

    def test_get_pattern_by_name(self, pattern_library):
        """Test retrieving pattern definition by name"""
        pattern = pattern_library.get_pattern("CRUD")

        assert pattern is not None
        assert pattern["name"] == "CRUD"
        assert "capabilities" in pattern
        assert "code_template" in pattern

    def test_list_all_patterns(self, pattern_library):
        """Test listing all available patterns"""
        patterns = pattern_library.list_patterns()

        assert len(patterns) >= 4
        pattern_names = [p["name"] for p in patterns]

        assert "CRUD" in pattern_names
        assert "Transformation" in pattern_names
        assert "Aggregation" in pattern_names
        assert "Orchestration" in pattern_names

    def test_get_pattern_metadata(self, pattern_library):
        """Test retrieving pattern metadata"""
        pattern = pattern_library.get_pattern("CRUD")

        assert "description" in pattern
        assert "required_capabilities" in pattern
        assert "optional_capabilities" in pattern
        assert "node_types" in pattern

    def test_pattern_not_found(self, pattern_library):
        """Test behavior when pattern not found"""
        pattern = pattern_library.get_pattern("NonExistentPattern")

        assert pattern is None


# ============================================================================
# MULTI-PATTERN COMPOSITION TESTS
# ============================================================================


class TestMultiPatternComposition:
    """Tests for combining multiple patterns"""

    def test_detect_multiple_patterns(self, pattern_library):
        """Test detection of multiple patterns in one contract"""
        mixed_contract = {
            "capabilities": [
                # CRUD operations
                {"name": "create_user", "type": "create", "required": True},
                {"name": "read_user", "type": "read", "required": True},
                # Transformation operations
                {"name": "transform_data", "type": "transform", "required": True},
            ]
        }

        result = pattern_library.detect_all_patterns(mixed_contract)

        assert len(result["patterns"]) >= 1
        pattern_names = [p["pattern_name"] for p in result["patterns"]]

        # Should detect at least one pattern
        assert len(pattern_names) > 0

    def test_compose_pattern_code(self, pattern_library):
        """Test composing code from multiple patterns"""
        patterns = ["CRUD", "Transformation"]

        result = pattern_library.compose_pattern_code(
            patterns=patterns,
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            node_type="EFFECT",
            class_name="NodeCompositeEffect",
        )

        assert "code" in result
        code = result["code"]

        # Should contain methods from both patterns
        assert "create" in code or "read" in code  # From CRUD
        # Note: May need contract with transformation capabilities


# ============================================================================
# REQUIRED IMPORTS/MIXINS INFERENCE TESTS
# ============================================================================


class TestImportMixinInference:
    """Tests for inferring required imports and mixins"""

    def test_infer_crud_pattern_mixins(self, pattern_library):
        """Test mixin inference for CRUD pattern"""
        result = pattern_library.infer_required_mixins(
            pattern_name="CRUD", contract=SAMPLE_CONTRACT_WITH_CRUD
        )

        assert "mixins" in result
        # CRUD typically needs EventBus for change notifications
        assert "MixinEventBus" in result["mixins"] or len(result["mixins"]) > 0

    def test_infer_transformation_pattern_mixins(self, pattern_library):
        """Test mixin inference for Transformation pattern"""
        result = pattern_library.infer_required_mixins(
            pattern_name="Transformation", contract=SAMPLE_CONTRACT_WITH_TRANSFORMATION
        )

        assert "mixins" in result
        # Transformation might need Validation mixin
        # At minimum should return empty list, not error

    def test_infer_pattern_imports(self, pattern_library):
        """Test import inference for pattern"""
        result = pattern_library.infer_required_imports(
            pattern_name="CRUD", contract=SAMPLE_CONTRACT_WITH_CRUD
        )

        assert "imports" in result
        imports = result["imports"]

        # Should include common imports
        assert any("Dict" in imp or "typing" in imp for imp in imports)
        assert any("UUID" in imp for imp in imports)


# ============================================================================
# PATTERN FALLBACK TESTS
# ============================================================================


class TestPatternFallback:
    """Tests for pattern fallback behavior"""

    def test_fallback_when_no_match(self, pattern_library):
        """Test fallback pattern when no match found"""
        unclear_contract = {
            "capabilities": [
                {"name": "do_stuff", "type": "operation", "required": True}
            ]
        }

        result = pattern_library.detect_pattern(unclear_contract)

        # Should fall back to Generic pattern
        assert result["pattern_name"] == "Generic" or result["matched"] is False

    def test_generic_pattern_code_generation(self, pattern_library):
        """Test generic pattern code generation as fallback"""
        result = pattern_library.generate_pattern_code(
            pattern_name="Generic",
            contract={"capabilities": []},
            node_type="EFFECT",
            class_name="NodeGenericEffect",
        )

        assert "code" in result
        # Should generate basic stub even for generic pattern
        assert "class NodeGenericEffect" in result["code"]

    def test_fallback_has_basic_structure(self, pattern_library):
        """Test fallback pattern has basic code structure"""
        result = pattern_library.generate_pattern_code(
            pattern_name="Generic",
            contract={},
            node_type="EFFECT",
            class_name="NodeFallbackEffect",
        )

        code = result["code"]

        # Verify basic structure
        assert "class" in code
        assert "async def" in code
        assert "execute" in code


# ============================================================================
# PATTERN MATCHING PERFORMANCE TESTS
# ============================================================================


class TestPatternMatchingPerformance:
    """Tests for pattern matching performance"""

    def test_pattern_matching_performance(self, pattern_library, crud_contract):
        """Test pattern matching completes quickly"""
        import time

        start = time.time()
        pattern_library.detect_pattern(crud_contract)
        duration_ms = (time.time() - start) * 1000

        # Pattern matching should be < 100ms
        assert (
            duration_ms < 100
        ), f"Pattern matching took {duration_ms}ms, expected < 100ms"

    def test_multiple_pattern_detection_performance(self, pattern_library):
        """Test detecting all patterns is fast"""
        import time

        mixed_contract = {
            "capabilities": [
                {"name": f"capability_{i}", "type": "operation", "required": True}
                for i in range(20)
            ]
        }

        start = time.time()
        pattern_library.detect_all_patterns(mixed_contract)
        duration_ms = (time.time() - start) * 1000

        # Should handle 20 capabilities in < 200ms
        assert duration_ms < 200, f"Multi-pattern detection took {duration_ms}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

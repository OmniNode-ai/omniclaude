#!/usr/bin/env python3
"""
Comprehensive validation tests for Aggregation Pattern implementations.

Tests the AggregationPattern class including:
- Pattern matching with aggregation keywords
- Code generation for reduce, group_by, windowed, stateful aggregations
- Error handling and edge cases
- Required imports and mixins
- Method name sanitization
- Aggregation type detection
"""

import pytest

from agents.lib.patterns.aggregation_pattern import AggregationPattern

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def aggregation_pattern():
    """Create an AggregationPattern instance"""
    return AggregationPattern()


@pytest.fixture
def reduce_capability():
    """Sample reduce capability"""
    return {
        "name": "sum_values",
        "description": "Sum all values in collection",
        "type": "aggregation",
        "required": True,
    }


@pytest.fixture
def group_by_capability():
    """Sample group by capability"""
    return {
        "name": "group_by_category",
        "description": "Group items by category field",
        "type": "aggregation",
        "required": True,
    }


@pytest.fixture
def windowed_capability():
    """Sample windowed aggregation capability"""
    return {
        "name": "windowed_aggregate",
        "description": "Aggregate data within sliding windows",
        "type": "aggregation",
        "required": True,
    }


@pytest.fixture
def stateful_capability():
    """Sample stateful aggregation capability"""
    return {
        "name": "stateful_accumulate",
        "description": "Incremental aggregation with state persistence",
        "type": "aggregation",
        "required": True,
    }


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================


class TestAggregationPatternMatching:
    """Tests for aggregation pattern matching logic"""

    def test_matches_aggregate_keyword(self, aggregation_pattern):
        """Test matching with 'aggregate' keyword"""
        capability = {"name": "aggregate_data", "description": "Aggregate values"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'aggregate' keyword"

    def test_matches_reduce_keyword(self, aggregation_pattern):
        """Test matching with 'reduce' keyword"""
        capability = {"name": "reduce_values", "description": "Reduce to single value"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'reduce' keyword"

    def test_matches_sum_keyword(self, aggregation_pattern):
        """Test matching with 'sum' keyword"""
        capability = {"name": "sum_totals", "description": "Sum all totals"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'sum' keyword"

    def test_matches_count_keyword(self, aggregation_pattern):
        """Test matching with 'count' keyword"""
        capability = {"name": "count_items", "description": "Count number of items"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'count' keyword"

    def test_matches_group_keyword(self, aggregation_pattern):
        """Test matching with 'group' keyword"""
        capability = {
            "name": "group_by_type",
            "description": "Group items by type",
        }
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'group' keyword"

    def test_matches_multiple_keywords(self, aggregation_pattern):
        """Test high confidence with multiple aggregation keywords"""
        capability = {
            "name": "aggregate_and_reduce",
            "description": "Aggregate data, count items, and sum totals",
        }
        confidence = aggregation_pattern.matches(capability)
        assert confidence >= 1.0, "Multiple keywords should give max confidence"

    def test_matches_case_insensitive(self, aggregation_pattern):
        """Test matching is case-insensitive"""
        capability = {"name": "AGGREGATE_DATA", "description": "SUM VALUES"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Matching should be case-insensitive"

    def test_no_match_non_aggregation(self, aggregation_pattern):
        """Test no match for non-aggregation capability"""
        capability = {"name": "create_user", "description": "Create new user"}
        confidence = aggregation_pattern.matches(capability)
        assert confidence == 0.0, "Should not match non-aggregation operations"

    def test_matches_average_keyword(self, aggregation_pattern):
        """Test matching with 'average' keyword"""
        capability = {
            "name": "calculate_average",
            "description": "Calculate average value",
        }
        confidence = aggregation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'average' keyword"

    def test_confidence_score_range(self, aggregation_pattern, reduce_capability):
        """Test confidence scores are within valid range"""
        confidence = aggregation_pattern.matches(reduce_capability)
        assert 0.0 <= confidence <= 1.0, "Confidence must be between 0.0 and 1.0"

    def test_empty_capability(self, aggregation_pattern):
        """Test handling of empty capability"""
        capability = {}
        confidence = aggregation_pattern.matches(capability)
        assert confidence == 0.0, "Empty capability should have zero confidence"


# ============================================================================
# CODE GENERATION TESTS - REDUCE
# ============================================================================


class TestReduceAggregationGeneration:
    """Tests for reduce aggregation code generation"""

    def test_generate_reduce_method(self, aggregation_pattern, reduce_capability):
        """Test generating reduce method code"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        assert "async def sum_values" in code
        assert "items: List[Any]" in code
        assert "operation: str" in code
        assert "initial_value" in code

    def test_reduce_includes_all_operations(
        self, aggregation_pattern, reduce_capability
    ):
        """Test reduce method includes all standard operations"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        operations = ["sum", "count", "average", "min", "max", "first", "last"]
        for operation in operations:
            assert f'operation == "{operation}"' in code

    def test_reduce_includes_custom_operation(
        self, aggregation_pattern, reduce_capability
    ):
        """Test reduce method includes custom operation support"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        assert "_apply_custom_reduction" in code

    def test_reduce_handles_empty_list(self, aggregation_pattern, reduce_capability):
        """Test reduce method handles empty input list"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        assert "if not items:" in code
        assert "initial_value" in code

    def test_reduce_includes_error_handling(
        self, aggregation_pattern, reduce_capability
    ):
        """Test reduce method includes error handling"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        assert "try:" in code
        assert "except Exception" in code
        assert "OPERATION_FAILED" in code

    def test_reduce_includes_logging(self, aggregation_pattern, reduce_capability):
        """Test reduce method includes logging"""
        context = {}
        code = aggregation_pattern.generate(reduce_capability, context)

        assert "self.logger.info" in code
        assert "self.logger.error" in code


# ============================================================================
# CODE GENERATION TESTS - GROUP BY
# ============================================================================


class TestGroupByAggregationGeneration:
    """Tests for group by aggregation code generation"""

    def test_generate_group_by_method(self, aggregation_pattern, group_by_capability):
        """Test generating group by method code"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert "async def group_by_category" in code
        assert "group_by_field: str" in code
        assert "aggregate_fields" in code

    def test_group_by_uses_defaultdict(self, aggregation_pattern, group_by_capability):
        """Test group by uses defaultdict for grouping"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert "defaultdict" in code or "groups = " in code

    def test_group_by_handles_missing_fields(
        self, aggregation_pattern, group_by_capability
    ):
        """Test group by handles missing group field"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert "if group_by_field not in item" in code
        assert "self.logger.warning" in code

    def test_group_by_includes_aggregation(
        self, aggregation_pattern, group_by_capability
    ):
        """Test group by includes aggregation within groups"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert "_aggregate_values" in code
        assert "aggregate_fields" in code

    def test_group_by_includes_count(self, aggregation_pattern, group_by_capability):
        """Test group by includes item count per group"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert '"count": len(group_items)' in code

    def test_group_by_helper_methods(self, aggregation_pattern, group_by_capability):
        """Test group by includes helper methods"""
        context = {}
        code = aggregation_pattern.generate(group_by_capability, context)

        assert "_aggregate_values" in code


# ============================================================================
# CODE GENERATION TESTS - WINDOWED AGGREGATION
# ============================================================================


class TestWindowedAggregationGeneration:
    """Tests for windowed aggregation code generation"""

    def test_generate_windowed_method(self, aggregation_pattern, windowed_capability):
        """Test generating windowed aggregation method code"""
        context = {}
        code = aggregation_pattern.generate(windowed_capability, context)

        assert "async def windowed_aggregate" in code
        assert "window_size: int" in code
        assert "time_field" in code
        assert "time_window_seconds" in code

    def test_windowed_includes_count_based(
        self, aggregation_pattern, windowed_capability
    ):
        """Test windowed aggregation includes count-based windowing"""
        context = {}
        code = aggregation_pattern.generate(windowed_capability, context)

        assert "for i in range(0, len(items), window_size)" in code
        assert "window = items[i:i + window_size]" in code

    def test_windowed_includes_time_based(
        self, aggregation_pattern, windowed_capability
    ):
        """Test windowed aggregation includes time-based windowing"""
        context = {}
        code = aggregation_pattern.generate(windowed_capability, context)

        assert "if time_field and time_window_seconds:" in code
        assert "_aggregate_by_time_windows" in code

    def test_windowed_includes_window_metadata(
        self, aggregation_pattern, windowed_capability
    ):
        """Test windowed results include window metadata"""
        context = {}
        code = aggregation_pattern.generate(windowed_capability, context)

        assert "window_index" in code
        assert "window_start" in code
        assert "window_end" in code
        assert "item_count" in code

    def test_windowed_helper_methods(self, aggregation_pattern, windowed_capability):
        """Test windowed aggregation includes helper methods"""
        context = {}
        code = aggregation_pattern.generate(windowed_capability, context)

        assert "_aggregate_window" in code
        assert "_aggregate_by_time_windows" in code


# ============================================================================
# CODE GENERATION TESTS - STATEFUL AGGREGATION
# ============================================================================


class TestStatefulAggregationGeneration:
    """Tests for stateful aggregation code generation"""

    def test_generate_stateful_method(self, aggregation_pattern, stateful_capability):
        """Test generating stateful aggregation method code"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert "async def stateful_accumulate" in code
        assert "new_items: List[Any]" in code
        assert "state_key: str" in code

    def test_stateful_loads_state(self, aggregation_pattern, stateful_capability):
        """Test stateful aggregation loads existing state"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert "_load_aggregation_state" in code

    def test_stateful_saves_state(self, aggregation_pattern, stateful_capability):
        """Test stateful aggregation saves updated state"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert "_save_aggregation_state" in code

    def test_stateful_updates_count(self, aggregation_pattern, stateful_capability):
        """Test stateful aggregation updates total count"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert 'state["total_count"] += len(new_items)' in code

    def test_stateful_computes_aggregates(
        self, aggregation_pattern, stateful_capability
    ):
        """Test stateful aggregation computes aggregate metrics"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert "_compute_aggregates" in code

    def test_stateful_includes_timestamp(
        self, aggregation_pattern, stateful_capability
    ):
        """Test stateful aggregation includes timestamp"""
        context = {}
        code = aggregation_pattern.generate(stateful_capability, context)

        assert "datetime.now()" in code
        assert "isoformat()" in code


# ============================================================================
# REQUIRED IMPORTS AND MIXINS TESTS
# ============================================================================


class TestAggregationRequirements:
    """Tests for required imports and mixins"""

    def test_get_required_imports(self, aggregation_pattern):
        """Test getting required imports for aggregation pattern"""
        imports = aggregation_pattern.get_required_imports()

        assert len(imports) > 0
        assert any("Dict" in imp for imp in imports)
        assert any("List" in imp for imp in imports)
        assert any("defaultdict" in imp for imp in imports)
        assert any("datetime" in imp for imp in imports)
        assert any("OnexError" in imp for imp in imports)

    def test_get_required_mixins(self, aggregation_pattern):
        """Test getting required mixins for aggregation pattern"""
        mixins = aggregation_pattern.get_required_mixins()

        assert len(mixins) > 0
        assert "MixinStateManagement" in mixins
        assert "MixinCaching" in mixins

    def test_required_imports_are_strings(self, aggregation_pattern):
        """Test imports are returned as strings"""
        imports = aggregation_pattern.get_required_imports()
        assert all(isinstance(imp, str) for imp in imports)

    def test_required_mixins_are_strings(self, aggregation_pattern):
        """Test mixins are returned as strings"""
        mixins = aggregation_pattern.get_required_mixins()
        assert all(isinstance(mixin, str) for mixin in mixins)


# ============================================================================
# UTILITY METHOD TESTS
# ============================================================================


class TestAggregationUtilities:
    """Tests for utility methods"""

    def test_sanitize_method_name(self, aggregation_pattern):
        """Test method name sanitization"""
        test_cases = [
            ("aggregate_data", "aggregate_data"),
            ("Aggregate-Data", "aggregate_data"),
            ("aggregate data", "aggregate_data"),
            ("aggregate@data!", "aggregatedata"),
            ("", "aggregate_data"),
        ]

        for input_name, expected in test_cases:
            result = aggregation_pattern._sanitize_method_name(input_name)
            assert result == expected, f"Failed for input: {input_name}"

    def test_detect_aggregation_type_reduce(self, aggregation_pattern):
        """Test detecting reduce aggregation type"""
        capability = {"name": "sum_values", "description": "Sum all values"}
        context = {}
        result = aggregation_pattern._detect_aggregation_type(capability, context)
        assert result == "reduce"

    def test_detect_aggregation_type_group_by(self, aggregation_pattern):
        """Test detecting group by aggregation type"""
        capability = {"name": "group_by_field", "description": "Group by category"}
        context = {}
        result = aggregation_pattern._detect_aggregation_type(capability, context)
        assert result == "group_by"

    def test_detect_aggregation_type_windowed(self, aggregation_pattern):
        """Test detecting windowed aggregation type"""
        capability = {"name": "window_aggregate", "description": "Window aggregation"}
        context = {}
        result = aggregation_pattern._detect_aggregation_type(capability, context)
        assert result == "windowed"

    def test_detect_aggregation_type_stateful(self, aggregation_pattern):
        """Test detecting stateful aggregation type"""
        capability = {
            "name": "stateful_aggregate",
            "description": "Stateful aggregation",
        }
        context = {}
        result = aggregation_pattern._detect_aggregation_type(capability, context)
        assert result == "stateful"

    def test_detect_aggregation_type_generic(self, aggregation_pattern):
        """Test detecting generic aggregation type"""
        capability = {"name": "process_data", "description": "Process items"}
        context = {}
        result = aggregation_pattern._detect_aggregation_type(capability, context)
        assert result == "generic"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestAggregationEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_generate_with_empty_capability(self, aggregation_pattern):
        """Test generation with empty capability"""
        capability = {}
        context = {}
        code = aggregation_pattern.generate(capability, context)
        assert "async def" in code

    def test_generate_generic_aggregation(self, aggregation_pattern):
        """Test generation of generic aggregation method"""
        capability = {
            "name": "process_items",
            "description": "Process collection of items",
        }
        context = {}
        code = aggregation_pattern.generate(capability, context)

        assert "async def process_items" in code
        assert "items" in code

    def test_capability_with_special_characters(self, aggregation_pattern):
        """Test handling capability with special characters"""
        capability = {
            "name": "aggregate-data@2024!",
            "description": "Aggregate data <test>",
        }
        context = {}
        code = aggregation_pattern.generate(capability, context)
        assert "async def" in code

    def test_very_long_capability_name(self, aggregation_pattern):
        """Test handling very long capability name"""
        capability = {
            "name": "aggregate_data_with_very_long_name_that_exceeds_normal_length",
            "description": "Aggregate data",
        }
        context = {}
        code = aggregation_pattern.generate(capability, context)
        assert "async def" in code

    def test_missing_description(self, aggregation_pattern):
        """Test handling capability without description"""
        capability = {"name": "aggregate_data"}
        context = {}
        code = aggregation_pattern.generate(capability, context)
        assert "async def" in code


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestAggregationIntegration:
    """Integration tests combining multiple features"""

    def test_all_aggregation_types(self, aggregation_pattern):
        """Test generating all aggregation types"""
        capabilities = [
            {"name": "reduce_values", "description": "Reduce to single value"},
            {"name": "group_by_field", "description": "Group items by field"},
            {"name": "window_aggregate", "description": "Window aggregation"},
            {"name": "stateful_aggregate", "description": "Stateful aggregation"},
        ]

        for capability in capabilities:
            code = aggregation_pattern.generate(capability, {})
            assert "async def" in code
            assert "OnexError" in code

    def test_code_generation_consistency(self, aggregation_pattern):
        """Test code generation is consistent across multiple calls"""
        capability = {"name": "sum_values", "description": "Sum all values"}
        context = {}

        code1 = aggregation_pattern.generate(capability, context)
        code2 = aggregation_pattern.generate(capability, context)

        assert code1 == code2, "Code generation should be deterministic"

    def test_all_types_include_error_handling(self, aggregation_pattern):
        """Test all aggregation types include proper error handling"""
        capability_names = [
            "reduce_values",
            "group_by_field",
            "window_aggregate",
            "stateful_aggregate",
        ]

        for name in capability_names:
            capability = {"name": name, "description": f"{name} operation"}
            code = aggregation_pattern.generate(capability, {})

            assert "try:" in code
            assert "except" in code
            assert "OnexError" in code

    def test_reduce_operations_comprehensive(self, aggregation_pattern):
        """Test reduce method supports comprehensive set of operations"""
        capability = {"name": "reduce_items", "description": "Reduce items"}
        context = {}
        code = aggregation_pattern.generate(capability, context)

        # Check for standard operations
        operations = ["sum", "count", "average", "min", "max"]
        for op in operations:
            assert op in code

    def test_group_by_with_multiple_aggregations(self, aggregation_pattern):
        """Test group by supports multiple aggregation fields"""
        capability = {
            "name": "group_aggregate",
            "description": "Group and aggregate multiple fields",
        }
        context = {}
        code = aggregation_pattern.generate(capability, context)

        assert "aggregate_fields" in code
        assert "for field, operation in" in code


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

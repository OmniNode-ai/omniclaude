#!/usr/bin/env python3
"""
Comprehensive validation tests for Transformation Pattern implementations.

Tests the TransformationPattern class including:
- Pattern matching with transformation keywords
- Code generation for format conversion, data mapping, validation, streaming
- Error handling and edge cases
- Required imports and mixins
- Method name sanitization
- Transformation type detection
"""

import pytest

from agents.lib.patterns.transformation_pattern import TransformationPattern

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def transformation_pattern():
    """Create a TransformationPattern instance"""
    return TransformationPattern()


@pytest.fixture
def format_conversion_capability():
    """Sample format conversion capability"""
    return {
        "name": "transform_csv_to_json",
        "description": "Convert CSV data to JSON format",
        "type": "transformation",
        "required": True,
    }


@pytest.fixture
def data_mapping_capability():
    """Sample data mapping capability"""
    return {
        "name": "map_user_fields",
        "description": "Map input fields to output schema",
        "type": "transformation",
        "required": True,
    }


@pytest.fixture
def validation_capability():
    """Sample validation capability"""
    return {
        "name": "validate_input_data",
        "description": "Validate input data according to rules",
        "type": "transformation",
        "required": True,
    }


@pytest.fixture
def streaming_capability():
    """Sample streaming transformation capability"""
    return {
        "name": "stream_transform_data",
        "description": "Transform large dataset in streaming fashion",
        "type": "transformation",
        "required": True,
    }


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================


class TestTransformationPatternMatching:
    """Tests for transformation pattern matching logic"""

    def test_matches_transform_keyword(self, transformation_pattern):
        """Test matching with 'transform' keyword"""
        capability = {
            "name": "transform_data",
            "description": "Transform input to output",
        }
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'transform' keyword"

    def test_matches_convert_keyword(self, transformation_pattern):
        """Test matching with 'convert' keyword"""
        capability = {"name": "convert_format", "description": "Convert data format"}
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'convert' keyword"

    def test_matches_parse_keyword(self, transformation_pattern):
        """Test matching with 'parse' keyword"""
        capability = {"name": "parse_json", "description": "Parse JSON data"}
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'parse' keyword"

    def test_matches_format_keyword(self, transformation_pattern):
        """Test matching with 'format' keyword"""
        capability = {"name": "format_output", "description": "Format output data"}
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'format' keyword"

    def test_matches_multiple_keywords(self, transformation_pattern):
        """Test high confidence with multiple transformation keywords"""
        capability = {
            "name": "transform_and_validate",
            "description": "Transform, parse, and format input data",
        }
        confidence = transformation_pattern.matches(capability)
        assert confidence >= 1.0, "Multiple keywords should give max confidence"

    def test_matches_case_insensitive(self, transformation_pattern):
        """Test matching is case-insensitive"""
        capability = {"name": "TRANSFORM_DATA", "description": "CONVERT FORMAT"}
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Matching should be case-insensitive"

    def test_no_match_non_transformation(self, transformation_pattern):
        """Test no match for non-transformation capability"""
        capability = {"name": "create_user", "description": "Create new user"}
        confidence = transformation_pattern.matches(capability)
        assert confidence == 0.0, "Should not match non-transformation operations"

    def test_matches_normalize_keyword(self, transformation_pattern):
        """Test matching with 'normalize' keyword"""
        capability = {
            "name": "normalize_data",
            "description": "Normalize input data",
        }
        confidence = transformation_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'normalize' keyword"

    def test_confidence_score_range(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test confidence scores are within valid range"""
        confidence = transformation_pattern.matches(format_conversion_capability)
        assert 0.0 <= confidence <= 1.0, "Confidence must be between 0.0 and 1.0"

    def test_empty_capability(self, transformation_pattern):
        """Test handling of empty capability"""
        capability = {}
        confidence = transformation_pattern.matches(capability)
        assert confidence == 0.0, "Empty capability should have zero confidence"


# ============================================================================
# CODE GENERATION TESTS - FORMAT CONVERSION
# ============================================================================


class TestFormatConversionGeneration:
    """Tests for format conversion code generation"""

    def test_generate_format_conversion_method(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test generating format conversion method code"""
        context = {}
        code = transformation_pattern.generate(format_conversion_capability, context)

        assert "async def transform_csv_to_json" in code
        assert "source_format" in code
        assert "target_format" in code
        assert "_parse_source_format" in code
        assert "_convert_to_target_format" in code

    def test_format_conversion_includes_validation(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test format conversion includes input validation"""
        context = {}
        code = transformation_pattern.generate(format_conversion_capability, context)

        assert "input_data is None" in code
        assert "VALIDATION_ERROR" in code

    def test_format_conversion_error_handling(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test format conversion includes error handling"""
        context = {}
        code = transformation_pattern.generate(format_conversion_capability, context)

        assert "try:" in code
        assert "except OnexError:" in code
        assert "except Exception" in code
        assert "OPERATION_FAILED" in code

    def test_format_conversion_includes_logging(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test format conversion includes logging"""
        context = {}
        code = transformation_pattern.generate(format_conversion_capability, context)

        assert "self.logger.info" in code
        assert "self.logger.error" in code

    def test_format_conversion_helper_methods(
        self, transformation_pattern, format_conversion_capability
    ):
        """Test format conversion includes helper methods"""
        context = {}
        code = transformation_pattern.generate(format_conversion_capability, context)

        assert "_parse_source_format" in code
        assert "_convert_to_target_format" in code
        assert "json.loads" in code or "json.dumps" in code


# ============================================================================
# CODE GENERATION TESTS - DATA MAPPING
# ============================================================================


class TestDataMappingGeneration:
    """Tests for data mapping code generation"""

    def test_generate_data_mapping_method(
        self, transformation_pattern, data_mapping_capability
    ):
        """Test generating data mapping method code"""
        context = {}
        code = transformation_pattern.generate(data_mapping_capability, context)

        assert "async def map_user_fields" in code
        assert "mapping_rules" in code
        assert "input_data: Dict[str, Any]" in code

    def test_data_mapping_includes_default_rules(
        self, transformation_pattern, data_mapping_capability
    ):
        """Test data mapping includes default mapping rules"""
        context = {}
        code = transformation_pattern.generate(data_mapping_capability, context)

        assert "_get_default_mapping_rules" in code

    def test_data_mapping_value_transformation(
        self, transformation_pattern, data_mapping_capability
    ):
        """Test data mapping includes value transformation"""
        context = {}
        code = transformation_pattern.generate(data_mapping_capability, context)

        assert "_transform_value" in code

    def test_data_mapping_handles_missing_fields(
        self, transformation_pattern, data_mapping_capability
    ):
        """Test data mapping handles missing source fields"""
        context = {}
        code = transformation_pattern.generate(data_mapping_capability, context)

        assert "if source_field in input_data" in code
        assert "self.logger.warning" in code


# ============================================================================
# CODE GENERATION TESTS - VALIDATION TRANSFORM
# ============================================================================


class TestValidationTransformGeneration:
    """Tests for validation transformation code generation"""

    def test_generate_validation_transform_method(
        self, transformation_pattern, validation_capability
    ):
        """Test generating validation transform method code"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert "async def validate_input_data" in code
        assert "validation_rules" in code
        assert "validation_errors" in code

    def test_validation_checks_required_fields(
        self, transformation_pattern, validation_capability
    ):
        """Test validation checks required fields"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert 'rules.get("required"' in code
        assert "Required field missing" in code

    def test_validation_includes_type_conversion(
        self, transformation_pattern, validation_capability
    ):
        """Test validation includes type conversion"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert "_convert_type" in code
        assert 'rules.get("type")' in code

    def test_validation_includes_range_checks(
        self, transformation_pattern, validation_capability
    ):
        """Test validation includes range checks"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert '"min" in rules' in code
        assert '"max" in rules' in code

    def test_validation_raises_error_on_failure(
        self, transformation_pattern, validation_capability
    ):
        """Test validation raises error when validation fails"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert "if validation_errors:" in code
        assert "VALIDATION_ERROR" in code

    def test_validation_helper_methods(
        self, transformation_pattern, validation_capability
    ):
        """Test validation includes helper methods"""
        context = {}
        code = transformation_pattern.generate(validation_capability, context)

        assert "_get_default_validation_rules" in code
        assert "_convert_type" in code


# ============================================================================
# CODE GENERATION TESTS - STREAMING
# ============================================================================


class TestStreamingTransformGeneration:
    """Tests for streaming transformation code generation"""

    def test_generate_streaming_transform_method(
        self, transformation_pattern, streaming_capability
    ):
        """Test generating streaming transform method code"""
        context = {}
        code = transformation_pattern.generate(streaming_capability, context)

        assert "async def stream_transform_data" in code
        assert "AsyncIterator" in code
        assert "batch_size" in code

    def test_streaming_includes_batch_processing(
        self, transformation_pattern, streaming_capability
    ):
        """Test streaming includes batch processing"""
        context = {}
        code = transformation_pattern.generate(streaming_capability, context)

        assert "async for item in input_stream" in code
        assert "batch = []" in code
        assert "yield" in code

    def test_streaming_includes_item_transformation(
        self, transformation_pattern, streaming_capability
    ):
        """Test streaming includes item transformation"""
        context = {}
        code = transformation_pattern.generate(streaming_capability, context)

        assert "_transform_item" in code

    def test_streaming_error_handling_per_item(
        self, transformation_pattern, streaming_capability
    ):
        """Test streaming handles errors per item without stopping"""
        context = {}
        code = transformation_pattern.generate(streaming_capability, context)

        assert "try:" in code
        assert "self.logger.warning" in code
        assert "# Continue with next item" in code

    def test_streaming_yields_remaining_batch(
        self, transformation_pattern, streaming_capability
    ):
        """Test streaming yields remaining items after loop"""
        context = {}
        code = transformation_pattern.generate(streaming_capability, context)

        assert "# Yield remaining items" in code or "if batch:" in code


# ============================================================================
# REQUIRED IMPORTS AND MIXINS TESTS
# ============================================================================


class TestTransformationRequirements:
    """Tests for required imports and mixins"""

    def test_get_required_imports(self, transformation_pattern):
        """Test getting required imports for transformation pattern"""
        imports = transformation_pattern.get_required_imports()

        assert len(imports) > 0
        assert any("Dict" in imp for imp in imports)
        assert any("AsyncIterator" in imp for imp in imports)
        assert any("json" in imp for imp in imports)
        assert any("OnexError" in imp for imp in imports)

    def test_get_required_mixins(self, transformation_pattern):
        """Test getting required mixins for transformation pattern"""
        mixins = transformation_pattern.get_required_mixins()

        assert len(mixins) > 0
        assert "MixinValidation" in mixins

    def test_required_imports_are_strings(self, transformation_pattern):
        """Test imports are returned as strings"""
        imports = transformation_pattern.get_required_imports()
        assert all(isinstance(imp, str) for imp in imports)

    def test_required_mixins_are_strings(self, transformation_pattern):
        """Test mixins are returned as strings"""
        mixins = transformation_pattern.get_required_mixins()
        assert all(isinstance(mixin, str) for mixin in mixins)


# ============================================================================
# UTILITY METHOD TESTS
# ============================================================================


class TestTransformationUtilities:
    """Tests for utility methods"""

    def test_sanitize_method_name(self, transformation_pattern):
        """Test method name sanitization"""
        test_cases = [
            ("transform_data", "transform_data"),
            ("Transform-Data", "transform_data"),
            ("transform data", "transform_data"),
            ("transform@data!", "transformdata"),
            ("", "transform_data"),
        ]

        for input_name, expected in test_cases:
            result = transformation_pattern._sanitize_method_name(input_name)
            assert result == expected, f"Failed for input: {input_name}"

    def test_detect_transformation_type_format_conversion(self, transformation_pattern):
        """Test detecting format conversion transformation type"""
        capability = {"name": "convert_csv", "description": "Convert CSV format"}
        context = {}
        result = transformation_pattern._detect_transformation_type(capability, context)
        assert result == "format_conversion"

    def test_detect_transformation_type_data_mapping(self, transformation_pattern):
        """Test detecting data mapping transformation type"""
        capability = {"name": "map_fields", "description": "Map data fields"}
        context = {}
        result = transformation_pattern._detect_transformation_type(capability, context)
        assert result == "data_mapping"

    def test_detect_transformation_type_validation(self, transformation_pattern):
        """Test detecting validation transformation type"""
        capability = {"name": "validate_input", "description": "Validate data"}
        context = {}
        result = transformation_pattern._detect_transformation_type(capability, context)
        assert result == "validation"

    def test_detect_transformation_type_streaming(self, transformation_pattern):
        """Test detecting streaming transformation type"""
        capability = {
            "name": "stream_data",
            "description": "Stream large dataset",
        }
        context = {}
        result = transformation_pattern._detect_transformation_type(capability, context)
        assert result == "streaming"

    def test_detect_transformation_type_generic(self, transformation_pattern):
        """Test detecting generic transformation type"""
        capability = {"name": "process_data", "description": "Process data"}
        context = {}
        result = transformation_pattern._detect_transformation_type(capability, context)
        assert result == "generic"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestTransformationEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_generate_with_empty_capability(self, transformation_pattern):
        """Test generation with empty capability"""
        capability = {}
        context = {}
        code = transformation_pattern.generate(capability, context)
        assert "async def" in code

    def test_generate_generic_transform(self, transformation_pattern):
        """Test generation of generic transformation method"""
        capability = {
            "name": "process_data",
            "description": "Process some data",
        }
        context = {}
        code = transformation_pattern.generate(capability, context)

        assert "async def process_data" in code
        assert "input_data" in code

    def test_capability_with_special_characters(self, transformation_pattern):
        """Test handling capability with special characters"""
        capability = {
            "name": "transform-data@2024!",
            "description": "Transform data <test>",
        }
        context = {}
        code = transformation_pattern.generate(capability, context)
        assert "async def" in code

    def test_very_long_capability_name(self, transformation_pattern):
        """Test handling very long capability name"""
        capability = {
            "name": "transform_data_with_very_long_name_that_exceeds_normal_length",
            "description": "Transform data",
        }
        context = {}
        code = transformation_pattern.generate(capability, context)
        assert "async def" in code

    def test_missing_description(self, transformation_pattern):
        """Test handling capability without description"""
        capability = {"name": "transform_data"}
        context = {}
        code = transformation_pattern.generate(capability, context)
        assert "async def" in code


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestTransformationIntegration:
    """Integration tests combining multiple features"""

    def test_all_transformation_types(self, transformation_pattern):
        """Test generating all transformation types"""
        capabilities = [
            {
                "name": "convert_format",
                "description": "Convert data format",
            },
            {
                "name": "map_fields",
                "description": "Map data fields",
            },
            {
                "name": "validate_data",
                "description": "Validate input data",
            },
            {
                "name": "stream_transform",
                "description": "Stream large dataset",
            },
        ]

        for capability in capabilities:
            code = transformation_pattern.generate(capability, {})
            assert "async def" in code
            assert "OnexError" in code

    def test_code_generation_consistency(self, transformation_pattern):
        """Test code generation is consistent across multiple calls"""
        capability = {
            "name": "transform_data",
            "description": "Transform input data",
        }
        context = {}

        code1 = transformation_pattern.generate(capability, context)
        code2 = transformation_pattern.generate(capability, context)

        assert code1 == code2, "Code generation should be deterministic"

    def test_all_types_include_error_handling(self, transformation_pattern):
        """Test all transformation types include proper error handling"""
        capability_names = [
            "convert_format",
            "map_fields",
            "validate_input",
            "stream_data",
        ]

        for name in capability_names:
            capability = {"name": name, "description": f"{name} operation"}
            code = transformation_pattern.generate(capability, {})

            assert "try:" in code
            assert "except" in code
            assert "OnexError" in code

    def test_transformation_with_context_options(self, transformation_pattern):
        """Test transformation respects context options"""
        capability = {"name": "map_fields", "description": "Map fields"}
        context = {"copy_unmapped": True}

        code = transformation_pattern.generate(capability, context)
        assert 'context.get("copy_unmapped"' in code


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

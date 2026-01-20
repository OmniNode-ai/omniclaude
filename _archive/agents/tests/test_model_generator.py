#!/usr/bin/env python3
"""
Tests for Model Generator (Phase 4)

Comprehensive tests for Pydantic model generation from PRD analysis.
"""

from datetime import datetime
from uuid import UUID, uuid4

import pytest

# Import the classes we need
from agents.lib.model_generator import ModelGenerator
from agents.lib.prd_analyzer import (
    DecompositionResult,
    ParsedPRD,
    PRDAnalysisResult,
    PRDAnalyzer,
)


@pytest.fixture
def model_generator():
    """Create a ModelGenerator instance"""
    return ModelGenerator()


@pytest.fixture
def sample_prd_content():
    """Sample PRD content for testing"""
    return """
# User Authentication Service

## Overview
A secure authentication service for user login and registration.

## Functional Requirements
- User registration with email and password
- User login with credentials
- Password reset functionality
- Session management
- Token-based authentication

## Features
- JWT token generation
- Password hashing with bcrypt
- Email verification
- Multi-factor authentication support
- Rate limiting for login attempts

## Success Criteria
- Successfully authenticate users within 200ms
- Support 1000 concurrent login requests
- Provide secure token storage
- Implement password complexity rules

## Technical Details
- Use PostgreSQL for user storage
- Use Redis for session caching
- Implement retry logic for failed operations
- Set timeout to 30 seconds
- Enable metrics collection
- Cache authentication tokens for 1 hour

## Dependencies
- PostgreSQL database
- Redis cache
- Email service API
"""


@pytest.fixture
async def prd_analysis(sample_prd_content):
    """Create PRD analysis from sample content"""
    analyzer = PRDAnalyzer()
    return await analyzer.analyze_prd(sample_prd_content)


class TestModelFieldInference:
    """Test field type inference"""

    def test_infer_uuid_fields(self, model_generator):
        """Test UUID field type inference"""
        # Test various ID patterns
        assert model_generator._infer_field_type("user_id") == "UUID"
        assert model_generator._infer_field_type("session_id") == "UUID"
        assert model_generator._infer_field_type("correlation_id") == "UUID"
        assert model_generator._infer_field_type("id") == "UUID"

    def test_infer_timestamp_fields(self, model_generator):
        """Test timestamp field type inference"""
        assert model_generator._infer_field_type("created_at") == "datetime"
        assert model_generator._infer_field_type("updated_at") == "datetime"
        assert model_generator._infer_field_type("timestamp") == "datetime"

    def test_infer_boolean_fields(self, model_generator):
        """Test boolean field type inference"""
        assert model_generator._infer_field_type("is_active") == "bool"
        assert model_generator._infer_field_type("has_permission") == "bool"
        assert model_generator._infer_field_type("can_edit") == "bool"
        assert model_generator._infer_field_type("cache_enabled") == "bool"
        assert model_generator._infer_field_type("success") == "bool"

    def test_infer_numeric_fields(self, model_generator):
        """Test numeric field type inference"""
        # Integers
        assert model_generator._infer_field_type("retry_count") == "int"
        assert model_generator._infer_field_type("timeout_seconds") == "int"
        assert model_generator._infer_field_type("port") == "int"

        # Floats
        assert model_generator._infer_field_type("confidence_score") == "float"
        assert model_generator._infer_field_type("success_rate") == "float"

    def test_infer_collection_fields(self, model_generator):
        """Test collection field type inference"""
        assert model_generator._infer_field_type("tags") == "List[str]"
        assert model_generator._infer_field_type("error_list") == "List[str]"
        assert model_generator._infer_field_type("metadata") == "Dict[str, str]"
        assert model_generator._infer_field_type("result_data") == "Dict[str, Any]"

    def test_infer_string_fields(self, model_generator):
        """Test string field type inference (default)"""
        assert model_generator._infer_field_type("username") == "str"
        assert model_generator._infer_field_type("error") == "str"
        assert model_generator._infer_field_type("message") == "str"

    def test_extract_field_candidates(self, model_generator):
        """Test field candidate extraction from text"""
        text = "user authentication with user_id and email password"
        candidates = model_generator._extract_field_candidates(text)

        assert "user_id" in candidates
        assert "email" in candidates
        assert "password" in candidates


class TestInputModelGeneration:
    """Test input model generation"""

    @pytest.mark.asyncio
    async def test_generate_basic_input_model(self, model_generator, prd_analysis):
        """Test basic input model generation"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )

        assert model is not None
        assert model.model_name == "ModelUserAuthenticationInput"
        assert model.model_type == "input"
        assert len(model.fields) > 0

        # Check for standard fields
        field_names = [f.name for f in model.fields]
        assert "operation_type" in field_names
        assert "correlation_id" in field_names
        assert "session_id" in field_names
        assert "metadata" in field_names
        assert "created_at" in field_names

    @pytest.mark.asyncio
    async def test_input_model_field_types(self, model_generator, prd_analysis):
        """Test input model has correct field types"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )

        # Find specific fields and check types
        field_map = {f.name: f.type_hint for f in model.fields}

        assert "UUID" in field_map["correlation_id"]
        assert field_map["session_id"] == "Optional[UUID]"
        assert field_map["created_at"] == "datetime"

    @pytest.mark.asyncio
    async def test_input_model_has_imports(self, model_generator, prd_analysis):
        """Test input model includes necessary imports"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )

        import_str = " ".join(model.imports)
        assert "from pydantic import BaseModel" in import_str
        assert "from uuid import UUID" in import_str
        assert "from datetime import datetime" in import_str

    @pytest.mark.asyncio
    async def test_input_model_has_config(self, model_generator, prd_analysis):
        """Test input model includes class config"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )

        assert model.class_config is not None
        assert "json_schema_extra" in model.class_config
        assert "example" in model.class_config["json_schema_extra"]


class TestOutputModelGeneration:
    """Test output model generation"""

    @pytest.mark.asyncio
    async def test_generate_basic_output_model(self, model_generator, prd_analysis):
        """Test basic output model generation"""
        model = await model_generator.generate_output_model(
            "UserAuthentication", prd_analysis
        )

        assert model is not None
        assert model.model_name == "ModelUserAuthenticationOutput"
        assert model.model_type == "output"

        # Check for standard output fields
        field_names = [f.name for f in model.fields]
        assert "success" in field_names
        assert "correlation_id" in field_names
        assert "error" in field_names
        assert "metadata" in field_names
        assert "completed_at" in field_names

    @pytest.mark.asyncio
    async def test_output_model_field_types(self, model_generator, prd_analysis):
        """Test output model has correct field types"""
        model = await model_generator.generate_output_model(
            "UserAuthentication", prd_analysis
        )

        field_map = {f.name: f.type_hint for f in model.fields}

        assert field_map["success"] == "bool"
        assert field_map["correlation_id"] == "UUID"
        assert field_map["error"] == "Optional[str]"
        assert field_map["completed_at"] == "datetime"

    @pytest.mark.asyncio
    async def test_output_model_has_optional_error(self, model_generator, prd_analysis):
        """Test output model error field is optional"""
        model = await model_generator.generate_output_model(
            "UserAuthentication", prd_analysis
        )

        error_field = next(f for f in model.fields if f.name == "error")
        assert "Optional" in error_field.type_hint
        assert error_field.default_value == "None"


class TestConfigModelGeneration:
    """Test configuration model generation"""

    @pytest.mark.asyncio
    async def test_generate_basic_config_model(self, model_generator, prd_analysis):
        """Test basic config model generation"""
        model = await model_generator.generate_config_model(
            "UserAuthentication", prd_analysis
        )

        assert model is not None
        assert model.model_name == "ModelUserAuthenticationConfig"
        assert model.model_type == "config"

        # Check for standard config fields
        field_names = [f.name for f in model.fields]
        assert "timeout_seconds" in field_names
        assert "retry_attempts" in field_names
        assert "cache_enabled" in field_names
        assert "log_level" in field_names

    @pytest.mark.asyncio
    async def test_config_model_has_defaults(self, model_generator, prd_analysis):
        """Test config model fields have default values"""
        model = await model_generator.generate_config_model(
            "UserAuthentication", prd_analysis
        )

        # All config fields should have defaults
        for field in model.fields:
            assert (
                field.default_value is not None
            ), f"Field {field.name} missing default value"

    @pytest.mark.asyncio
    async def test_config_model_field_types(self, model_generator, prd_analysis):
        """Test config model has correct field types"""
        model = await model_generator.generate_config_model(
            "UserAuthentication", prd_analysis
        )

        field_map = {f.name: f.type_hint for f in model.fields}

        assert field_map["timeout_seconds"] == "int"
        assert field_map["retry_attempts"] == "int"
        assert field_map["cache_enabled"] == "bool"
        assert field_map["log_level"] == "str"


class TestModelCodeGeneration:
    """Test model code generation"""

    @pytest.mark.asyncio
    async def test_generate_input_model_code(self, model_generator, prd_analysis):
        """Test input model code generation"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )
        code = model_generator._generate_model_code(model)

        # Verify code structure
        assert "class ModelUserAuthenticationInput(BaseModel):" in code
        assert "from pydantic import BaseModel" in code
        assert "from uuid import UUID" in code
        assert '"""' in code  # Has docstring

        # Verify fields in code
        assert "operation_type:" in code
        assert "correlation_id:" in code
        assert "session_id:" in code

    @pytest.mark.asyncio
    async def test_generate_output_model_code(self, model_generator, prd_analysis):
        """Test output model code generation"""
        model = await model_generator.generate_output_model(
            "UserAuthentication", prd_analysis
        )
        code = model_generator._generate_model_code(model)

        # Verify code structure
        assert "class ModelUserAuthenticationOutput(BaseModel):" in code
        assert "success:" in code
        assert "correlation_id:" in code
        assert "error:" in code

    @pytest.mark.asyncio
    async def test_generate_config_model_code(self, model_generator, prd_analysis):
        """Test config model code generation"""
        model = await model_generator.generate_config_model(
            "UserAuthentication", prd_analysis
        )
        code = model_generator._generate_model_code(model)

        # Verify code structure
        assert "class ModelUserAuthenticationConfig(BaseModel):" in code
        assert "timeout_seconds:" in code
        assert "retry_attempts:" in code
        assert "cache_enabled:" in code

    @pytest.mark.asyncio
    async def test_generated_code_is_valid_python(self, model_generator, prd_analysis):
        """Test that generated code is syntactically valid Python"""
        model = await model_generator.generate_input_model(
            "UserAuthentication", prd_analysis
        )
        code = model_generator._generate_model_code(model)

        # Try to compile the code (will raise SyntaxError if invalid)
        try:
            compile(code, "<string>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")


class TestONEXCompliance:
    """Test ONEX compliance validation"""

    @pytest.mark.asyncio
    async def test_validate_compliant_models(self, model_generator, prd_analysis):
        """Test validation of ONEX-compliant models"""
        input_model = await model_generator.generate_input_model(
            "UserAuth", prd_analysis
        )
        output_model = await model_generator.generate_output_model(
            "UserAuth", prd_analysis
        )
        config_model = await model_generator.generate_config_model(
            "UserAuth", prd_analysis
        )

        input_code = model_generator._generate_model_code(input_model)
        output_code = model_generator._generate_model_code(output_model)
        config_code = model_generator._generate_model_code(config_model)

        (
            quality_score,
            onex_compliant,
            violations,
        ) = await model_generator.validate_model_code(
            input_code, output_code, config_code
        )

        assert quality_score >= 0.7
        assert onex_compliant is True
        assert len(violations) <= 3

    @pytest.mark.asyncio
    async def test_detect_missing_basemodel(self, model_generator):
        """Test detection of missing BaseModel inheritance"""
        bad_code = """
class ModelTestInput:
    pass
"""
        (
            quality_score,
            onex_compliant,
            violations,
        ) = await model_generator.validate_model_code(bad_code, bad_code, bad_code)

        assert quality_score < 1.0
        assert any("BaseModel" in v for v in violations)

    @pytest.mark.asyncio
    async def test_detect_missing_docstrings(self, model_generator):
        """Test detection of missing docstrings"""
        bad_code = """
from pydantic import BaseModel

class ModelTestInput(BaseModel):
    field: str
"""
        (
            quality_score,
            onex_compliant,
            violations,
        ) = await model_generator.validate_model_code(bad_code, bad_code, bad_code)

        assert any("docstring" in v.lower() for v in violations)

    @pytest.mark.asyncio
    async def test_detect_missing_required_fields(self, model_generator):
        """Test detection of missing required fields"""
        input_code = """
from pydantic import BaseModel
\"\"\"Test\"\"\"
class ModelTestInput(BaseModel):
    \"\"\"Test\"\"\"
    field: str
"""
        output_code = """
from pydantic import BaseModel
\"\"\"Test\"\"\"
class ModelTestOutput(BaseModel):
    \"\"\"Test\"\"\"
    field: str
"""
        config_code = """
from pydantic import BaseModel
\"\"\"Test\"\"\"
class ModelTestConfig(BaseModel):
    \"\"\"Test\"\"\"
    field: str
"""

        (
            quality_score,
            onex_compliant,
            violations,
        ) = await model_generator.validate_model_code(
            input_code, output_code, config_code
        )

        # Should detect missing correlation_id and success
        assert any("correlation_id" in v for v in violations)
        assert any("success" in v for v in violations)


class TestParallelGeneration:
    """Test parallel model generation"""

    @pytest.mark.asyncio
    async def test_generate_all_models_concurrently(
        self, model_generator, prd_analysis
    ):
        """Test concurrent generation of all models"""
        import time

        start_time = time.time()
        result = await model_generator.generate_all_models(
            "UserAuthentication", prd_analysis
        )
        end_time = time.time()

        # Verify all models were generated
        assert result.input_model is not None
        assert result.output_model is not None
        assert result.config_model is not None

        # Verify code was generated
        assert len(result.input_model_code) > 0
        assert len(result.output_model_code) > 0
        assert len(result.config_model_code) > 0

        # Verify quality metrics
        assert result.quality_score >= 0.0
        assert isinstance(result.onex_compliant, bool)

        # Parallel execution should be reasonably fast
        # (This is a rough check; actual timing may vary)
        elapsed = end_time - start_time
        print(f"Parallel generation took {elapsed:.3f} seconds")

    @pytest.mark.asyncio
    async def test_generation_result_completeness(self, model_generator, prd_analysis):
        """Test that generation result contains all expected data"""
        result = await model_generator.generate_all_models(
            "UserAuthentication", prd_analysis
        )

        # Check all required fields are present
        assert isinstance(result.session_id, UUID)
        assert isinstance(result.correlation_id, UUID)
        assert result.service_name == "UserAuthentication"
        assert isinstance(result.generated_at, datetime)

        # Check quality metrics
        assert 0.0 <= result.quality_score <= 1.0
        assert isinstance(result.onex_compliant, bool)
        assert isinstance(result.violations, list)


class TestFieldInference:
    """Test field inference from PRD"""

    def test_infer_fields_from_requirements(self, model_generator):
        """Test field inference from requirements"""
        requirements = [
            "User authentication with email and password",
            "Support for user_id and session_id",
            "Return error messages on failure",
        ]

        fields = model_generator.infer_model_fields(requirements, [], "input")

        [f.name for f in fields]

        # Should extract common field names
        assert len(fields) > 0
        # Note: actual fields depend on extraction logic
        # Just verify we get some fields back

    def test_infer_fields_with_context(self, model_generator):
        """Test field inference with additional context"""
        requirements = ["Process user data"]
        context = [
            "Store results in result_data field",
            "Include status flag",
            "Add error message if needed",
        ]

        fields = model_generator.infer_model_fields(requirements, context, "output")

        assert len(fields) > 0


class TestErrorHandling:
    """Test error handling in model generation"""

    @pytest.mark.asyncio
    async def test_handle_empty_prd(self, model_generator):
        """Test handling of empty PRD analysis"""
        # Create minimal PRD analysis
        empty_prd = ParsedPRD(
            title="Empty",
            description="",
            functional_requirements=[],
            features=[],
            success_criteria=[],
            technical_details=[],
            dependencies=[],
            extracted_keywords=[],
            sections=[],
            word_count=0,
        )

        empty_analysis = PRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="",
            parsed_prd=empty_prd,
            decomposition_result=DecompositionResult(
                tasks=[], total_tasks=0, verification_successful=True
            ),
            node_type_hints={},
            recommended_mixins=[],
            external_systems=[],
            quality_baseline=0.5,
            confidence_score=0.0,
        )

        # Should still generate models (with minimal fields)
        result = await model_generator.generate_all_models(
            "EmptyService", empty_analysis
        )

        assert result is not None
        assert result.input_model is not None
        assert result.output_model is not None
        assert result.config_model is not None


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])

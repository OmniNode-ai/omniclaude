#!/usr/bin/env python3
"""
Tests for Quality Validator (Phase 5)

Tests ONEX compliance checks, syntax validation, contract conformance,
quality score calculation, and violation detection.
"""

import pytest

from agents.lib.quality_validator import QualityValidator
from agents.tests.fixtures.phase4_fixtures import (
    INVALID_SYNTAX_CODE,
    MISSING_ERROR_HANDLING_CODE,
    ONEX_VIOLATION_CODE,
    SAMPLE_CONTRACT_WITH_CRUD,
    VALID_EFFECT_NODE_CODE,
)

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def quality_validator():
    """Create a QualityValidator instance"""
    return QualityValidator()


@pytest.fixture
def valid_code_sample():
    """Return valid ONEX-compliant code sample"""
    return VALID_EFFECT_NODE_CODE


@pytest.fixture
def invalid_syntax_sample():
    """Return code with syntax errors"""
    return INVALID_SYNTAX_CODE


@pytest.fixture
def onex_violation_sample():
    """Return code with ONEX violations"""
    return ONEX_VIOLATION_CODE


# ============================================================================
# SYNTAX VALIDATION TESTS
# ============================================================================


class TestSyntaxValidation:
    """Tests for syntax validation"""

    @pytest.mark.asyncio
    async def test_validate_valid_syntax(self, quality_validator, valid_code_sample):
        """Test validation of syntactically correct code"""
        result = await quality_validator.validate_syntax(valid_code_sample)

        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["ast_tree"] is not None

    @pytest.mark.asyncio
    async def test_validate_invalid_syntax(
        self, quality_validator, invalid_syntax_sample
    ):
        """Test validation of code with syntax errors"""
        result = await quality_validator.validate_syntax(invalid_syntax_sample)

        assert result["valid"] is False
        assert len(result["errors"]) > 0
        assert any("syntax" in error.lower() for error in result["errors"])

    @pytest.mark.asyncio
    async def test_syntax_error_line_numbers(
        self, quality_validator, invalid_syntax_sample
    ):
        """Test that syntax errors include line numbers"""
        result = await quality_validator.validate_syntax(invalid_syntax_sample)

        assert result["valid"] is False
        # Check that at least one error mentions a line number
        assert any("line" in error.lower() for error in result["errors"])


# ============================================================================
# ONEX COMPLIANCE TESTS
# ============================================================================


class TestOnexCompliance:
    """Tests for ONEX architectural compliance"""

    @pytest.mark.asyncio
    async def test_validate_onex_naming(self, quality_validator, valid_code_sample):
        """Test ONEX naming convention validation"""
        result = await quality_validator.validate_onex_naming(
            valid_code_sample,
            expected_class_prefix="Node",
            expected_class_suffix="Effect",
        )

        assert result["valid"] is True
        assert len(result["violations"]) == 0

    @pytest.mark.asyncio
    async def test_detect_naming_violations(self, quality_validator):
        """Test detection of naming convention violations"""
        code_with_bad_naming = """
class BadName:  # Should be Node<Name>Effect
    pass
"""
        result = await quality_validator.validate_onex_naming(
            code_with_bad_naming,
            expected_class_prefix="Node",
            expected_class_suffix="Effect",
        )

        assert result["valid"] is False
        assert len(result["violations"]) > 0
        assert any("naming" in v.lower() for v in result["violations"])

    @pytest.mark.asyncio
    async def test_validate_type_safety(self, quality_validator, valid_code_sample):
        """Test type safety validation (no bare Any)"""
        result = await quality_validator.validate_type_safety(valid_code_sample)

        assert result["valid"] is True
        assert result["has_type_annotations"] is True
        assert result["uses_bare_any"] is False

    @pytest.mark.asyncio
    async def test_detect_bare_any_usage(
        self, quality_validator, onex_violation_sample
    ):
        """Test detection of bare Any type usage"""
        result = await quality_validator.validate_type_safety(onex_violation_sample)

        assert result["valid"] is False
        assert result["uses_bare_any"] is True
        assert len(result["violations"]) > 0

    @pytest.mark.asyncio
    async def test_validate_error_handling(self, quality_validator, valid_code_sample):
        """Test error handling pattern validation"""
        result = await quality_validator.validate_error_handling(valid_code_sample)

        assert result["valid"] is True
        assert result["has_try_except"] is True
        assert result["uses_onex_error"] is True
        assert len(result["violations"]) == 0

    @pytest.mark.asyncio
    async def test_detect_missing_error_handling(self, quality_validator):
        """Test detection of missing error handling"""
        result = await quality_validator.validate_error_handling(
            MISSING_ERROR_HANDLING_CODE
        )

        assert result["valid"] is False
        assert len(result["violations"]) > 0


# ============================================================================
# CONTRACT CONFORMANCE TESTS
# ============================================================================


class TestContractConformance:
    """Tests for contract conformance checking"""

    @pytest.mark.asyncio
    async def test_validate_contract_methods_present(self, quality_validator):
        """Test that all contract capabilities have corresponding methods"""
        code = VALID_EFFECT_NODE_CODE
        contract = SAMPLE_CONTRACT_WITH_CRUD

        result = await quality_validator.validate_contract_conformance(
            code=code, contract=contract
        )

        assert result["valid"] is True
        assert result["all_methods_present"] is True
        assert len(result["missing_methods"]) == 0

    @pytest.mark.asyncio
    async def test_detect_missing_contract_methods(self, quality_validator):
        """Test detection of missing contract methods"""
        code = """
class NodeTestEffect:
    async def execute_effect(self, data):
        pass
    # Missing: create_user, get_user, update_user, delete_user
"""
        contract = SAMPLE_CONTRACT_WITH_CRUD

        result = await quality_validator.validate_contract_conformance(
            code=code, contract=contract
        )

        assert result["valid"] is False
        assert len(result["missing_methods"]) > 0
        assert "create_user" in result["missing_methods"]

    @pytest.mark.asyncio
    async def test_validate_method_signatures(self, quality_validator):
        """Test method signature validation against contract"""
        code = VALID_EFFECT_NODE_CODE
        contract = SAMPLE_CONTRACT_WITH_CRUD

        result = await quality_validator.validate_method_signatures(
            code=code, contract=contract
        )

        assert result["valid"] is True
        assert len(result["signature_mismatches"]) == 0

    @pytest.mark.asyncio
    async def test_validate_return_types(self, quality_validator):
        """Test return type validation against contract"""
        code = VALID_EFFECT_NODE_CODE
        contract = SAMPLE_CONTRACT_WITH_CRUD

        result = await quality_validator.validate_return_types(
            code=code, contract=contract
        )

        # Should validate that return types match contract output types
        assert "validation_results" in result


# ============================================================================
# QUALITY SCORE CALCULATION TESTS
# ============================================================================


class TestQualityScoreCalculation:
    """Tests for quality score calculation"""

    @pytest.mark.asyncio
    async def test_calculate_quality_score_valid_code(
        self, quality_validator, valid_code_sample
    ):
        """Test quality score for valid code"""
        result = await quality_validator.calculate_quality_score(
            code=valid_code_sample, contract=SAMPLE_CONTRACT_WITH_CRUD
        )

        assert "quality_score" in result
        assert 0.0 <= result["quality_score"] <= 1.0
        assert result["quality_score"] >= 0.8, "Valid code should score >= 0.8"

    @pytest.mark.asyncio
    async def test_calculate_quality_score_invalid_code(
        self, quality_validator, onex_violation_sample
    ):
        """Test quality score for invalid code"""
        result = await quality_validator.calculate_quality_score(
            code=onex_violation_sample, contract={}
        )

        assert "quality_score" in result
        assert result["quality_score"] < 0.8, "Invalid code should score < 0.8"

    @pytest.mark.asyncio
    async def test_quality_score_components(self, quality_validator, valid_code_sample):
        """Test quality score component breakdown"""
        result = await quality_validator.calculate_quality_score(
            code=valid_code_sample, contract=SAMPLE_CONTRACT_WITH_CRUD
        )

        # Verify score components exist
        assert "components" in result
        components = result["components"]

        assert "syntax_score" in components
        assert "type_safety_score" in components
        assert "error_handling_score" in components
        assert "contract_conformance_score" in components
        assert "naming_compliance_score" in components

        # All components should be 0-1
        for component, score in components.items():
            assert 0.0 <= score <= 1.0, f"{component} out of range: {score}"


# ============================================================================
# THRESHOLD VALIDATION TESTS
# ============================================================================


class TestThresholdValidation:
    """Tests for quality threshold validation"""

    @pytest.mark.asyncio
    async def test_validate_meets_threshold(self, quality_validator, valid_code_sample):
        """Test validation against quality threshold"""
        result = await quality_validator.validate_quality_threshold(
            code=valid_code_sample, contract=SAMPLE_CONTRACT_WITH_CRUD, threshold=0.8
        )

        assert result["meets_threshold"] is True
        assert result["quality_score"] >= 0.8

    @pytest.mark.asyncio
    async def test_validate_fails_threshold(
        self, quality_validator, onex_violation_sample
    ):
        """Test validation failure against threshold"""
        result = await quality_validator.validate_quality_threshold(
            code=onex_violation_sample, contract={}, threshold=0.8
        )

        assert result["meets_threshold"] is False
        assert result["quality_score"] < 0.8

    @pytest.mark.asyncio
    async def test_threshold_validation_with_details(self, quality_validator):
        """Test threshold validation includes failure details"""
        result = await quality_validator.validate_quality_threshold(
            code=ONEX_VIOLATION_CODE, contract={}, threshold=0.8
        )

        assert "failure_reasons" in result
        if not result["meets_threshold"]:
            assert len(result["failure_reasons"]) > 0


# ============================================================================
# VIOLATION DETECTION TESTS
# ============================================================================


class TestViolationDetection:
    """Tests for comprehensive violation detection"""

    @pytest.mark.asyncio
    async def test_detect_all_violations(
        self, quality_validator, onex_violation_sample
    ):
        """Test comprehensive violation detection"""
        result = await quality_validator.detect_all_violations(
            code=onex_violation_sample, contract={}
        )

        assert "violations" in result
        assert len(result["violations"]) > 0

        # Should detect multiple violation types
        violation_types = set(v["type"] for v in result["violations"])
        assert "type_safety" in violation_types

    @pytest.mark.asyncio
    async def test_violation_reporting_format(
        self, quality_validator, onex_violation_sample
    ):
        """Test violation reporting format"""
        result = await quality_validator.detect_all_violations(
            code=onex_violation_sample, contract={}
        )

        for violation in result["violations"]:
            # Verify violation structure
            assert "type" in violation
            assert "severity" in violation
            assert "message" in violation
            assert "line" in violation or "location" in violation

    @pytest.mark.asyncio
    async def test_no_violations_for_valid_code(
        self, quality_validator, valid_code_sample
    ):
        """Test that valid code has no violations"""
        result = await quality_validator.detect_all_violations(
            code=valid_code_sample, contract=SAMPLE_CONTRACT_WITH_CRUD
        )

        assert len(result["violations"]) == 0


# ============================================================================
# IMPORT VALIDATION TESTS
# ============================================================================


class TestImportValidation:
    """Tests for import statement validation"""

    @pytest.mark.asyncio
    async def test_validate_required_imports(
        self, quality_validator, valid_code_sample
    ):
        """Test validation of required imports"""
        result = await quality_validator.validate_imports(
            code=valid_code_sample, required_imports=["OnexError", "NodeEffect"]
        )

        assert result["valid"] is True
        assert len(result["missing_imports"]) == 0

    @pytest.mark.asyncio
    async def test_detect_missing_imports(self, quality_validator):
        """Test detection of missing required imports"""
        code = """
class NodeTestEffect:
    pass
"""
        result = await quality_validator.validate_imports(
            code=code, required_imports=["OnexError", "NodeEffect"]
        )

        assert result["valid"] is False
        assert len(result["missing_imports"]) == 2


# ============================================================================
# COMPREHENSIVE VALIDATION TESTS
# ============================================================================


class TestComprehensiveValidation:
    """Tests for comprehensive validation pipeline"""

    @pytest.mark.asyncio
    async def test_full_validation_valid_code(
        self, quality_validator, valid_code_sample
    ):
        """Test full validation pipeline on valid code"""
        result = await quality_validator.validate_code(
            code=valid_code_sample,
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            quality_threshold=0.8,
        )

        assert result["valid"] is True
        assert result["quality_score"] >= 0.8
        assert len(result["violations"]) == 0
        assert result["meets_threshold"] is True

    @pytest.mark.asyncio
    async def test_full_validation_invalid_code(
        self, quality_validator, onex_violation_sample
    ):
        """Test full validation pipeline on invalid code"""
        result = await quality_validator.validate_code(
            code=onex_violation_sample, contract={}, quality_threshold=0.8
        )

        assert result["valid"] is False
        assert result["quality_score"] < 0.8
        assert len(result["violations"]) > 0
        assert result["meets_threshold"] is False

    @pytest.mark.asyncio
    async def test_validation_performance(self, quality_validator, valid_code_sample):
        """Test validation completes within performance threshold"""
        import time

        start = time.time()
        await quality_validator.validate_code(
            code=valid_code_sample,
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            quality_threshold=0.8,
        )
        duration_ms = (time.time() - start) * 1000

        # Quality validation should be < 1 second
        assert duration_ms < 1000, f"Validation took {duration_ms}ms, expected < 1000ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

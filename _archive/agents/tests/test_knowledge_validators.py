#!/usr/bin/env python3
"""
Unit tests for knowledge validation quality gates (KV-001 to KV-002).

Tests:
- UAKSIntegrationValidator (KV-001)
- PatternRecognitionValidator (KV-002)
- UAKS knowledge structure validation
- Pattern extraction and quality scoring
- Storage integration (mocked)

ONEX v2.0 Compliance:
- Async test patterns
- Mock UAKS storage (no actual persistence)
- Performance validation
- Type safety
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from agents.lib.models.model_quality_gate import EnumQualityGate
from agents.lib.validators.knowledge_validators import (
    PatternRecognitionValidator,
    UAKSIntegrationValidator,
)


class TestUAKSIntegrationValidator:
    """Test suite for KV-001: UAKS Integration Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return UAKSIntegrationValidator()

    @pytest.fixture
    def valid_uaks_knowledge(self):
        """Create valid UAKS knowledge object."""
        return {
            "execution_id": str(uuid4()),
            "timestamp": datetime.now(UTC),
            "agent_type": "code_generator",
            "success": True,
            "duration_ms": 1500,
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "sequential_validation",
                    "confidence_score": 0.85,
                }
            ],
            "intelligence_used": [
                {"source": "rag", "query": "ONEX patterns", "relevance": 0.9}
            ],
            "quality_metrics": {
                "code_quality": 0.85,
                "onex_compliance": 0.9,
            },
            "metadata": {
                "context": "test_execution",
                "environment": "development",
            },
        }

    @pytest.mark.asyncio
    async def test_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator.gate == EnumQualityGate.UAKS_INTEGRATION
        assert validator.gate.category == "knowledge_validation"
        assert validator.gate.performance_target_ms == 50

    @pytest.mark.asyncio
    async def test_valid_uaks_knowledge(self, validator, valid_uaks_knowledge):
        """Test validation passes with valid UAKS knowledge."""
        context = {"uaks_knowledge": valid_uaks_knowledge}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.gate == EnumQualityGate.UAKS_INTEGRATION
        assert "UAKS integration validated" in result.message
        assert result.metadata["execution_id_valid"] is True
        assert result.metadata["patterns_count"] == 1
        assert result.metadata["quality_metrics_count"] == 2

    @pytest.mark.asyncio
    async def test_missing_uaks_knowledge(self, validator):
        """Test validation fails when UAKS knowledge is missing."""
        context = {}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "not found" in result.message
        assert result.metadata["error"] == "missing_uaks_knowledge"

    @pytest.mark.asyncio
    async def test_invalid_knowledge_type(self, validator):
        """Test validation fails with non-dict knowledge."""
        context = {"uaks_knowledge": "not a dict"}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "must be dict" in result.message

    @pytest.mark.asyncio
    async def test_missing_required_fields(self, validator):
        """Test validation fails when required fields are missing."""
        context = {
            "uaks_knowledge": {
                "execution_id": str(uuid4()),
                # Missing: timestamp, agent_type, success
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Missing required fields" in result.message
        assert "timestamp" in result.message
        assert "agent_type" in result.message
        assert "success" in result.message

    @pytest.mark.asyncio
    async def test_invalid_execution_id(self, validator):
        """Test validation fails with invalid execution_id format."""
        context = {
            "uaks_knowledge": {
                "execution_id": "not-a-uuid",
                "timestamp": datetime.now(UTC),
                "agent_type": "test",
                "success": True,
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Invalid execution_id format" in result.message
        assert result.metadata["execution_id_valid"] is False

    @pytest.mark.asyncio
    async def test_missing_recommended_fields(self, validator):
        """Test warnings for missing recommended fields."""
        context = {
            "uaks_knowledge": {
                "execution_id": str(uuid4()),
                "timestamp": datetime.now(UTC),
                "agent_type": "test",
                "success": True,
                # Missing recommended fields
            }
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "warnings" in result.message
        warnings = result.metadata["warnings"]
        assert any("Missing recommended fields" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_invalid_patterns_type(self, validator, valid_uaks_knowledge):
        """Test validation fails when patterns_extracted is not a list."""
        valid_uaks_knowledge["patterns_extracted"] = "not a list"
        context = {"uaks_knowledge": valid_uaks_knowledge}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "patterns_extracted must be list" in result.message

    @pytest.mark.asyncio
    async def test_invalid_quality_metrics_type(self, validator, valid_uaks_knowledge):
        """Test validation fails when quality_metrics is not a dict."""
        valid_uaks_knowledge["quality_metrics"] = "not a dict"
        context = {"uaks_knowledge": valid_uaks_knowledge}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "quality_metrics must be dict" in result.message

    @pytest.mark.asyncio
    async def test_storage_success(self, validator, valid_uaks_knowledge):
        """Test validation with successful storage."""
        context = {
            "uaks_knowledge": valid_uaks_knowledge,
            "uaks_storage_result": {
                "success": True,
                "stored_at": datetime.now(UTC),
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["storage_attempted"] is True
        assert result.metadata["storage_success"] is True

    @pytest.mark.asyncio
    async def test_storage_failure(self, validator, valid_uaks_knowledge):
        """Test warning when storage fails (graceful degradation)."""
        context = {
            "uaks_knowledge": valid_uaks_knowledge,
            "uaks_storage_result": {
                "success": False,
                "error": "Connection timeout",
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"  # Storage failure is non-critical
        assert result.metadata["storage_attempted"] is True
        assert result.metadata["storage_success"] is False
        warnings = result.metadata["warnings"]
        assert any("storage failed" in w.lower() for w in warnings)

    @pytest.mark.asyncio
    async def test_storage_not_attempted(self, validator, valid_uaks_knowledge):
        """Test warning when storage result not available."""
        context = {"uaks_knowledge": valid_uaks_knowledge}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["storage_attempted"] is False
        warnings = result.metadata["warnings"]
        assert any("storage result not available" in w.lower() for w in warnings)

    @pytest.mark.asyncio
    async def test_multiple_patterns(self, validator, valid_uaks_knowledge):
        """Test validation with multiple patterns."""
        valid_uaks_knowledge["patterns_extracted"] = [
            {"pattern_type": "workflow", "pattern_name": "p1"},
            {"pattern_type": "code", "pattern_name": "p2"},
            {"pattern_type": "naming", "pattern_name": "p3"},
        ]
        context = {"uaks_knowledge": valid_uaks_knowledge}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["patterns_count"] == 3


class TestPatternRecognitionValidator:
    """Test suite for KV-002: Pattern Recognition Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return PatternRecognitionValidator()

    @pytest.fixture
    def valid_patterns(self):
        """Create valid pattern list."""
        return [
            {
                "pattern_type": "workflow",
                "pattern_name": "sequential_validation",
                "pattern_description": "Input -> Process -> Output validation flow",
                "confidence_score": 0.85,
                "source_context": {"agent": "code_generator"},
                "reuse_conditions": ["validation_workflows"],
                "examples": [{"input": "data", "output": "validated"}],
            },
            {
                "pattern_type": "code",
                "pattern_name": "dependency_injection",
                "pattern_description": "Constructor-based dependency injection",
                "confidence_score": 0.92,
                "source_context": {"agent": "architecture_designer"},
                "reuse_conditions": ["onex_nodes"],
                "examples": [{"class": "NodeEffect", "container": "ModelContainer"}],
            },
        ]

    @pytest.mark.asyncio
    async def test_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator.gate == EnumQualityGate.PATTERN_RECOGNITION
        assert validator.gate.category == "knowledge_validation"
        assert validator.gate.performance_target_ms == 40
        assert validator.gate.dependencies == ["KV-001"]

    @pytest.mark.asyncio
    async def test_valid_patterns(self, validator, valid_patterns):
        """Test validation passes with valid patterns."""
        context = {"patterns_extracted": valid_patterns}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.gate == EnumQualityGate.PATTERN_RECOGNITION
        assert "2 patterns validated" in result.message
        assert result.metadata["valid_patterns"] == 2
        assert result.metadata["invalid_patterns"] == 0

    @pytest.mark.asyncio
    async def test_missing_patterns(self, validator):
        """Test validation fails when patterns are missing."""
        context = {}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No patterns extracted" in result.message
        assert result.metadata["error"] == "missing_patterns"

    @pytest.mark.asyncio
    async def test_invalid_patterns_type(self, validator):
        """Test validation fails when patterns is not a list."""
        context = {"patterns_extracted": "not a list"}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "must be list" in result.message

    @pytest.mark.asyncio
    async def test_empty_patterns_list(self, validator):
        """Test validation fails with empty patterns list."""
        context = {"patterns_extracted": []}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["error"] == "empty_patterns_list"

    @pytest.mark.asyncio
    async def test_pattern_missing_required_fields(self, validator):
        """Test validation fails when pattern missing required fields."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    # Missing: pattern_name, pattern_description, confidence_score
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["invalid_patterns"] == 1
        issues = result.metadata["issues"]
        assert any("Pattern 0" in issue for issue in issues)
        assert any("Missing required field" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_invalid_confidence_score_type(self, validator):
        """Test validation fails with non-numeric confidence."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "test",
                    "pattern_description": "Test pattern",
                    "confidence_score": "high",  # Should be float
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["invalid_patterns"] == 1
        issues = result.metadata["issues"]
        assert any("confidence_score must be numeric" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_invalid_confidence_score_range(self, validator):
        """Test validation fails with confidence out of range."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "test",
                    "pattern_description": "Test pattern",
                    "confidence_score": 1.5,  # > 1.0
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["invalid_patterns"] == 1
        issues = result.metadata["issues"]
        assert any("must be 0.0-1.0" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_low_quality_pattern(self, validator):
        """Test warning for patterns below quality threshold."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "low_quality",
                    "pattern_description": "Low quality pattern",
                    "confidence_score": 0.4,  # < 0.6 threshold
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "passed"  # Still passes but with warnings
        assert result.metadata["low_quality_patterns"] == 1
        warnings = result.metadata["warnings"]
        assert any("Low confidence" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_unknown_pattern_type(self, validator, valid_patterns):
        """Test warning for unknown pattern types."""
        valid_patterns[0]["pattern_type"] = "unknown_type"
        context = {"patterns_extracted": valid_patterns}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "unknown_type" in result.metadata["unknown_pattern_types"]
        warnings = result.metadata["warnings"]
        assert any("Unknown type" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_invalid_reuse_conditions_type(self, validator):
        """Test validation fails with invalid reuse_conditions type."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "test",
                    "pattern_description": "Test",
                    "confidence_score": 0.8,
                    "reuse_conditions": "not a list",  # Should be list
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["invalid_patterns"] == 1
        issues = result.metadata["issues"]
        assert any("reuse_conditions must be list" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_invalid_examples_type(self, validator):
        """Test validation fails with invalid examples type."""
        context = {
            "patterns_extracted": [
                {
                    "pattern_type": "workflow",
                    "pattern_name": "test",
                    "pattern_description": "Test",
                    "confidence_score": 0.8,
                    "examples": "not a list",  # Should be list
                }
            ]
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert result.metadata["invalid_patterns"] == 1
        issues = result.metadata["issues"]
        assert any("examples must be list" in issue for issue in issues)

    @pytest.mark.asyncio
    async def test_pattern_storage_success(self, validator, valid_patterns):
        """Test validation with successful pattern storage."""
        context = {
            "patterns_extracted": valid_patterns,
            "pattern_storage_result": {
                "success": True,
                "patterns_stored": 2,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["storage_attempted"] is True
        assert result.metadata["storage_success"] is True

    @pytest.mark.asyncio
    async def test_pattern_storage_failure(self, validator, valid_patterns):
        """Test warning when pattern storage fails."""
        context = {
            "patterns_extracted": valid_patterns,
            "pattern_storage_result": {
                "success": False,
                "error": "Database unavailable",
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["storage_attempted"] is True
        assert result.metadata["storage_success"] is False
        warnings = result.metadata["warnings"]
        assert any("storage failed" in w.lower() for w in warnings)

    @pytest.mark.asyncio
    async def test_mixed_quality_patterns(self, validator):
        """Test validation with mix of high and low quality patterns."""
        patterns = [
            {
                "pattern_type": "workflow",
                "pattern_name": "high_quality",
                "pattern_description": "High quality pattern",
                "confidence_score": 0.9,
            },
            {
                "pattern_type": "code",
                "pattern_name": "low_quality",
                "pattern_description": "Low quality pattern",
                "confidence_score": 0.5,
            },
            {
                "pattern_type": "naming",
                "pattern_name": "medium_quality",
                "pattern_description": "Medium quality pattern",
                "confidence_score": 0.7,
            },
        ]
        context = {"patterns_extracted": patterns}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["valid_patterns"] == 3
        assert result.metadata["low_quality_patterns"] == 1
        assert "below quality threshold" in result.message

    @pytest.mark.asyncio
    async def test_pattern_with_all_fields(self, validator):
        """Test validation with pattern containing all recommended fields."""
        pattern = {
            "pattern_type": "workflow",
            "pattern_name": "complete_pattern",
            "pattern_description": "Pattern with all fields",
            "confidence_score": 0.95,
            "source_context": {
                "agent": "test",
                "file": "test.py",
                "line": 42,
            },
            "reuse_conditions": ["condition1", "condition2"],
            "examples": [
                {"input": "x", "output": "y"},
                {"input": "a", "output": "b"},
            ],
        }
        context = {"patterns_extracted": [pattern]}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["valid_patterns"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
"""
Test suite for Intelligence Validation Quality Gates.

Comprehensive tests for IV-001, IV-002, IV-003 validators with mock RAG
queries and intelligence application scenarios.

ONEX v2.0 Compliance:
- Async test patterns
- Mock data for RAG (no actual RAG calls)
- Comprehensive validation scenarios
- Performance verification
"""

import pytest

from agents.lib.models.model_quality_gate import EnumQualityGate
from agents.lib.validators.intelligence_validators import (
    KnowledgeApplicationValidator,
    LearningCaptureValidator,
    RAGQueryValidationValidator,
)


class TestRAGQueryValidationValidator:
    """Test suite for IV-001: RAG Query Validation Validator."""

    @pytest.fixture
    def validator(self) -> RAGQueryValidationValidator:
        """Create validator instance."""
        return RAGQueryValidationValidator()

    @pytest.fixture
    def successful_rag_query(self) -> dict:
        """Mock successful RAG query data."""
        return {
            "executed": True,
            "results": [
                {
                    "id": "result_1",
                    "content": "Example pattern for error handling",
                    "relevance_score": 0.92,
                    "source": "archon_docs",
                },
                {
                    "id": "result_2",
                    "content": "ONEX architecture guidelines",
                    "relevance_score": 0.88,
                    "source": "onex_patterns",
                },
                {
                    "id": "result_3",
                    "content": "Best practices for async code",
                    "relevance_score": 0.85,
                    "source": "python_docs",
                },
                {
                    "id": "result_4",
                    "content": "Type safety patterns",
                    "relevance_score": 0.78,
                    "source": "onex_patterns",
                },
            ],
            "query_time_ms": 1200,
            "error": None,
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(
        self, validator: RAGQueryValidationValidator
    ):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.RAG_QUERY_VALIDATION
        assert validator.gate.category == "intelligence_validation"
        assert validator.gate.performance_target_ms == 100

    @pytest.mark.asyncio
    async def test_successful_rag_query_validation(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test validation passes with successful RAG query."""
        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.gate == EnumQualityGate.RAG_QUERY_VALIDATION
        assert "4 results" in result.message
        assert result.metadata["result_count"] == 4
        assert result.metadata["source_diversity"] == 3  # 3 unique sources
        assert not result.metadata["performance_warning"]  # 1200ms < 1500ms

    @pytest.mark.asyncio
    async def test_rag_query_not_executed(self, validator: RAGQueryValidationValidator):
        """Test validation fails when RAG query was not executed."""
        context = {"rag_query": {"executed": False}}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "not executed" in result.message
        assert result.metadata["reason"] == "rag_query_not_executed"

    @pytest.mark.asyncio
    async def test_rag_query_error(self, validator: RAGQueryValidationValidator):
        """Test validation fails when RAG query had an error."""
        context = {
            "rag_query": {
                "executed": True,
                "error": "Connection timeout to RAG service",
                "results": [],
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "RAG query failed" in result.message
        assert result.metadata["reason"] == "rag_query_error"
        assert "Connection timeout" in result.metadata["error"]

    @pytest.mark.asyncio
    async def test_insufficient_results(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test validation fails with insufficient results."""
        # Only 2 results, minimum is 3
        successful_rag_query["results"] = successful_rag_query["results"][:2]

        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Insufficient RAG results" in result.message
        assert result.metadata["result_count"] == 2
        assert result.metadata["min_required"] == 3

    @pytest.mark.asyncio
    async def test_low_relevance_scores(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test validation fails when too many results have low relevance."""
        # Make all results low relevance
        for result in successful_rag_query["results"]:
            result["relevance_score"] = 0.4

        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "low-relevance results" in result.message
        assert result.metadata["low_relevance_count"] == 4
        assert result.metadata["low_relevance_ratio"] == 1.0

    @pytest.mark.asyncio
    async def test_some_low_relevance_acceptable(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test validation passes when some (but not too many) results are low relevance."""
        # Make 1 out of 4 results low relevance (25%, below 50% threshold)
        successful_rag_query["results"][3]["relevance_score"] = 0.5

        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["low_relevance_count"] == 1

    @pytest.mark.asyncio
    async def test_performance_warning(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test performance warning when query time exceeds threshold."""
        successful_rag_query["query_time_ms"] = 2000  # > 1500ms default

        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "passed"  # Still passes, just warns
        assert result.metadata["performance_warning"] is True
        assert result.metadata["query_time_ms"] == 2000

    @pytest.mark.asyncio
    async def test_source_diversity(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test source diversity calculation."""
        context = {"rag_query": successful_rag_query}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["source_diversity"] == 3
        assert set(result.metadata["sources"]) == {
            "archon_docs",
            "onex_patterns",
            "python_docs",
        }

    @pytest.mark.asyncio
    async def test_custom_thresholds(
        self, validator: RAGQueryValidationValidator, successful_rag_query: dict
    ):
        """Test validation with custom thresholds."""
        context = {
            "rag_query": successful_rag_query,
            "min_rag_results": 5,  # Require 5 results instead of 3
            "min_relevance_score": 0.9,  # Higher relevance threshold
        }

        result = await validator.validate(context)

        # Should fail due to insufficient results (4 < 5)
        assert result.status == "failed"
        assert result.metadata["min_required"] == 5


class TestKnowledgeApplicationValidator:
    """Test suite for IV-002: Knowledge Application Validator."""

    @pytest.fixture
    def validator(self) -> KnowledgeApplicationValidator:
        """Create validator instance."""
        return KnowledgeApplicationValidator()

    @pytest.fixture
    def successful_knowledge_application(self) -> dict:
        """Mock successful knowledge application data."""
        return {
            "intelligence_used": ["result_1", "result_2", "result_3"],
            "patterns_applied": ["error_handling_pattern", "async_pattern"],
            "output": "Generated code with proper error handling and async patterns...",
            "critical_intelligence": ["result_1"],  # Only result_1 is critical
        }

    @pytest.fixture
    def mock_rag_results(self) -> dict:
        """Mock RAG results for cross-validation."""
        return {
            "results": [
                {"id": "result_1", "content": "Critical pattern"},
                {"id": "result_2", "content": "Secondary pattern"},
                {"id": "result_3", "content": "Tertiary pattern"},
            ]
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(
        self, validator: KnowledgeApplicationValidator
    ):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.KNOWLEDGE_APPLICATION
        assert validator.gate.category == "intelligence_validation"
        assert validator.gate.performance_target_ms == 75

    @pytest.mark.asyncio
    async def test_successful_knowledge_application(
        self,
        validator: KnowledgeApplicationValidator,
        successful_knowledge_application: dict,
        mock_rag_results: dict,
    ):
        """Test validation passes with successful knowledge application."""
        context = {
            "knowledge_application": successful_knowledge_application,
            "rag_query": mock_rag_results,
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "3 items used" in result.message
        assert "2 patterns applied" in result.message
        assert result.metadata["intelligence_used_count"] == 3
        assert result.metadata["patterns_applied_count"] == 2
        assert result.metadata["critical_all_used"] is True
        assert result.metadata["usage_ratio"] == 1.0  # All RAG results used

    @pytest.mark.asyncio
    async def test_no_intelligence_used(self, validator: KnowledgeApplicationValidator):
        """Test validation fails when no intelligence was used."""
        context = {
            "knowledge_application": {
                "intelligence_used": [],
                "patterns_applied": [],
                "output": "Some output",
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No intelligence" in result.message
        assert result.metadata["reason"] == "no_intelligence_used"

    @pytest.mark.asyncio
    async def test_critical_intelligence_ignored(
        self,
        validator: KnowledgeApplicationValidator,
        successful_knowledge_application: dict,
    ):
        """Test validation fails when critical intelligence is ignored."""
        # Remove critical result from used intelligence
        successful_knowledge_application["intelligence_used"] = ["result_2", "result_3"]
        # result_1 is critical but not used

        context = {"knowledge_application": successful_knowledge_application}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Critical intelligence ignored" in result.message
        assert "result_1" in result.metadata["ignored_critical"]
        assert result.metadata["critical_count"] == 1

    @pytest.mark.asyncio
    async def test_no_output_generated(
        self,
        validator: KnowledgeApplicationValidator,
        successful_knowledge_application: dict,
    ):
        """Test validation fails when no output was generated."""
        successful_knowledge_application["output"] = ""

        context = {"knowledge_application": successful_knowledge_application}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No output generated" in result.message
        assert result.metadata["reason"] == "no_output"

    @pytest.mark.asyncio
    async def test_no_patterns_applied_warning(
        self,
        validator: KnowledgeApplicationValidator,
        successful_knowledge_application: dict,
    ):
        """Test validation with no patterns applied (warning, not failure)."""
        successful_knowledge_application["patterns_applied"] = []

        context = {"knowledge_application": successful_knowledge_application}

        result = await validator.validate(context)

        # Should still pass - patterns might not always be applicable
        assert result.status == "passed"
        assert result.metadata["patterns_applied_count"] == 0

    @pytest.mark.asyncio
    async def test_usage_ratio_calculation(
        self,
        validator: KnowledgeApplicationValidator,
        successful_knowledge_application: dict,
        mock_rag_results: dict,
    ):
        """Test usage ratio calculation."""
        # Use only 2 out of 3 RAG results
        successful_knowledge_application["intelligence_used"] = ["result_1", "result_2"]

        context = {
            "knowledge_application": successful_knowledge_application,
            "rag_query": mock_rag_results,
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["usage_ratio"] == pytest.approx(0.667, rel=0.01)


class TestLearningCaptureValidator:
    """Test suite for IV-003: Learning Capture Validator."""

    @pytest.fixture
    def validator(self) -> LearningCaptureValidator:
        """Create validator instance."""
        return LearningCaptureValidator()

    @pytest.fixture
    def successful_learning_capture(self) -> dict:
        """Mock successful learning capture data."""
        return {
            "patterns_extracted": [
                {
                    "name": "error_handling_pattern",
                    "description": "Common error handling approach",
                    "examples": ["try/except with context"],
                },
                {
                    "name": "async_pattern",
                    "description": "Async/await pattern for I/O operations",
                    "examples": ["async def with await"],
                },
            ],
            "learning_data": {
                "execution_context": "ONEX node generation",
                "success_metrics": {"quality_score": 0.9, "performance_ms": 1200},
                "reuse_metadata": {
                    "tags": ["error_handling", "async", "ONEX"],
                    "context": "Node generation workflow",
                    "applicability": "All ONEX node types",
                },
            },
            "uaks_stored": True,
            "storage_error": None,
        }

    @pytest.mark.asyncio
    async def test_validator_initialization(self, validator: LearningCaptureValidator):
        """Test validator initializes with correct gate."""
        assert validator.gate == EnumQualityGate.LEARNING_CAPTURE
        assert validator.gate.category == "intelligence_validation"
        assert validator.gate.performance_target_ms == 50

    @pytest.mark.asyncio
    async def test_successful_learning_capture(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation passes with successful learning capture."""
        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "2 patterns" in result.message
        assert result.metadata["patterns_extracted_count"] == 2
        assert not result.metadata["pattern_warning"]
        assert result.metadata["uaks_stored"] is True
        assert not result.metadata["storage_warning"]
        assert result.metadata["metadata_completeness"] == 1.0  # All metadata present

    @pytest.mark.asyncio
    async def test_no_patterns_extracted_warning(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation with no patterns extracted (warning)."""
        successful_learning_capture["patterns_extracted"] = []

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        # Should still pass but with warning
        assert result.status == "passed"
        assert result.metadata["pattern_warning"] is True
        assert result.metadata["patterns_extracted_count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_pattern_format(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation fails with invalid pattern format."""
        # Add pattern without required fields
        successful_learning_capture["patterns_extracted"].append(
            {"name": "incomplete_pattern"}  # Missing description
        )

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Invalid pattern format" in result.message
        assert result.metadata["reason"] == "invalid_pattern_format"
        assert 2 in result.metadata["invalid_pattern_indices"]

    @pytest.mark.asyncio
    async def test_pattern_not_dict(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation fails when pattern is not a dict."""
        successful_learning_capture["patterns_extracted"].append(
            "invalid_pattern_string"
        )

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Invalid pattern format" in result.message

    @pytest.mark.asyncio
    async def test_no_learning_data(self, validator: LearningCaptureValidator):
        """Test validation fails when no learning data captured."""
        context = {
            "learning_capture": {
                "patterns_extracted": [{"name": "pattern", "description": "A pattern"}],
                "learning_data": {},  # Empty learning data
                "uaks_stored": True,
            }
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No learning data captured" in result.message
        assert result.metadata["reason"] == "no_learning_data"

    @pytest.mark.asyncio
    async def test_uaks_not_attempted(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation fails when UAKS storage not attempted."""
        successful_learning_capture["uaks_stored"] = False
        successful_learning_capture["storage_error"] = None

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "not attempted" in result.message
        assert result.metadata["reason"] == "uaks_not_attempted"

    @pytest.mark.asyncio
    async def test_uaks_storage_error_warning(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test validation passes with UAKS storage error (attempt was made)."""
        successful_learning_capture["uaks_stored"] = False
        successful_learning_capture["storage_error"] = "Connection timeout"

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        # Should pass because attempt was made
        assert result.status == "passed"
        assert result.metadata["storage_warning"] is True
        assert result.metadata["storage_error"] == "Connection timeout"

    @pytest.mark.asyncio
    async def test_metadata_completeness(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test metadata completeness calculation."""
        # Remove some metadata fields
        successful_learning_capture["learning_data"]["reuse_metadata"] = {
            "tags": ["some_tags"],
            # Missing context and applicability
        }

        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["metadata_completeness"] == pytest.approx(
            0.333, rel=0.01
        )
        assert result.metadata["has_tags"] is True
        assert result.metadata["has_context"] is False
        assert result.metadata["has_applicability"] is False

    @pytest.mark.asyncio
    async def test_learning_data_keys_tracking(
        self, validator: LearningCaptureValidator, successful_learning_capture: dict
    ):
        """Test learning data keys are tracked in metadata."""
        context = {"learning_capture": successful_learning_capture}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert set(result.metadata["learning_data_keys"]) == {
            "execution_context",
            "success_metrics",
            "reuse_metadata",
        }

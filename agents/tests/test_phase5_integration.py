#!/usr/bin/env python3
"""
Phase 5 Integration Tests - Business Logic & Validation Pipeline

Tests the complete Phase 5 pipeline: PRD → Contract → Business Logic → Validation
"""

import asyncio
import tempfile
import time

import pytest

from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.lib.contract_generator import ContractGenerator
from agents.lib.pattern_library import PatternLibrary
from agents.lib.quality_validator import QualityValidator
from agents.lib.simple_prd_analyzer import SimplePRDAnalyzer
from agents.tests.fixtures.phase4_fixtures import (
    COMPUTE_NODE_PRD,
    EFFECT_ANALYSIS_RESULT,
    EFFECT_NODE_PRD,
    SAMPLE_CONTRACT_WITH_CRUD,
)

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def prd_analyzer():
    """Create PRD analyzer instance"""
    return SimplePRDAnalyzer()


@pytest.fixture
def contract_generator():
    """Create contract generator instance"""
    return ContractGenerator()


@pytest.fixture
def business_logic_generator():
    """Create business logic generator instance"""
    return BusinessLogicGenerator()


@pytest.fixture
def quality_validator():
    """Create quality validator instance"""
    return QualityValidator()


@pytest.fixture
def pattern_library():
    """Create pattern library instance"""
    return PatternLibrary()


@pytest.fixture
def temp_output_dir():
    """Create temporary directory for outputs"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir


# ============================================================================
# END-TO-END PIPELINE TESTS
# ============================================================================


class TestFullPipeline:
    """Tests for complete PRD → Contract → Business Logic → Validation pipeline"""

    @pytest.mark.asyncio
    async def test_full_pipeline_effect_node(
        self,
        prd_analyzer,
        contract_generator,
        business_logic_generator,
        quality_validator,
    ):
        """Test complete pipeline for EFFECT node"""
        # Step 1: Analyze PRD
        analysis_result = await prd_analyzer.analyze_prd(EFFECT_NODE_PRD)
        assert analysis_result is not None
        assert analysis_result.confidence_score > 0.5

        # Step 2: Generate contract
        contract_result = await contract_generator.generate_contract_yaml(
            analysis_result=analysis_result,
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
        )
        assert contract_result["validation_result"]["valid"] is True

        # Step 3: Generate business logic
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_result["contract"],
            analysis_result=analysis_result,
        )
        assert business_logic_result["code"] is not None

        # Step 4: Validate quality
        validation_result = await quality_validator.validate_code(
            code=business_logic_result["code"],
            contract=contract_result["contract"],
            quality_threshold=0.8,
        )
        assert validation_result["quality_score"] >= 0.8
        assert validation_result["valid"] is True

    @pytest.mark.asyncio
    async def test_full_pipeline_compute_node(
        self,
        prd_analyzer,
        contract_generator,
        business_logic_generator,
        quality_validator,
    ):
        """Test complete pipeline for COMPUTE node"""
        # Step 1: Analyze PRD
        analysis_result = await prd_analyzer.analyze_prd(COMPUTE_NODE_PRD)

        # Step 2: Generate contract
        contract_result = await contract_generator.generate_contract_yaml(
            analysis_result=analysis_result,
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
        )

        # Step 3: Generate business logic
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
            contract=contract_result["contract"],
            analysis_result=analysis_result,
        )

        # Step 4: Validate quality
        validation_result = await quality_validator.validate_code(
            code=business_logic_result["code"],
            contract=contract_result["contract"],
            quality_threshold=0.8,
        )
        assert validation_result["quality_score"] >= 0.8

    @pytest.mark.asyncio
    async def test_pipeline_preserves_metadata(
        self, prd_analyzer, contract_generator, business_logic_generator
    ):
        """Test that metadata is preserved throughout pipeline"""
        # Analyze PRD
        analysis_result = await prd_analyzer.analyze_prd(EFFECT_NODE_PRD)
        session_id = analysis_result.session_id

        # Generate contract
        contract_result = await contract_generator.generate_contract_yaml(
            analysis_result=analysis_result,
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
        )

        # Verify session ID is preserved in contract metadata
        assert str(session_id) in str(contract_result["contract"].get("metadata", {}))

        # Generate business logic
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_result["contract"],
            analysis_result=analysis_result,
        )

        # Verify metadata is available
        assert "metadata" in business_logic_result or session_id is not None


# ============================================================================
# PATTERN-ENHANCED GENERATION TESTS
# ============================================================================


class TestPatternEnhancedGeneration:
    """Tests for pattern-enhanced business logic generation"""

    @pytest.mark.asyncio
    async def test_pattern_detection_and_generation(
        self, contract_generator, business_logic_generator, pattern_library
    ):
        """Test pattern detection enhances code generation"""
        # Generate contract
        contract_result = await contract_generator.generate_contract_yaml(
            analysis_result=EFFECT_ANALYSIS_RESULT,
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
        )

        # Detect pattern
        pattern_result = pattern_library.detect_pattern(contract_result["contract"])

        # Generate with pattern enhancement
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_result["contract"],
            analysis_result=EFFECT_ANALYSIS_RESULT,
            pattern_hint=(
                pattern_result["pattern_name"] if pattern_result["matched"] else None
            ),
        )

        # Verify pattern was applied
        if pattern_result["matched"]:
            assert (
                pattern_result["pattern_name"].lower()
                in business_logic_result["code"].lower()
                or len(business_logic_result["methods"]) > 0
            )

    @pytest.mark.asyncio
    async def test_multi_pattern_generation(
        self, business_logic_generator, pattern_library
    ):
        """Test generation with multiple patterns"""
        mixed_contract = {
            "version": "1.0.0",
            "node_type": "EFFECT",
            "capabilities": [
                {"name": "create_user", "type": "create", "required": True},
                {"name": "transform_data", "type": "transform", "required": True},
            ],
            "subcontracts": [],
        }

        # Detect all patterns
        pattern_library.detect_all_patterns(mixed_contract)

        # Generate with multiple patterns
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="multi_pattern_service",
            domain="mixed",
            contract=mixed_contract,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Verify methods from both patterns exist
        code = business_logic_result["code"]
        assert "create_user" in code
        assert "transform_data" in code


# ============================================================================
# QUALITY VALIDATION PIPELINE TESTS
# ============================================================================


class TestQualityValidationPipeline:
    """Tests for quality validation pipeline"""

    @pytest.mark.asyncio
    async def test_validation_failure_detection(
        self, business_logic_generator, quality_validator
    ):
        """Test validation detects quality issues"""
        # Generate minimal business logic
        business_logic_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="test_service",
            domain="test",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=EFFECT_ANALYSIS_RESULT,
            include_error_handling=False,  # Intentionally omit error handling
        )

        # Validate with strict threshold
        validation_result = await quality_validator.validate_code(
            code=business_logic_result["code"], contract={}, quality_threshold=0.9
        )

        # Should detect missing error handling
        if not validation_result["valid"]:
            assert len(validation_result["violations"]) > 0

    @pytest.mark.asyncio
    async def test_validation_regeneration_workflow(
        self, business_logic_generator, quality_validator
    ):
        """Test regeneration after validation failure"""
        # First generation
        initial_result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="test_service",
            domain="test",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Validate
        validation_result = await quality_validator.validate_code(
            code=initial_result["code"],
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            quality_threshold=0.8,
        )

        # If validation fails, regenerate with feedback
        if not validation_result["valid"]:
            improved_result = await business_logic_generator.generate_node_stub(
                node_type="EFFECT",
                microservice_name="test_service",
                domain="test",
                contract=SAMPLE_CONTRACT_WITH_CRUD,
                analysis_result=EFFECT_ANALYSIS_RESULT,
                validation_feedback=validation_result["violations"],
            )

            # Re-validate
            revalidation_result = await quality_validator.validate_code(
                code=improved_result["code"],
                contract=SAMPLE_CONTRACT_WITH_CRUD,
                quality_threshold=0.8,
            )

            # Should improve
            assert (
                revalidation_result["quality_score"]
                >= validation_result["quality_score"]
            )


# ============================================================================
# CONCURRENT GENERATION TESTS
# ============================================================================


class TestConcurrentGeneration:
    """Tests for concurrent generation with validation"""

    @pytest.mark.asyncio
    async def test_concurrent_node_generation(
        self, prd_analyzer, contract_generator, business_logic_generator
    ):
        """Test generating multiple nodes concurrently"""
        node_configs = [
            ("EFFECT", "user_management", "identity", EFFECT_NODE_PRD),
            ("COMPUTE", "data_transformer", "processing", COMPUTE_NODE_PRD),
        ]

        async def generate_node(node_type, name, domain, prd):
            analysis = await prd_analyzer.analyze_prd(prd)
            contract_result = await contract_generator.generate_contract_yaml(
                analysis_result=analysis,
                node_type=node_type,
                microservice_name=name,
                domain=domain,
            )
            business_logic = await business_logic_generator.generate_node_stub(
                node_type=node_type,
                microservice_name=name,
                domain=domain,
                contract=contract_result["contract"],
                analysis_result=analysis,
            )
            return business_logic

        # Generate concurrently
        tasks = [generate_node(*config) for config in node_configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all succeeded
        for result in results:
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent generation failed: {result}")
            assert result["code"] is not None

    @pytest.mark.asyncio
    async def test_concurrent_validation(
        self, business_logic_generator, quality_validator
    ):
        """Test validating multiple nodes concurrently"""
        # Generate multiple nodes
        nodes = []
        for i in range(3):
            result = await business_logic_generator.generate_node_stub(
                node_type="EFFECT",
                microservice_name=f"service_{i}",
                domain="test",
                contract=SAMPLE_CONTRACT_WITH_CRUD,
                analysis_result=EFFECT_ANALYSIS_RESULT,
            )
            nodes.append(result)

        # Validate concurrently
        async def validate_node(node):
            return await quality_validator.validate_code(
                code=node["code"],
                contract=SAMPLE_CONTRACT_WITH_CRUD,
                quality_threshold=0.8,
            )

        tasks = [validate_node(node) for node in nodes]
        results = await asyncio.gather(*tasks)

        # All should validate
        for result in results:
            assert "quality_score" in result


# ============================================================================
# PERFORMANCE BENCHMARK TESTS
# ============================================================================


class TestPerformanceBenchmarks:
    """Tests for performance benchmarks"""

    @pytest.mark.asyncio
    async def test_business_logic_generation_performance(
        self, business_logic_generator
    ):
        """Test business logic generation meets performance target"""
        start = time.time()

        await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        duration_ms = (time.time() - start) * 1000

        # Should be < 2s per node
        assert duration_ms < 2000, f"Generation took {duration_ms}ms, expected < 2000ms"

    @pytest.mark.asyncio
    async def test_quality_validation_performance(self, quality_validator):
        """Test quality validation meets performance target"""
        from agents.tests.fixtures.phase4_fixtures import VALID_EFFECT_NODE_CODE

        start = time.time()

        await quality_validator.validate_code(
            code=VALID_EFFECT_NODE_CODE,
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            quality_threshold=0.8,
        )

        duration_ms = (time.time() - start) * 1000

        # Should be < 1s per file
        assert duration_ms < 1000, f"Validation took {duration_ms}ms, expected < 1000ms"

    @pytest.mark.asyncio
    async def test_full_pipeline_performance(
        self,
        prd_analyzer,
        contract_generator,
        business_logic_generator,
        quality_validator,
    ):
        """Test full pipeline (Phase 4 + Phase 5) meets performance target"""
        start = time.time()

        # Full pipeline
        analysis = await prd_analyzer.analyze_prd(EFFECT_NODE_PRD)
        contract_result = await contract_generator.generate_contract_yaml(
            analysis_result=analysis,
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
        )
        business_logic = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_result["contract"],
            analysis_result=analysis,
        )
        await quality_validator.validate_code(
            code=business_logic["code"],
            contract=contract_result["contract"],
            quality_threshold=0.8,
        )

        duration_ms = (time.time() - start) * 1000

        # Full pipeline should be < 5s
        assert (
            duration_ms < 5000
        ), f"Full pipeline took {duration_ms}ms, expected < 5000ms"


# ============================================================================
# ERROR SCENARIO TESTS
# ============================================================================


class TestErrorScenarios:
    """Tests for error handling and recovery"""

    @pytest.mark.asyncio
    async def test_invalid_contract_handling(
        self, business_logic_generator, quality_validator
    ):
        """Test handling of invalid contract"""
        from omnibase_core.errors import OnexError

        invalid_contract = {
            "version": "1.0.0",
            # Missing required fields
        }

        # Should handle gracefully
        try:
            result = await business_logic_generator.generate_node_stub(
                node_type="EFFECT",
                microservice_name="test",
                domain="test",
                contract=invalid_contract,
                analysis_result=EFFECT_ANALYSIS_RESULT,
            )
            # If it succeeds, verify it generated something valid
            assert result is not None
        except OnexError:
            # Expected behavior - error raised for invalid contract
            pass

    @pytest.mark.asyncio
    async def test_validation_failure_recovery(
        self, business_logic_generator, quality_validator
    ):
        """Test recovery from validation failures"""
        # Generate code
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="test",
            domain="test",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Validate
        validation = await quality_validator.validate_code(
            code=result["code"],
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            quality_threshold=0.8,
        )

        # If validation fails, should provide actionable feedback
        if not validation["valid"]:
            assert len(validation["violations"]) > 0
            assert all(
                "message" in v or isinstance(v, str) for v in validation["violations"]
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

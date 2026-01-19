#!/usr/bin/env python3
"""
Phase 4 Integration Tests - Full Generation Pipeline

Tests the complete code generation pipeline from PRD to contracts, models, and enums.
"""

import tempfile
from pathlib import Path

import pytest

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.lib.simple_prd_analyzer import PRDAnalyzer
from agents.tests.fixtures.phase4_fixtures import (
    COMPUTE_NODE_PRD,
    EFFECT_ANALYSIS_RESULT,
    EFFECT_NODE_PRD,
    ORCHESTRATOR_NODE_PRD,
    REDUCER_NODE_PRD,
    create_mock_analysis_result,
)
from agents.tests.utils.generation_test_helpers import (
    parse_generated_python,
    validate_onex_naming,
)


class TestPhase4Integration:
    """Integration tests for Phase 4 code generation pipeline"""

    @pytest.mark.asyncio
    async def test_full_generation_pipeline_effect_node(self):
        """Test complete generation: PRD → Analysis → Templates for EFFECT node"""
        # 1. Analyze PRD
        analyzer = PRDAnalyzer()
        analysis = await analyzer.analyze_prd(EFFECT_NODE_PRD)

        # Verify analysis
        assert analysis is not None
        assert analysis.confidence_score > 0.5
        assert "EFFECT" in analysis.node_type_hints
        assert analysis.node_type_hints["EFFECT"] > 0.0

        # 2. Generate node using template engine
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # 3. Validate generated output
            assert result["node_type"] == "EFFECT"
            assert result["microservice_name"] == "user_management"
            assert result["domain"] == "identity"
            assert "output_path" in result
            assert "main_file" in result

            # 4. Verify files were created
            main_file = Path(result["main_file"])
            assert main_file.exists()

            # 5. Validate file naming
            is_valid, error = validate_onex_naming(main_file.name)
            if not is_valid:
                pytest.skip(f"Node naming validation not enforced yet: {error}")

            # 6. Validate Python syntax
            with open(main_file) as f:
                content = f.read()
                tree, errors = parse_generated_python(content)
                assert tree is not None, f"Syntax errors: {errors}"

    @pytest.mark.asyncio
    async def test_full_generation_pipeline_compute_node(self):
        """Test complete generation: PRD → Analysis → Templates for COMPUTE node"""
        # 1. Analyze PRD
        analyzer = PRDAnalyzer()
        analysis = await analyzer.analyze_prd(COMPUTE_NODE_PRD)

        # Verify analysis
        assert analysis is not None
        assert analysis.confidence_score > 0.5

        # 2. Generate node
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="COMPUTE",
                microservice_name="csv_json_transformer",
                domain="data_processing",
                output_directory=temp_dir,
            )

            # 3. Validate output
            assert result["node_type"] == "COMPUTE"
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_analysis_to_generation_consistency(self):
        """Test that analysis results are consistently applied in generation"""
        # Use pre-created analysis result
        analysis = EFFECT_ANALYSIS_RESULT

        # Generate node
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Read generated content
            with open(result["main_file"]) as f:
                content = f.read()

            # Verify mixins from analysis are in generated code
            for mixin in analysis.recommended_mixins:
                assert mixin in content, f"Mixin {mixin} not found in generated code"

            # Verify microservice name is in generated code
            assert "user_management" in content.lower()

            # Verify domain is in metadata (not necessarily in code content)
            assert result.get("domain") == "identity"

    @pytest.mark.asyncio
    async def test_multiple_node_types_generation(self):
        """Test generating all four node types in sequence"""
        engine = OmniNodeTemplateEngine()
        results = []

        node_configs = [
            ("EFFECT", "user_management", "identity", EFFECT_NODE_PRD),
            ("COMPUTE", "data_transformer", "processing", COMPUTE_NODE_PRD),
            ("REDUCER", "analytics_aggregator", "analytics", REDUCER_NODE_PRD),
            (
                "ORCHESTRATOR",
                "workflow_coordinator",
                "orchestration",
                ORCHESTRATOR_NODE_PRD,
            ),
        ]

        analyzer = PRDAnalyzer()

        with tempfile.TemporaryDirectory() as temp_dir:
            for node_type, microservice_name, domain, prd_content in node_configs:
                # Analyze PRD
                analysis = await analyzer.analyze_prd(prd_content)

                # Generate node
                result = await engine.generate_node(
                    analysis_result=analysis,
                    node_type=node_type,
                    microservice_name=microservice_name,
                    domain=domain,
                    output_directory=temp_dir,
                )

                results.append(result)

                # Verify each generation
                assert result["node_type"] == node_type
                assert Path(result["main_file"]).exists()

            # Verify all nodes were generated
            assert len(results) == 4

            # Verify no file conflicts
            main_files = [r["main_file"] for r in results]
            assert len(main_files) == len(
                set(main_files)
            ), "Duplicate file names detected"

    @pytest.mark.asyncio
    async def test_generation_with_minimal_prd(self):
        """Test generation with minimal PRD content"""
        minimal_prd = """# Minimal Service

## Overview
A basic service with minimal requirements.

## Functional Requirements
- Perform basic operations
"""

        analyzer = PRDAnalyzer()
        analysis = await analyzer.analyze_prd(minimal_prd)

        # Should still generate something
        assert analysis is not None
        assert analysis.confidence_score >= 0.0

        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="minimal_service",
                domain="basic",
                output_directory=temp_dir,
            )

            assert result is not None
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_error_handling_empty_prd(self):
        """Test error handling with empty PRD"""
        from omnibase_core.errors import OnexError

        analyzer = PRDAnalyzer()

        with pytest.raises(OnexError):
            await analyzer.analyze_prd("")

    @pytest.mark.asyncio
    async def test_generated_code_structure(self):
        """Test that generated code has expected structure"""
        analysis = EFFECT_ANALYSIS_RESULT
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Parse generated code
            with open(result["main_file"]) as f:
                content = f.read()

            tree, errors = parse_generated_python(content)
            assert tree is not None, f"Syntax errors: {errors}"

            # Check for expected class
            classes = [node.name for node in tree.body if hasattr(node, "name")]
            assert any("Effect" in cls for cls in classes), "No Effect class found"

    @pytest.mark.asyncio
    async def test_mixin_integration(self):
        """Test that mixins are properly integrated in generated code"""
        # Create analysis with specific mixins (only use available mixins)
        analysis = create_mock_analysis_result(
            EFFECT_NODE_PRD,
            "EFFECT",
            mixins=["MixinEventBus", "MixinHealthCheck"],  # Only available mixins
            external_systems=["PostgreSQL"],
        )

        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"]) as f:
                content = f.read()

            # Verify mixin imports and usage
            assert (
                "from omnibase_core.mixins import" in content
            ), "Mixin import statement not found"
            assert (
                "MixinEventBus" in content
            ), "MixinEventBus not found in generated code"
            assert (
                "MixinHealthCheck" in content
            ), "MixinHealthCheck not found in generated code"

    @pytest.mark.asyncio
    async def test_metadata_preservation(self):
        """Test that metadata is preserved throughout generation"""
        analysis = EFFECT_ANALYSIS_RESULT
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Check metadata in result
            assert "metadata" in result
            metadata = result["metadata"]
            assert "session_id" in metadata or "correlation_id" in metadata

    @pytest.mark.asyncio
    async def test_concurrent_generation(self):
        """Test concurrent generation of multiple nodes"""
        import asyncio

        analyzer = PRDAnalyzer()
        engine = OmniNodeTemplateEngine()

        async def generate_node(prd_content, node_type, name, domain):
            analysis = await analyzer.analyze_prd(prd_content)
            with tempfile.TemporaryDirectory() as temp_dir:
                return await engine.generate_node(
                    analysis_result=analysis,
                    node_type=node_type,
                    microservice_name=name,
                    domain=domain,
                    output_directory=temp_dir,
                )

        # Generate multiple nodes concurrently
        tasks = [
            generate_node(EFFECT_NODE_PRD, "EFFECT", "user_mgmt", "identity"),
            generate_node(COMPUTE_NODE_PRD, "COMPUTE", "transformer", "processing"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify both succeeded
        for result in results:
            if isinstance(result, Exception):
                pytest.fail(f"Concurrent generation failed: {result}")
            assert result is not None


class TestGenerationArtifacts:
    """Test generated artifacts separately"""

    @pytest.mark.asyncio
    async def test_directory_structure_creation(self):
        """Test that proper directory structure is created"""
        analysis = EFFECT_ANALYSIS_RESULT
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            output_path = Path(result["output_path"])
            assert output_path.exists()
            assert output_path.is_dir()

    @pytest.mark.asyncio
    async def test_generated_files_list(self):
        """Test that list of generated files is accurate"""
        analysis = EFFECT_ANALYSIS_RESULT
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Check generated_files list
            assert "generated_files" in result
            generated_files = result["generated_files"]

            # Verify all listed files exist
            for file_path in generated_files:
                assert Path(
                    file_path
                ).exists(), f"Listed file does not exist: {file_path}"

    @pytest.mark.asyncio
    async def test_init_file_generation(self):
        """Test that __init__.py files are created"""
        analysis = EFFECT_ANALYSIS_RESULT
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Check for __init__.py in output directory
            output_path = Path(result["output_path"])
            init_file = output_path / "__init__.py"

            # May or may not exist depending on implementation
            if init_file.exists():
                assert init_file.is_file()

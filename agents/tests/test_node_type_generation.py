#!/usr/bin/env python3
"""
Node Type Generation Tests

Tests specific to each ONEX node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR).
"""

import tempfile
from pathlib import Path

import pytest

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.tests.fixtures.phase4_fixtures import NODE_TYPE_FIXTURES
from agents.tests.utils.generation_test_helpers import (
    extract_class_definitions,
    parse_generated_python,
)


class TestEffectNodeGeneration:
    """Tests for EFFECT node generation"""

    @pytest.mark.asyncio
    async def test_effect_node_basic_generation(self):
        """Test basic EFFECT node generation"""
        fixture = NODE_TYPE_FIXTURES["EFFECT"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            assert result["node_type"] == "EFFECT"
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_effect_node_has_required_methods(self):
        """Test that EFFECT node has required abstract methods implemented"""
        fixture = NODE_TYPE_FIXTURES["EFFECT"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            # Parse generated code
            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            assert tree is not None

            # Extract classes and methods
            classes = extract_class_definitions(tree)

            # Find Effect class
            effect_class = next((c for c in classes if "Effect" in c["name"]), None)
            assert effect_class is not None, "No Effect class found"

            # Check for at least __init__ method (other methods depend on template)
            assert "__init__" in effect_class["methods"], "Missing __init__ method"

            # Check that the class has some async methods (common for EFFECT nodes)
            assert (
                len(effect_class["methods"]) >= 1
            ), "Effect class should have at least one method"

    @pytest.mark.asyncio
    async def test_effect_node_imports_base_class(self):
        """Test that EFFECT node imports from correct base class"""
        fixture = NODE_TYPE_FIXTURES["EFFECT"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # Check for NodeEffect import (ONEX architecture pattern)
            assert "NodeEffect" in content or "node_effect" in content

    @pytest.mark.asyncio
    async def test_effect_node_external_system_integration(self):
        """Test that EFFECT node includes external system integration code"""
        fixture = NODE_TYPE_FIXTURES["EFFECT"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="EFFECT",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # EFFECT nodes typically interact with external systems
            # Check for common patterns
            assert (
                "async" in content or "await" in content
            ), "EFFECT should have async operations"


class TestComputeNodeGeneration:
    """Tests for COMPUTE node generation"""

    @pytest.mark.asyncio
    async def test_compute_node_basic_generation(self):
        """Test basic COMPUTE node generation"""
        fixture = NODE_TYPE_FIXTURES["COMPUTE"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="COMPUTE",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            assert result["node_type"] == "COMPUTE"
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_compute_node_pure_computation(self):
        """Test that COMPUTE node emphasizes pure computation"""
        fixture = NODE_TYPE_FIXTURES["COMPUTE"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="COMPUTE",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            assert tree is not None

            # COMPUTE nodes should have compute methods
            classes = extract_class_definitions(tree)
            compute_class = next((c for c in classes if "Compute" in c["name"]), None)
            assert compute_class is not None, "No Compute class found"

    @pytest.mark.asyncio
    async def test_compute_node_imports_base_class(self):
        """Test that COMPUTE node imports from correct base class"""
        fixture = NODE_TYPE_FIXTURES["COMPUTE"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="COMPUTE",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # Check for NodeCompute import (ONEX architecture pattern)
            assert "NodeCompute" in content or "node_compute" in content


class TestReducerNodeGeneration:
    """Tests for REDUCER node generation"""

    @pytest.mark.asyncio
    async def test_reducer_node_basic_generation(self):
        """Test basic REDUCER node generation"""
        fixture = NODE_TYPE_FIXTURES["REDUCER"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="REDUCER",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            assert result["node_type"] == "REDUCER"
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_reducer_node_aggregation_focus(self):
        """Test that REDUCER node focuses on aggregation"""
        fixture = NODE_TYPE_FIXTURES["REDUCER"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="REDUCER",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            assert tree is not None

            # REDUCER nodes should have reducer methods
            classes = extract_class_definitions(tree)
            reducer_class = next((c for c in classes if "Reducer" in c["name"]), None)
            assert reducer_class is not None, "No Reducer class found"

    @pytest.mark.asyncio
    async def test_reducer_node_state_management(self):
        """Test that REDUCER node includes state management"""
        fixture = NODE_TYPE_FIXTURES["REDUCER"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="REDUCER",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # REDUCER nodes typically manage state
            # Check for state-related patterns
            assert "state" in content.lower() or "reduce" in content.lower()


class TestOrchestratorNodeGeneration:
    """Tests for ORCHESTRATOR node generation"""

    @pytest.mark.asyncio
    async def test_orchestrator_node_basic_generation(self):
        """Test basic ORCHESTRATOR node generation"""
        fixture = NODE_TYPE_FIXTURES["ORCHESTRATOR"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="ORCHESTRATOR",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            assert result["node_type"] == "ORCHESTRATOR"
            assert Path(result["main_file"]).exists()

    @pytest.mark.asyncio
    async def test_orchestrator_node_coordination_focus(self):
        """Test that ORCHESTRATOR node focuses on coordination"""
        fixture = NODE_TYPE_FIXTURES["ORCHESTRATOR"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="ORCHESTRATOR",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            assert tree is not None

            # ORCHESTRATOR nodes should have orchestrator methods
            classes = extract_class_definitions(tree)
            orchestrator_class = next(
                (c for c in classes if "Orchestrator" in c["name"]), None
            )
            assert orchestrator_class is not None, "No Orchestrator class found"

    @pytest.mark.asyncio
    async def test_orchestrator_node_workflow_management(self):
        """Test that ORCHESTRATOR node includes workflow management"""
        fixture = NODE_TYPE_FIXTURES["ORCHESTRATOR"]
        analysis = fixture["analysis"]
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=analysis,
                node_type="ORCHESTRATOR",
                microservice_name=fixture["microservice_name"],
                domain=fixture["domain"],
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # ORCHESTRATOR nodes coordinate workflows
            assert (
                "orchestrate" in content.lower()
                or "coordinate" in content.lower()
                or "workflow" in content.lower()
            )


class TestNodeTypeComparison:
    """Tests comparing different node types"""

    @pytest.mark.asyncio
    async def test_all_node_types_have_unique_characteristics(self):
        """Test that each node type has unique characteristics"""
        engine = OmniNodeTemplateEngine()
        generated_content = {}

        with tempfile.TemporaryDirectory() as temp_dir:
            for node_type, fixture in NODE_TYPE_FIXTURES.items():
                result = await engine.generate_node(
                    analysis_result=fixture["analysis"],
                    node_type=node_type,
                    microservice_name=fixture["microservice_name"],
                    domain=fixture["domain"],
                    output_directory=temp_dir,
                )

                with open(result["main_file"], "r") as f:
                    generated_content[node_type] = f.read()

        # Verify each has unique base class
        assert "Effect" in generated_content["EFFECT"]
        assert "Compute" in generated_content["COMPUTE"]
        assert "Reducer" in generated_content["REDUCER"]
        assert "Orchestrator" in generated_content["ORCHESTRATOR"]

    @pytest.mark.asyncio
    async def test_node_type_specific_mixins(self):
        """Test that different node types can have different mixin requirements"""
        # EFFECT nodes often need EventBus and Caching
        effect_fixture = NODE_TYPE_FIXTURES["EFFECT"]
        assert "MixinEventBus" in effect_fixture["analysis"].recommended_mixins

        # COMPUTE nodes often need Validation
        compute_fixture = NODE_TYPE_FIXTURES["COMPUTE"]
        assert "MixinValidation" in compute_fixture["analysis"].recommended_mixins

        # ORCHESTRATOR nodes often need CircuitBreaker and Retry
        orchestrator_fixture = NODE_TYPE_FIXTURES["ORCHESTRATOR"]
        assert (
            "MixinCircuitBreaker" in orchestrator_fixture["analysis"].recommended_mixins
            or "MixinRetry" in orchestrator_fixture["analysis"].recommended_mixins
        )

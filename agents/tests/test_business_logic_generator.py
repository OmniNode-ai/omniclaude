#!/usr/bin/env python3
"""
Tests for Business Logic Generator (Phase 5)

Tests stub generation for all node types, method signatures from contracts,
mixin integration, error handling patterns, and ONEX compliance.
"""

import tempfile
from pathlib import Path

import pytest
from omnibase_core.errors import OnexError

from agents.lib.business_logic_generator import BusinessLogicGenerator
from agents.tests.fixtures.phase4_fixtures import (
    COMPUTE_ANALYSIS_RESULT,
    EFFECT_ANALYSIS_RESULT,
    NODE_TYPE_FIXTURES,
    ORCHESTRATOR_ANALYSIS_RESULT,
    REDUCER_ANALYSIS_RESULT,
    SAMPLE_CONTRACT_WITH_CRUD,
    SAMPLE_CONTRACT_WITH_TRANSFORMATION,
)
from agents.tests.utils.generation_test_helpers import (
    check_type_annotations,
    extract_class_definitions,
    parse_generated_python,
    validate_class_naming,
    validate_onex_naming,
)

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def business_logic_generator():
    """Create a BusinessLogicGenerator instance"""
    return BusinessLogicGenerator()


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for output files"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    # Cleanup handled by tempdir


# ============================================================================
# EFFECT NODE STUB GENERATION TESTS
# ============================================================================


class TestEffectNodeGeneration:
    """Tests for EFFECT node business logic generation"""

    @pytest.mark.asyncio
    async def test_generate_effect_node_stub(self, business_logic_generator):
        """Test basic EFFECT node stub generation"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Verify result structure
        assert "code" in result
        assert "class_name" in result
        assert "methods" in result
        assert result["node_type"] == "EFFECT"

        # Verify code is valid Python
        tree, errors = parse_generated_python(result["code"])
        assert tree is not None, f"Syntax errors: {errors}"

        # Verify class name follows ONEX naming
        assert result["class_name"].endswith("Effect")
        is_valid, error = validate_class_naming(result["class_name"], "node")
        assert is_valid, f"Class naming violation: {error}"

    @pytest.mark.asyncio
    async def test_effect_node_has_execute_method(self, business_logic_generator):
        """Test EFFECT node has required execute_effect method"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Parse and extract methods
        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)

        assert len(classes) > 0, "No classes found in generated code"
        main_class = classes[0]

        # Verify execute_effect method exists
        assert (
            "execute_effect" in main_class["methods"]
        ), "execute_effect method not found in EFFECT node"

    @pytest.mark.asyncio
    async def test_effect_node_inherits_correct_base(self, business_logic_generator):
        """Test EFFECT node inherits from NodeEffect"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)

        assert len(classes) > 0
        main_class = classes[0]

        # Verify NodeEffect is in bases
        assert (
            "NodeEffect" in main_class["bases"]
        ), "EFFECT node must inherit from NodeEffect"

    @pytest.mark.asyncio
    async def test_effect_node_method_signatures_from_contract(
        self, business_logic_generator
    ):
        """Test method signatures are generated from contract capabilities"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)
        main_class = classes[0]

        # Verify methods for each capability
        expected_methods = ["create_user", "get_user", "update_user", "delete_user"]
        for method_name in expected_methods:
            assert (
                method_name in main_class["methods"]
            ), f"Method {method_name} not generated from contract capability"


# ============================================================================
# COMPUTE NODE STUB GENERATION TESTS
# ============================================================================


class TestComputeNodeGeneration:
    """Tests for COMPUTE node business logic generation"""

    @pytest.mark.asyncio
    async def test_generate_compute_node_stub(self, business_logic_generator):
        """Test basic COMPUTE node stub generation"""
        result = await business_logic_generator.generate_node_stub(
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
            contract=SAMPLE_CONTRACT_WITH_TRANSFORMATION,
            analysis_result=COMPUTE_ANALYSIS_RESULT,
        )

        # Verify result structure
        assert result["node_type"] == "COMPUTE"
        assert result["class_name"].endswith("Compute")

        # Verify code is valid
        tree, errors = parse_generated_python(result["code"])
        assert tree is not None, f"Syntax errors: {errors}"

    @pytest.mark.asyncio
    async def test_compute_node_has_execute_method(self, business_logic_generator):
        """Test COMPUTE node has required execute_compute method"""
        result = await business_logic_generator.generate_node_stub(
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
            contract=SAMPLE_CONTRACT_WITH_TRANSFORMATION,
            analysis_result=COMPUTE_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)
        main_class = classes[0]

        assert (
            "execute_compute" in main_class["methods"]
        ), "execute_compute method not found in COMPUTE node"

    @pytest.mark.asyncio
    async def test_compute_node_is_pure(self, business_logic_generator):
        """Test COMPUTE node has no side effects (no external system calls)"""
        result = await business_logic_generator.generate_node_stub(
            node_type="COMPUTE",
            microservice_name="data_transformer",
            domain="data_processing",
            contract=SAMPLE_CONTRACT_WITH_TRANSFORMATION,
            analysis_result=COMPUTE_ANALYSIS_RESULT,
        )

        # Verify no external system imports
        code = result["code"]
        assert "requests" not in code, "COMPUTE node should not have HTTP calls"
        assert "psycopg2" not in code, "COMPUTE node should not have database calls"
        assert "kafka" not in code, "COMPUTE node should not have event bus calls"


# ============================================================================
# REDUCER NODE STUB GENERATION TESTS
# ============================================================================


class TestReducerNodeGeneration:
    """Tests for REDUCER node business logic generation"""

    @pytest.mark.asyncio
    async def test_generate_reducer_node_stub(self, business_logic_generator):
        """Test basic REDUCER node stub generation"""
        result = await business_logic_generator.generate_node_stub(
            node_type="REDUCER",
            microservice_name="analytics_aggregator",
            domain="analytics",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=REDUCER_ANALYSIS_RESULT,
        )

        assert result["node_type"] == "REDUCER"
        assert result["class_name"].endswith("Reducer")

        tree, errors = parse_generated_python(result["code"])
        assert tree is not None, f"Syntax errors: {errors}"

    @pytest.mark.asyncio
    async def test_reducer_node_has_execute_method(self, business_logic_generator):
        """Test REDUCER node has required execute_reduction method"""
        result = await business_logic_generator.generate_node_stub(
            node_type="REDUCER",
            microservice_name="analytics_aggregator",
            domain="analytics",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=REDUCER_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)
        main_class = classes[0]

        assert (
            "execute_reduction" in main_class["methods"]
        ), "execute_reduction method not found in REDUCER node"


# ============================================================================
# ORCHESTRATOR NODE STUB GENERATION TESTS
# ============================================================================


class TestOrchestratorNodeGeneration:
    """Tests for ORCHESTRATOR node business logic generation"""

    @pytest.mark.asyncio
    async def test_generate_orchestrator_node_stub(self, business_logic_generator):
        """Test basic ORCHESTRATOR node stub generation"""
        result = await business_logic_generator.generate_node_stub(
            node_type="ORCHESTRATOR",
            microservice_name="workflow_coordinator",
            domain="orchestration",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=ORCHESTRATOR_ANALYSIS_RESULT,
        )

        assert result["node_type"] == "ORCHESTRATOR"
        assert result["class_name"].endswith("Orchestrator")

        tree, errors = parse_generated_python(result["code"])
        assert tree is not None, f"Syntax errors: {errors}"

    @pytest.mark.asyncio
    async def test_orchestrator_node_has_execute_method(self, business_logic_generator):
        """Test ORCHESTRATOR node has required execute_orchestration method"""
        result = await business_logic_generator.generate_node_stub(
            node_type="ORCHESTRATOR",
            microservice_name="workflow_coordinator",
            domain="orchestration",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=ORCHESTRATOR_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)
        main_class = classes[0]

        assert (
            "execute_orchestration" in main_class["methods"]
        ), "execute_orchestration method not found in ORCHESTRATOR node"


# ============================================================================
# MIXIN INTEGRATION TESTS
# ============================================================================


class TestMixinIntegration:
    """Tests for mixin integration in generated code"""

    @pytest.mark.asyncio
    async def test_mixin_imports_generated(self, business_logic_generator):
        """Test that mixin imports are included"""
        contract_with_mixins = {
            **SAMPLE_CONTRACT_WITH_CRUD,
            "subcontracts": [
                {"mixin": "MixinEventBus", "config": {}},
                {"mixin": "MixinCaching", "config": {}},
                {"mixin": "MixinHealthCheck", "config": {}},
            ],
        }

        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_with_mixins,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        code = result["code"]
        assert "MixinEventBus" in code, "MixinEventBus not imported"
        assert "MixinCaching" in code, "MixinCaching not imported"
        assert "MixinHealthCheck" in code, "MixinHealthCheck not imported"

    @pytest.mark.asyncio
    async def test_mixin_inheritance(self, business_logic_generator):
        """Test that mixins are in class inheritance"""
        contract_with_mixins = {
            **SAMPLE_CONTRACT_WITH_CRUD,
            "subcontracts": [
                {"mixin": "MixinEventBus", "config": {}},
                {"mixin": "MixinCaching", "config": {}},
            ],
        }

        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=contract_with_mixins,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        classes = extract_class_definitions(tree)
        main_class = classes[0]

        assert "MixinEventBus" in main_class["bases"]
        assert "MixinCaching" in main_class["bases"]


# ============================================================================
# ERROR HANDLING PATTERN TESTS
# ============================================================================


class TestErrorHandlingPatterns:
    """Tests for error handling pattern generation"""

    @pytest.mark.asyncio
    async def test_methods_have_try_except(self, business_logic_generator):
        """Test that generated methods have try/except blocks"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        code = result["code"]
        # Verify try/except patterns exist
        assert "try:" in code, "No try blocks in generated code"
        assert "except" in code, "No except blocks in generated code"

    @pytest.mark.asyncio
    async def test_onex_error_used(self, business_logic_generator):
        """Test that OnexError is used for exception handling"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        code = result["code"]
        assert (
            "from omnibase_core.errors import OnexError" in code
        ), "OnexError not imported"
        assert "raise OnexError" in code, "OnexError not raised in exception handling"


# ============================================================================
# ONEX NAMING COMPLIANCE TESTS
# ============================================================================


class TestOnexNamingCompliance:
    """Tests for ONEX naming convention compliance"""

    @pytest.mark.parametrize(
        "node_type,suffix",
        [
            ("EFFECT", "Effect"),
            ("COMPUTE", "Compute"),
            ("REDUCER", "Reducer"),
            ("ORCHESTRATOR", "Orchestrator"),
        ],
    )
    @pytest.mark.asyncio
    async def test_class_name_suffix(self, business_logic_generator, node_type, suffix):
        """Test that class names have correct suffix"""
        result = await business_logic_generator.generate_node_stub(
            node_type=node_type,
            microservice_name="test_service",
            domain="test",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=NODE_TYPE_FIXTURES[node_type]["analysis"],
        )

        assert result["class_name"].endswith(
            suffix
        ), f"{node_type} node must end with {suffix}"

    @pytest.mark.asyncio
    async def test_file_name_convention(
        self, business_logic_generator, temp_output_dir
    ):
        """Test that generated file names follow ONEX conventions"""
        result = await business_logic_generator.generate_node_file(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
            output_directory=temp_output_dir,
        )

        file_path = Path(result["file_path"])
        file_name = file_path.name

        is_valid, error = validate_onex_naming(file_name)
        assert is_valid, f"File naming violation: {error}"


# ============================================================================
# TYPE HINT GENERATION TESTS
# ============================================================================


class TestTypeHintGeneration:
    """Tests for type hint generation"""

    @pytest.mark.asyncio
    async def test_methods_have_type_hints(self, business_logic_generator):
        """Test that all methods have proper type hints"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        tree, _ = parse_generated_python(result["code"])
        all_annotated, violations = check_type_annotations(tree)

        assert all_annotated, f"Type annotation violations: {violations}"

    @pytest.mark.asyncio
    async def test_no_bare_any_types(self, business_logic_generator):
        """Test that generated code doesn't use bare Any types"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="user_management",
            domain="identity",
            contract=SAMPLE_CONTRACT_WITH_CRUD,
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        code = result["code"]

        # Check for bare Any usage in type annotations (not in imports)
        import re

        # Match patterns like ": Any" or "-> Any" but not "Dict[str, Any]" or "List[Any]" or "import Any"
        bare_any_in_annotations = re.compile(r"(?::\s*|->\s*)Any(?!\[)")

        # Exclude import lines
        lines = code.split("\n")
        violations = []
        for i, line in enumerate(lines):
            # Skip import lines
            if "import" in line:
                continue

            matches = bare_any_in_annotations.findall(line)
            if matches:
                violations.append(f"Line {i+1}: {line.strip()}")

        if violations:
            pytest.fail(
                "Bare Any type found in type annotations:\n" + "\n".join(violations)
            )


# ============================================================================
# ERROR SCENARIO TESTS
# ============================================================================


class TestErrorScenarios:
    """Tests for error handling and validation"""

    @pytest.mark.asyncio
    async def test_invalid_node_type_raises_error(self, business_logic_generator):
        """Test that invalid node type raises OnexError"""
        with pytest.raises(OnexError) as exc_info:
            await business_logic_generator.generate_node_stub(
                node_type="INVALID_TYPE",
                microservice_name="test_service",
                domain="test",
                contract={},
                analysis_result=EFFECT_ANALYSIS_RESULT,
            )

        assert "Invalid node type" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_contract_generates_basic_stub(self, business_logic_generator):
        """Test that empty contract still generates valid stub"""
        result = await business_logic_generator.generate_node_stub(
            node_type="EFFECT",
            microservice_name="minimal_service",
            domain="test",
            contract={"capabilities": [], "subcontracts": []},
            analysis_result=EFFECT_ANALYSIS_RESULT,
        )

        # Should still generate valid code
        tree, errors = parse_generated_python(result["code"])
        assert tree is not None, f"Failed to generate from empty contract: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

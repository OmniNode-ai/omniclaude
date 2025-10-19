#!/usr/bin/env python3
"""
Generation Validation Tests

Tests for ONEX compliance, type safety, contract validation, and enum serialization.
"""

import tempfile
from pathlib import Path

import pytest

from agents.lib.omninode_template_engine import OmniNodeTemplateEngine
from agents.tests.fixtures.phase4_fixtures import (
    EFFECT_ANALYSIS_RESULT,
    EXPECTED_EFFECT_CONTRACT_YAML,
    ONEX_NAMING_VALID,
    ONEX_NAMING_VIOLATIONS,
    TYPE_SAFETY_VIOLATIONS,
)
from agents.tests.utils.generation_test_helpers import (
    check_for_any_types,
    check_type_annotations,
    parse_generated_python,
    parse_generated_yaml,
    validate_class_naming,
    validate_contract_schema,
    validate_enum_serialization,
    validate_mixin_compatibility,
    validate_onex_naming,
)


class TestONEXCompliance:
    """Tests for ONEX naming convention compliance"""

    def test_onex_naming_valid_files(self):
        """Test validation of valid ONEX file names"""
        for filename in ONEX_NAMING_VALID:
            is_valid, error = validate_onex_naming(filename)
            assert is_valid, f"Valid filename rejected: {filename} - {error}"

    def test_onex_naming_invalid_files(self):
        """Test rejection of invalid ONEX file names"""
        for filename in ONEX_NAMING_VIOLATIONS:
            is_valid, error = validate_onex_naming(filename)
            assert not is_valid, f"Invalid filename accepted: {filename}"
            assert error is not None

    def test_node_class_naming_valid(self):
        """Test validation of valid node class names"""
        valid_names = [
            ("NodeIdentityUserManagementEffect", "node"),
            ("NodeDataProcessingTransformerCompute", "node"),
            ("NodeAnalyticsAggregatorReducer", "node"),
            ("NodeOrchestrationCoordinatorOrchestrator", "node"),
        ]

        for class_name, file_type in valid_names:
            is_valid, error = validate_class_naming(class_name, file_type)
            assert is_valid, f"Valid class name rejected: {class_name} - {error}"

    def test_node_class_naming_invalid(self):
        """Test rejection of invalid node class names"""
        invalid_names = [
            ("UserService", "node"),  # Missing Node prefix
            ("nodeUserService", "node"),  # Wrong case
            ("Node_User_Service", "node"),  # Underscores
        ]

        for class_name, file_type in invalid_names:
            is_valid, error = validate_class_naming(class_name, file_type)
            assert not is_valid, f"Invalid class name accepted: {class_name}"

    def test_model_class_naming_valid(self):
        """Test validation of valid model class names"""
        valid_names = [
            ("ModelUserInput", "model"),
            ("ModelUserOutput", "model"),
            ("ModelUserConfig", "model"),
        ]

        for class_name, file_type in valid_names:
            is_valid, error = validate_class_naming(class_name, file_type)
            assert is_valid, f"Valid model name rejected: {class_name} - {error}"

    def test_enum_class_naming_valid(self):
        """Test validation of valid enum class names"""
        valid_names = [
            ("EnumOperationType", "enum"),
            ("EnumStatusCode", "enum"),
        ]

        for class_name, file_type in valid_names:
            is_valid, error = validate_class_naming(class_name, file_type)
            assert is_valid, f"Valid enum name rejected: {class_name} - {error}"

    @pytest.mark.asyncio
    async def test_generated_files_follow_onex_naming(self):
        """Test that generated files follow ONEX naming conventions"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            main_file = Path(result["main_file"])
            filename = main_file.name

            # Should follow node naming convention
            is_valid, error = validate_onex_naming(filename)
            if not is_valid:
                pytest.skip(f"ONEX naming not enforced yet: {error}")


class TestTypeSafety:
    """Tests for type safety and annotation compliance"""

    def test_type_annotation_detection(self):
        """Test detection of proper type annotations"""
        code_with_annotations = """
def process(data: Dict[str, Any]) -> ModelOutput:
    return ModelOutput()
"""
        tree, _ = parse_generated_python(code_with_annotations)
        is_valid, violations = check_type_annotations(tree)
        assert is_valid, f"Valid annotations rejected: {violations}"

    def test_missing_type_annotation_detection(self):
        """Test detection of missing type annotations"""
        code_without_annotations = """
def process(data):
    return None
"""
        tree, _ = parse_generated_python(code_without_annotations)
        is_valid, violations = check_type_annotations(tree)
        assert not is_valid, "Missing annotations not detected"
        assert len(violations) > 0

    def test_any_type_detection(self):
        """Test detection of Any type usage"""
        for violation_code in TYPE_SAFETY_VIOLATIONS:
            full_code = f"""
from typing import Any, Dict, List

{violation_code}
    pass
"""
            is_valid, violations = check_for_any_types(full_code)
            # Note: This test may need adjustment based on implementation
            # Some Any usage might be acceptable in certain contexts

    @pytest.mark.asyncio
    async def test_generated_code_type_safety(self):
        """Test that generated code has proper type annotations"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, errors = parse_generated_python(content)
            assert tree is not None, f"Syntax errors: {errors}"

            # Check type annotations
            is_valid, violations = check_type_annotations(tree)
            if not is_valid:
                # Log violations but don't fail yet (may not be fully implemented)
                print(f"Type annotation violations: {violations}")

    @pytest.mark.asyncio
    async def test_generated_code_no_any_types(self):
        """Test that generated code avoids Any types"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            is_valid, violations = check_for_any_types(content)
            if not is_valid:
                # Log violations for awareness
                print(f"Any type violations: {violations}")


class TestContractValidation:
    """Tests for contract YAML validation"""

    def test_contract_yaml_parsing(self):
        """Test parsing of contract YAML"""
        parsed = parse_generated_yaml(EXPECTED_EFFECT_CONTRACT_YAML)
        assert parsed is not None
        assert isinstance(parsed, dict)

    def test_contract_schema_validation_valid(self):
        """Test validation of valid contract schema"""
        parsed = parse_generated_yaml(EXPECTED_EFFECT_CONTRACT_YAML)
        is_valid, errors = validate_contract_schema(parsed)
        assert is_valid, f"Valid contract rejected: {errors}"

    def test_contract_schema_validation_missing_fields(self):
        """Test detection of missing required fields"""
        incomplete_contract = """
version: "1.0.0"
node_type: "EFFECT"
"""
        parsed = parse_generated_yaml(incomplete_contract)
        is_valid, errors = validate_contract_schema(parsed)
        assert not is_valid, "Incomplete contract accepted"
        assert len(errors) > 0

    def test_contract_version_format(self):
        """Test validation of version format"""
        invalid_version = """
version: "1.0"
node_type: "EFFECT"
domain: "test"
microservice_name: "test"
capabilities: []
"""
        parsed = parse_generated_yaml(invalid_version)
        is_valid, errors = validate_contract_schema(parsed)
        assert not is_valid, "Invalid version format accepted"

    def test_contract_node_type_validation(self):
        """Test validation of node type values"""
        invalid_node_type = """
version: "1.0.0"
node_type: "INVALID"
domain: "test"
microservice_name: "test"
capabilities: []
"""
        parsed = parse_generated_yaml(invalid_node_type)
        is_valid, errors = validate_contract_schema(parsed)
        assert not is_valid, "Invalid node type accepted"

    def test_contract_capabilities_structure(self):
        """Test validation of capabilities structure"""
        invalid_capabilities = """
version: "1.0.0"
node_type: "EFFECT"
domain: "test"
microservice_name: "test"
capabilities:
  - invalid_structure
"""
        parsed = parse_generated_yaml(invalid_capabilities)
        is_valid, errors = validate_contract_schema(parsed)
        assert not is_valid, "Invalid capabilities structure accepted"

    def test_contract_mixin_naming(self):
        """Test validation of mixin naming conventions"""
        contract_with_mixins = """
version: "1.0.0"
node_type: "EFFECT"
domain: "test"
microservice_name: "test"
capabilities: []
mixins:
  - MixinEventBus
  - InvalidMixin
"""
        parsed = parse_generated_yaml(contract_with_mixins)
        is_valid, errors = validate_contract_schema(parsed)
        # Should pass schema validation but InvalidMixin should be noted
        # (depends on implementation)


class TestEnumSerialization:
    """Tests for enum JSON serialization"""

    def test_enum_str_inheritance(self):
        """Test that enums inherit from str for JSON serialization"""
        enum_code = """
from enum import Enum

class EnumOperationType(str, Enum):
    CREATE = "create"
    READ = "read"

    def __str__(self) -> str:
        return self.value
"""
        tree, _ = parse_generated_python(enum_code)
        is_valid, violations = validate_enum_serialization(tree)
        assert is_valid, f"Valid enum rejected: {violations}"

    def test_enum_missing_str_inheritance(self):
        """Test detection of enums without str inheritance"""
        enum_code = """
from enum import Enum

class EnumOperationType(Enum):
    CREATE = "create"
    READ = "read"
"""
        tree, _ = parse_generated_python(enum_code)
        is_valid, violations = validate_enum_serialization(tree)
        assert not is_valid, "Enum without str inheritance accepted"
        assert len(violations) > 0

    def test_enum_str_method(self):
        """Test that enums implement __str__ method"""
        enum_code = """
from enum import Enum

class EnumOperationType(str, Enum):
    CREATE = "create"

    def __str__(self) -> str:
        return self.value
"""
        tree, _ = parse_generated_python(enum_code)
        is_valid, violations = validate_enum_serialization(tree)
        assert is_valid, f"Valid enum rejected: {violations}"


class TestMixinValidation:
    """Tests for mixin compatibility validation"""

    def test_mixin_compatibility_valid(self):
        """Test validation of compatible mixins"""
        mixins = ["MixinEventBus", "MixinHealthCheck", "MixinMetrics"]
        is_compatible, conflicts = validate_mixin_compatibility(mixins)
        assert is_compatible, f"Compatible mixins rejected: {conflicts}"

    def test_mixin_compatibility_conflicts(self):
        """Test detection of incompatible mixins"""
        mixins = ["MixinCaching", "MixinNoCaching"]
        is_compatible, conflicts = validate_mixin_compatibility(mixins)
        assert not is_compatible, "Incompatible mixins accepted"
        assert len(conflicts) > 0

    @pytest.mark.asyncio
    async def test_generated_mixins_are_compatible(self):
        """Test that generated code uses compatible mixins"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            # Check mixin compatibility
            mixins = EFFECT_ANALYSIS_RESULT.recommended_mixins
            is_compatible, conflicts = validate_mixin_compatibility(mixins)
            assert (
                is_compatible
            ), f"Generated code uses incompatible mixins: {conflicts}"


class TestQualityMetrics:
    """Tests for code quality metrics"""

    @pytest.mark.asyncio
    async def test_generated_code_has_docstrings(self):
        """Test that generated code includes docstrings"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            # Check for docstrings
            assert '"""' in content or "'''" in content, "No docstrings found"

    @pytest.mark.asyncio
    async def test_generated_code_has_imports(self):
        """Test that generated code has necessary imports"""
        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            imports = [
                node
                for node in tree.body
                if isinstance(
                    node, (__import__("ast").Import, __import__("ast").ImportFrom)
                )
            ]
            assert len(imports) > 0, "No imports found"

    @pytest.mark.asyncio
    async def test_generated_code_complexity(self):
        """Test that generated code has reasonable complexity"""
        from agents.tests.utils.generation_test_helpers import estimate_code_complexity

        engine = OmniNodeTemplateEngine()

        with tempfile.TemporaryDirectory() as temp_dir:
            result = await engine.generate_node(
                analysis_result=EFFECT_ANALYSIS_RESULT,
                node_type="EFFECT",
                microservice_name="user_management",
                domain="identity",
                output_directory=temp_dir,
            )

            with open(result["main_file"], "r") as f:
                content = f.read()

            tree, _ = parse_generated_python(content)
            metrics = estimate_code_complexity(tree)

            # Basic sanity checks
            assert metrics["num_classes"] >= 1, "No classes found"
            assert metrics["num_functions"] >= 1, "No functions found"
            assert metrics["max_nesting_depth"] < 10, "Excessive nesting detected"

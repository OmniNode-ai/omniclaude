"""
Integration tests for generation utilities.

Tests the 5 core utilities working together:
- TypeMapper
- EnumGenerator
- ReferenceResolver
- ASTBuilder
- ContractAnalyzer
"""

import ast

import pytest
import yaml

from agents.lib.generation import (
    ASTBuilder,
    ContractAnalyzer,
    EnumGenerator,
    ReferenceResolver,
    TypeMapper,
)


class TestTypeMapper:
    """Tests for TypeMapper utility."""

    def test_basic_type_mapping(self):
        """Test basic type mappings."""
        mapper = TypeMapper()

        # Basic types
        assert mapper.get_type_string_from_schema({"type": "string"}) == "str"
        assert mapper.get_type_string_from_schema({"type": "integer"}) == "int"
        assert mapper.get_type_string_from_schema({"type": "number"}) == "float"
        assert mapper.get_type_string_from_schema({"type": "boolean"}) == "bool"

    def test_format_based_mapping(self):
        """Test format-based type mappings."""
        mapper = TypeMapper()

        assert (
            mapper.get_type_string_from_schema({"type": "string", "format": "uuid"})
            == "UUID"
        )
        assert (
            mapper.get_type_string_from_schema(
                {"type": "string", "format": "date-time"}
            )
            == "datetime"
        )
        assert (
            mapper.get_type_string_from_schema({"type": "string", "format": "date"})
            == "date"
        )

    def test_array_type_mapping(self):
        """Test array type mappings."""
        mapper = TypeMapper()

        result = mapper.get_type_string_from_schema(
            {"type": "array", "items": {"type": "string"}}
        )
        assert result == "List[str]"

    def test_enum_name_generation(self):
        """Test enum name generation."""
        mapper = TypeMapper()

        # Single word
        assert mapper.generate_enum_name_from_values(["active"]) == "EnumActive"

        # Snake case
        assert (
            mapper.generate_enum_name_from_values(["processing_mode"])
            == "EnumProcessingMode"
        )

        # Hyphenated
        assert (
            mapper.generate_enum_name_from_values(["multi-word-value"])
            == "EnumMultiWordValue"
        )

    def test_reference_resolution(self):
        """Test reference resolution."""
        mapper = TypeMapper()

        # Internal reference
        result = mapper.get_type_string_from_schema({"$ref": "#/definitions/User"})
        assert result == "ModelUser"


class TestEnumGenerator:
    """Tests for EnumGenerator utility."""

    def test_discover_enums_from_contract(self):
        """Test enum discovery from contract."""
        generator = EnumGenerator()

        contract = {
            "definitions": {
                "StatusConfig": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "inactive", "pending"],
                        }
                    },
                }
            }
        }

        enums = generator.discover_enums_from_contract(contract)
        assert len(enums) == 1
        assert enums[0].name == "EnumActive"
        assert enums[0].values == ["active", "inactive", "pending"]

    def test_generate_enum_class(self):
        """Test enum class AST generation."""
        generator = EnumGenerator()

        enum_ast = generator.generate_enum_class("EnumStatus", ["active", "inactive"])

        assert isinstance(enum_ast, ast.ClassDef)
        assert enum_ast.name == "EnumStatus"

        # Render to code
        code = ast.unparse(enum_ast)
        assert "class EnumStatus(str, Enum):" in code
        assert "ACTIVE = 'active'" in code
        assert "INACTIVE = 'inactive'" in code

    def test_enum_name_validation(self):
        """Test enum name must start with Enum."""
        generator = EnumGenerator()

        with pytest.raises(ValueError, match="must start with 'Enum'"):
            generator.generate_enum_class("Status", ["active"])


class TestReferenceResolver:
    """Tests for ReferenceResolver utility."""

    def test_internal_reference_resolution(self):
        """Test internal reference resolution."""
        resolver = ReferenceResolver()

        result = resolver.resolve_ref("#/definitions/User")
        assert result == "ModelUser"

    def test_external_reference_resolution(self):
        """Test external reference resolution."""
        resolver = ReferenceResolver()

        result = resolver.resolve_ref("contracts/models.yaml#/Config")
        assert result == "ModelConfig"

    def test_model_prefix_enforcement(self):
        """Test Model prefix is enforced."""
        resolver = ReferenceResolver()

        # Already has prefix
        assert resolver.resolve_ref("#/definitions/ModelUser") == "ModelUser"

        # Needs prefix
        assert resolver.resolve_ref("#/definitions/User") == "ModelUser"


class TestASTBuilder:
    """Tests for ASTBuilder utility."""

    def test_generate_model_class(self):
        """Test Pydantic model generation."""
        builder = ASTBuilder()

        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name"],
        }

        model_ast = builder.generate_model_class("ModelUser", schema)

        assert isinstance(model_ast, ast.ClassDef)
        assert model_ast.name == "ModelUser"

        # Render to code
        code = ast.unparse(model_ast)
        assert "class ModelUser(BaseModel):" in code
        assert "name:" in code
        assert "age:" in code

    def test_field_with_constraints(self):
        """Test field generation with constraints."""
        builder = ASTBuilder()

        schema = {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Count value",
                }
            },
            "required": ["count"],
        }

        model_ast = builder.generate_model_class("ModelCounter", schema)
        code = ast.unparse(model_ast)

        assert "ge=0" in code
        assert "le=100" in code
        assert "description=" in code

    def test_generate_import_statement(self):
        """Test import statement generation."""
        builder = ASTBuilder()

        import_ast = builder.generate_import_statement("typing", ["List", "Dict"])

        assert isinstance(import_ast, ast.ImportFrom)
        code = ast.unparse(import_ast)
        assert "from typing import List, Dict" in code


class TestContractAnalyzer:
    """Tests for ContractAnalyzer utility."""

    @pytest.fixture
    def sample_contract(self, tmp_path):
        """Create a sample contract file."""
        contract = {
            "name": "test_service",
            "version": "1.0.0",
            "input_state": {
                "type": "object",
                "properties": {"input_field": {"type": "string"}},
                "required": ["input_field"],
            },
            "output_state": {
                "type": "object",
                "properties": {"output_field": {"type": "string"}},
            },
            "definitions": {
                "Config": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean"}},
                }
            },
        }

        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.dump(contract))
        return contract_path

    def test_load_contract(self, sample_contract):
        """Test contract loading."""
        analyzer = ContractAnalyzer()

        contract = analyzer.load_contract(sample_contract)

        assert contract["name"] == "test_service"
        assert contract["version"] == "1.0.0"
        assert "input_state" in contract
        assert "output_state" in contract
        assert "definitions" in contract

    def test_validate_contract(self):
        """Test contract validation."""
        analyzer = ContractAnalyzer()

        # Valid contract
        valid_contract = {
            "name": "test",
            "version": "1.0.0",
            "input_state": {"type": "object"},
        }

        result = analyzer.validate_contract(valid_contract)
        assert result.is_valid

        # Invalid contract (missing name)
        invalid_contract = {"version": "1.0.0"}

        result = analyzer.validate_contract(invalid_contract)
        assert not result.is_valid
        assert any("name" in error for error in result.errors)

    def test_analyze_contract(self, sample_contract):
        """Test contract analysis."""
        analyzer = ContractAnalyzer()

        contract = analyzer.load_contract(sample_contract)
        info = analyzer.analyze_contract(contract)

        assert info.node_name == "test_service"
        assert info.node_version == "1.0.0"
        assert info.has_input_state
        assert info.has_output_state
        assert info.has_definitions
        assert info.definition_count == 1
        assert info.field_count > 0


class TestIntegration:
    """Integration tests for all utilities working together."""

    def test_full_generation_pipeline(self, tmp_path):
        """Test complete generation pipeline with all utilities."""
        # 1. Create a contract
        contract = {
            "name": "effect_processor",
            "version": "1.0.0",
            "input_state": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "update", "delete"],
                    },
                    "data": {"type": "string"},
                },
                "required": ["action", "data"],
            },
            "definitions": {
                "Config": {
                    "type": "object",
                    "properties": {"timeout": {"type": "integer", "minimum": 0}},
                }
            },
        }

        contract_path = tmp_path / "contract.yaml"
        contract_path.write_text(yaml.dump(contract))

        # 2. Load contract
        analyzer = ContractAnalyzer()
        loaded_contract = analyzer.load_contract(contract_path)

        # 3. Discover enums
        enum_gen = EnumGenerator()
        enums = enum_gen.discover_enums_from_contract(loaded_contract)
        assert len(enums) > 0

        # 4. Build AST for input state
        builder = ASTBuilder(type_mapper=TypeMapper())
        model_ast = builder.generate_model_class(
            "ModelEffectInput", loaded_contract["input_state"]
        )

        # 5. Generate code
        code = builder.unparse_node(model_ast)

        # Verify generated code
        assert "class ModelEffectInput(BaseModel):" in code
        assert "action:" in code
        assert "data:" in code

        # 6. Verify code compiles
        compile(code, "<string>", "exec")

    def test_utilities_with_dependencies(self):
        """Test utilities with dependency injection."""
        # Create type mapper
        type_mapper = TypeMapper()

        # Create reference resolver
        ref_resolver = ReferenceResolver()

        # Create AST builder with dependencies
        ast_builder = ASTBuilder(
            type_mapper=type_mapper, reference_resolver=ref_resolver
        )

        # Create enum generator with type mapper
        enum_gen = EnumGenerator(type_mapper=type_mapper)

        # Create contract analyzer with dependencies
        analyzer = ContractAnalyzer(
            reference_resolver=ref_resolver, enum_generator=enum_gen
        )

        # Verify all components initialized
        assert ast_builder.type_mapper is type_mapper
        assert ast_builder.reference_resolver is ref_resolver
        assert enum_gen.type_mapper is type_mapper
        assert analyzer.reference_resolver is ref_resolver

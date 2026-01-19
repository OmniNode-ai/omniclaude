#!/usr/bin/env python3
"""
Comprehensive validation tests for CRUD Pattern implementations.

Tests the CRUDPattern class including:
- Pattern matching with various CRUD keywords
- Code generation for create, read, update, delete operations
- Error handling and edge cases
- Required imports and mixins
- Method name sanitization
- Entity name extraction
"""

import pytest

from agents.lib.patterns.crud_pattern import CRUDPattern

# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def crud_pattern():
    """Create a CRUDPattern instance"""
    return CRUDPattern()


@pytest.fixture
def create_capability():
    """Sample create capability"""
    return {
        "name": "create_user",
        "description": "Create a new user record in the database",
        "type": "create",
        "required": True,
    }


@pytest.fixture
def read_capability():
    """Sample read capability"""
    return {
        "name": "get_user",
        "description": "Fetch user record from database",
        "type": "read",
        "required": True,
    }


@pytest.fixture
def update_capability():
    """Sample update capability"""
    return {
        "name": "update_user",
        "description": "Modify existing user record",
        "type": "update",
        "required": True,
    }


@pytest.fixture
def delete_capability():
    """Sample delete capability"""
    return {
        "name": "delete_user",
        "description": "Remove user record from database",
        "type": "delete",
        "required": True,
    }


# ============================================================================
# PATTERN MATCHING TESTS
# ============================================================================


class TestCRUDPatternMatching:
    """Tests for CRUD pattern matching logic"""

    def test_matches_create_keyword(self, crud_pattern):
        """Test matching with 'create' keyword"""
        capability = {"name": "create_record", "description": "Creates a new record"}
        confidence = crud_pattern.matches(capability)
        assert confidence > 0.0, "Should match 'create' keyword"
        assert (
            confidence >= 0.33
        ), "Single create keyword should have reasonable confidence"

    def test_matches_read_keywords(self, crud_pattern):
        """Test matching with read keywords"""
        capability = {"name": "get_user", "description": "Read user data"}
        confidence = crud_pattern.matches(capability)
        assert confidence > 0.0, "Should match read keywords"

    def test_matches_update_keywords(self, crud_pattern):
        """Test matching with update keywords"""
        capability = {"name": "update_record", "description": "Modify existing record"}
        confidence = crud_pattern.matches(capability)
        assert confidence > 0.0, "Should match update keywords"

    def test_matches_delete_keywords(self, crud_pattern):
        """Test matching with delete keywords"""
        capability = {"name": "delete_item", "description": "Remove item from storage"}
        confidence = crud_pattern.matches(capability)
        assert confidence > 0.0, "Should match delete keywords"

    def test_matches_multiple_crud_keywords(self, crud_pattern):
        """Test high confidence with multiple CRUD keywords"""
        capability = {
            "name": "manage_users",
            "description": "Create, read, update, and delete user records",
        }
        confidence = crud_pattern.matches(capability)
        assert confidence >= 1.0, "Multiple CRUD keywords should give max confidence"

    def test_matches_case_insensitive(self, crud_pattern):
        """Test matching is case-insensitive"""
        capability = {"name": "CREATE_USER", "description": "CREATE NEW USER"}
        confidence = crud_pattern.matches(capability)
        assert confidence > 0.0, "Matching should be case-insensitive"

    def test_no_match_non_crud_capability(self, crud_pattern):
        """Test no match for non-CRUD capability"""
        capability = {
            "name": "calculate_total",
            "description": "Calculate sum of values",
        }
        confidence = crud_pattern.matches(capability)
        assert confidence == 0.0, "Should not match non-CRUD operations"

    def test_matches_alternative_keywords(self, crud_pattern):
        """Test matching with alternative CRUD keywords"""
        capabilities = [
            {"name": "insert_record", "description": "Insert new data"},
            {"name": "fetch_data", "description": "Fetch from database"},
            {"name": "modify_entry", "description": "Modify existing entry"},
            {"name": "remove_item", "description": "Remove from storage"},
        ]

        for cap in capabilities:
            confidence = crud_pattern.matches(cap)
            assert confidence > 0.0, f"Should match alternative keyword: {cap['name']}"

    def test_confidence_score_range(self, crud_pattern, create_capability):
        """Test confidence scores are within valid range"""
        confidence = crud_pattern.matches(create_capability)
        assert 0.0 <= confidence <= 1.0, "Confidence must be between 0.0 and 1.0"

    def test_empty_capability(self, crud_pattern):
        """Test handling of empty capability"""
        capability = {}
        confidence = crud_pattern.matches(capability)
        assert confidence == 0.0, "Empty capability should have zero confidence"


# ============================================================================
# CODE GENERATION TESTS - CREATE
# ============================================================================


class TestCRUDCreateGeneration:
    """Tests for CREATE operation code generation"""

    def test_generate_create_method(self, crud_pattern, create_capability):
        """Test generating CREATE method code"""
        context = {"operation": "create", "has_event_bus": False}
        code = crud_pattern.generate(create_capability, context)

        assert "async def create_user" in code
        assert "input_data: Dict[str, Any]" in code
        assert "OnexError" in code
        assert "transaction_manager" in code
        assert "db.insert" in code

    def test_create_with_event_bus(self, crud_pattern, create_capability):
        """Test CREATE method includes event publishing when EventBus available"""
        context = {"operation": "create", "has_event_bus": True}
        code = crud_pattern.generate(create_capability, context)

        assert "publish_event" in code
        assert ".created" in code

    def test_create_includes_validation(self, crud_pattern, create_capability):
        """Test CREATE method includes input validation"""
        context = {"operation": "create", "has_event_bus": False}
        code = crud_pattern.generate(create_capability, context)

        assert "validate_input" in code or "VALIDATION_ERROR" in code
        assert "required_fields" in code

    def test_create_includes_error_handling(self, crud_pattern, create_capability):
        """Test CREATE method includes proper error handling"""
        context = {"operation": "create", "has_event_bus": False}
        code = crud_pattern.generate(create_capability, context)

        assert "try:" in code
        assert "except OnexError:" in code
        assert "except Exception as e:" in code
        assert "OPERATION_FAILED" in code

    def test_create_includes_logging(self, crud_pattern, create_capability):
        """Test CREATE method includes logging statements"""
        context = {"operation": "create", "has_event_bus": False}
        code = crud_pattern.generate(create_capability, context)

        assert "self.logger.info" in code
        assert "self.logger.error" in code

    def test_create_returns_success_response(self, crud_pattern, create_capability):
        """Test CREATE method returns proper success response"""
        context = {"operation": "create", "has_event_bus": False}
        code = crud_pattern.generate(create_capability, context)

        assert '"success": True' in code
        assert '"entity_id"' in code
        assert '"message"' in code


# ============================================================================
# CODE GENERATION TESTS - READ
# ============================================================================


class TestCRUDReadGeneration:
    """Tests for READ operation code generation"""

    def test_generate_read_method(self, crud_pattern, read_capability):
        """Test generating READ method code"""
        context = {"operation": "read"}
        code = crud_pattern.generate(read_capability, context)

        assert "async def get_user" in code
        assert "entity_id: str" in code
        assert "db.query_one" in code

    def test_read_includes_not_found_handling(self, crud_pattern, read_capability):
        """Test READ method handles entity not found"""
        context = {"operation": "read"}
        code = crud_pattern.generate(read_capability, context)

        assert "NOT_FOUND" in code
        assert "if not result:" in code

    def test_read_includes_query_logic(self, crud_pattern, read_capability):
        """Test READ method includes database query"""
        context = {"operation": "read"}
        code = crud_pattern.generate(read_capability, context)

        assert "SELECT * FROM" in code
        assert "WHERE id = $1" in code


# ============================================================================
# CODE GENERATION TESTS - UPDATE
# ============================================================================


class TestCRUDUpdateGeneration:
    """Tests for UPDATE operation code generation"""

    def test_generate_update_method(self, crud_pattern, update_capability):
        """Test generating UPDATE method code"""
        context = {"operation": "update", "has_event_bus": False}
        code = crud_pattern.generate(update_capability, context)

        assert "async def update_user" in code
        assert "entity_id: str" in code
        assert "update_data: Dict[str, Any]" in code
        assert "db.update" in code

    def test_update_checks_entity_exists(self, crud_pattern, update_capability):
        """Test UPDATE method checks entity exists before updating"""
        context = {"operation": "update", "has_event_bus": False}
        code = crud_pattern.generate(update_capability, context)

        assert "query_one" in code
        assert "NOT_FOUND" in code

    def test_update_with_event_bus(self, crud_pattern, update_capability):
        """Test UPDATE method includes event publishing"""
        context = {"operation": "update", "has_event_bus": True}
        code = crud_pattern.generate(update_capability, context)

        assert "publish_event" in code
        assert ".updated" in code

    def test_update_uses_transaction(self, crud_pattern, update_capability):
        """Test UPDATE method uses transaction"""
        context = {"operation": "update", "has_event_bus": False}
        code = crud_pattern.generate(update_capability, context)

        assert "transaction_manager.begin()" in code


# ============================================================================
# CODE GENERATION TESTS - DELETE
# ============================================================================


class TestCRUDDeleteGeneration:
    """Tests for DELETE operation code generation"""

    def test_generate_delete_method(self, crud_pattern, delete_capability):
        """Test generating DELETE method code"""
        context = {"operation": "delete", "has_event_bus": False}
        code = crud_pattern.generate(delete_capability, context)

        assert "async def delete_user" in code
        assert "entity_id: str" in code
        assert "db.delete" in code

    def test_delete_checks_entity_exists(self, crud_pattern, delete_capability):
        """Test DELETE method checks entity exists"""
        context = {"operation": "delete", "has_event_bus": False}
        code = crud_pattern.generate(delete_capability, context)

        assert "query_one" in code
        assert "NOT_FOUND" in code

    def test_delete_with_event_bus(self, crud_pattern, delete_capability):
        """Test DELETE method includes event publishing"""
        context = {"operation": "delete", "has_event_bus": True}
        code = crud_pattern.generate(delete_capability, context)

        assert "publish_event" in code
        assert ".deleted" in code


# ============================================================================
# REQUIRED IMPORTS AND MIXINS TESTS
# ============================================================================


class TestCRUDRequirements:
    """Tests for required imports and mixins"""

    def test_get_required_imports(self, crud_pattern):
        """Test getting required imports for CRUD pattern"""
        imports = crud_pattern.get_required_imports()

        assert len(imports) > 0
        assert any("Dict" in imp for imp in imports)
        assert any("UUID" in imp for imp in imports)
        assert any("OnexError" in imp for imp in imports)

    def test_get_required_mixins(self, crud_pattern):
        """Test getting required mixins for CRUD pattern"""
        mixins = crud_pattern.get_required_mixins()

        assert len(mixins) > 0
        assert "MixinDatabase" in mixins
        assert "MixinValidation" in mixins

    def test_required_imports_are_strings(self, crud_pattern):
        """Test imports are returned as strings"""
        imports = crud_pattern.get_required_imports()
        assert all(isinstance(imp, str) for imp in imports)

    def test_required_mixins_are_strings(self, crud_pattern):
        """Test mixins are returned as strings"""
        mixins = crud_pattern.get_required_mixins()
        assert all(isinstance(mixin, str) for mixin in mixins)


# ============================================================================
# UTILITY METHOD TESTS
# ============================================================================


class TestCRUDUtilities:
    """Tests for utility methods"""

    def test_sanitize_method_name(self, crud_pattern):
        """Test method name sanitization"""
        test_cases = [
            ("create_user", "create_user"),
            ("Create-User", "create_user"),
            ("create user", "create_user"),
            ("create@user!", "createuser"),
            ("", "execute_operation"),
        ]

        for input_name, expected in test_cases:
            result = crud_pattern._sanitize_method_name(input_name)
            assert result == expected, f"Failed for input: {input_name}"

    def test_extract_entity_name_from_create(self, crud_pattern):
        """Test extracting entity name from create operation"""
        capability = {"name": "create_user", "description": "Create user"}
        context = {}
        entity_name = crud_pattern._extract_entity_name(capability, context)
        assert entity_name == "User" or "user" in entity_name.lower()

    def test_extract_entity_name_from_read(self, crud_pattern):
        """Test extracting entity name from read operation"""
        capability = {"name": "get_product", "description": "Get product"}
        context = {}
        entity_name = crud_pattern._extract_entity_name(capability, context)
        assert entity_name == "Product" or "product" in entity_name.lower()

    def test_extract_entity_name_default(self, crud_pattern):
        """Test default entity name when extraction fails"""
        capability = {"name": "", "description": ""}
        context = {}
        entity_name = crud_pattern._extract_entity_name(capability, context)
        assert entity_name == "Entity"


# ============================================================================
# EDGE CASE TESTS
# ============================================================================


class TestCRUDEdgeCases:
    """Tests for edge cases and error conditions"""

    def test_generate_with_empty_capability(self, crud_pattern):
        """Test generation with empty capability"""
        capability = {}
        context = {"operation": "create"}
        code = crud_pattern.generate(capability, context)
        assert "async def" in code

    def test_generate_with_missing_operation(self, crud_pattern, create_capability):
        """Test generation with missing operation in context"""
        context = {}
        code = crud_pattern.generate(create_capability, context)
        assert "async def" in code

    def test_generate_generic_crud_method(self, crud_pattern):
        """Test generation of generic CRUD method"""
        capability = {"name": "save_data", "description": "Save data"}
        context = {"operation": "unknown"}
        code = crud_pattern.generate(capability, context)

        assert "async def save_data" in code
        assert "TODO" in code

    def test_capability_with_special_characters(self, crud_pattern):
        """Test handling capability with special characters"""
        capability = {
            "name": "create-user@2024!",
            "description": "Create user <test>",
        }
        context = {"operation": "create"}
        code = crud_pattern.generate(capability, context)
        assert "async def" in code

    def test_very_long_capability_name(self, crud_pattern):
        """Test handling very long capability name"""
        capability = {
            "name": "create_user_with_very_long_name_that_exceeds_normal_length",
            "description": "Create user",
        }
        context = {"operation": "create"}
        code = crud_pattern.generate(capability, context)
        assert "async def" in code


# ============================================================================
# INTEGRATION TESTS
# ============================================================================


class TestCRUDIntegration:
    """Integration tests combining multiple features"""

    def test_full_crud_workflow(self, crud_pattern):
        """Test generating all CRUD operations for same entity"""
        operations = ["create", "read", "update", "delete"]
        entity = "user"

        for operation in operations:
            capability = {
                "name": f"{operation}_{entity}",
                "description": f"{operation.capitalize()} {entity} record",
            }
            context = {"operation": operation, "has_event_bus": True}

            code = crud_pattern.generate(capability, context)
            assert "async def" in code
            assert entity in code.lower()

    def test_code_generation_consistency(self, crud_pattern):
        """Test code generation is consistent across multiple calls"""
        capability = {"name": "create_user", "description": "Create user"}
        context = {"operation": "create", "has_event_bus": False}

        code1 = crud_pattern.generate(capability, context)
        code2 = crud_pattern.generate(capability, context)

        assert code1 == code2, "Code generation should be deterministic"

    def test_all_operations_include_error_handling(self, crud_pattern):
        """Test all operations include proper error handling"""
        operations = ["create", "read", "update", "delete"]

        for operation in operations:
            capability = {"name": f"{operation}_item", "description": f"{operation}"}
            context = {"operation": operation}

            code = crud_pattern.generate(capability, context)
            assert "try:" in code
            assert "except" in code
            assert "OnexError" in code


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

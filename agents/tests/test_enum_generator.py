#!/usr/bin/env python3
"""
Test Enum Generator

Comprehensive tests for Phase 4 enum generation.
"""

import pytest
import json
from uuid import uuid4
from datetime import datetime

from agents.lib.enum_generator import EnumGenerator, EnumValue, GeneratedEnum
from agents.lib.simple_prd_analyzer import SimplePRDAnalysisResult, SimpleParsedPRD, SimpleDecompositionResult
from omnibase_core.errors import OnexError


class TestEnumValue:
    """Test EnumValue dataclass"""

    def test_enum_value_creation(self):
        """Test creating EnumValue"""
        value = EnumValue(name="CREATE", value="create", description="Create operation")

        assert value.name == "CREATE"
        assert value.value == "create"
        assert value.description == "Create operation"

    def test_enum_value_equality(self):
        """Test EnumValue equality by name"""
        value1 = EnumValue("CREATE", "create")
        value2 = EnumValue("CREATE", "create")
        value3 = EnumValue("UPDATE", "update")

        assert value1 == value2
        assert value1 != value3

    def test_enum_value_hashable(self):
        """Test EnumValue can be used in sets"""
        value1 = EnumValue("CREATE", "create")
        value2 = EnumValue("CREATE", "create")
        value3 = EnumValue("UPDATE", "update")

        value_set = {value1, value2, value3}
        assert len(value_set) == 2  # value1 and value2 are duplicates


class TestEnumGenerator:
    """Test EnumGenerator class"""

    @pytest.fixture
    def generator(self):
        """Create EnumGenerator instance"""
        return EnumGenerator()

    @pytest.fixture
    def sample_prd_analysis(self):
        """Create sample PRD analysis for testing"""
        parsed_prd = SimpleParsedPRD(
            title="User Management Service",
            description="Service for managing user accounts and authentication",
            functional_requirements=[
                "Create new user accounts",
                "Update existing user profiles",
                "Delete inactive users",
                "Search users by email or username",
                "Validate user credentials",
                "List all active users",
            ],
            features=[
                "User registration with email verification",
                "Profile management",
                "Account deactivation",
                "User search and filtering",
            ],
            success_criteria=["99.9% uptime", "Sub-second response times"],
            technical_details=[
                "PostgreSQL for user storage",
                "Redis for session caching",
                "Event-driven architecture with Kafka",
            ],
            dependencies=["Authentication service", "Email notification service"],
            extracted_keywords=["user", "account", "authentication"],
            sections=["overview", "requirements", "features"],
            word_count=250,
        )

        decomposition_result = SimpleDecompositionResult(
            tasks=[
                {
                    "id": "task_1",
                    "title": "Create user registration endpoint",
                    "description": "Implement user creation logic",
                    "priority": "high",
                    "complexity": "medium",
                },
                {
                    "id": "task_2",
                    "title": "Update user profile endpoint",
                    "description": "Implement profile update logic",
                    "priority": "medium",
                    "complexity": "low",
                },
            ],
            total_tasks=2,
            verification_successful=True,
        )

        return SimplePRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Sample PRD content",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={"EFFECT": 0.8, "COMPUTE": 0.3},
            recommended_mixins=["MixinEventBus", "MixinCaching"],
            external_systems=["PostgreSQL", "Redis", "Kafka"],
            quality_baseline=0.85,
            confidence_score=0.9,
            analysis_timestamp=datetime.utcnow(),
        )

    def test_generator_initialization(self, generator):
        """Test EnumGenerator initializes correctly"""
        assert generator is not None
        assert len(generator.OPERATION_VERBS) > 0
        assert len(generator.STANDARD_STATUSES) > 0

    def test_generate_operation_type_enum(self, generator, sample_prd_analysis):
        """Test operation type enum generation"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        assert isinstance(result, GeneratedEnum)
        assert result.class_name == "EnumUserManagementOperationType"
        assert result.enum_type == "operation_type"
        assert result.file_path == "enum_user_management_operation_type.py"
        assert len(result.values) > 0

        # Check for CRUD operations
        value_names = {v.name for v in result.values}
        assert "CREATE" in value_names
        assert "UPDATE" in value_names
        assert "DELETE" in value_names
        assert "SEARCH" in value_names or "READ" in value_names

    def test_generate_operation_type_enum_with_additional_operations(self, generator, sample_prd_analysis):
        """Test operation type enum with additional operations"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis,
            service_name="user_management",
            additional_operations=["archive", "export", "import"],
        )

        value_names = {v.name for v in result.values}
        assert "ARCHIVE" in value_names
        assert "EXPORT" in value_names
        assert "IMPORT" in value_names

    def test_generate_status_enum(self, generator):
        """Test status enum generation"""
        result = generator.generate_status_enum(service_name="user_management")

        assert isinstance(result, GeneratedEnum)
        assert result.class_name == "EnumUserManagementStatus"
        assert result.enum_type == "status"
        assert result.file_path == "enum_user_management_status.py"
        assert len(result.values) >= 5  # At least standard statuses

        # Check for standard statuses
        value_names = {v.name for v in result.values}
        assert "PENDING" in value_names
        assert "IN_PROGRESS" in value_names
        assert "COMPLETED" in value_names
        assert "FAILED" in value_names

    def test_generate_status_enum_with_prd_analysis(self, generator, sample_prd_analysis):
        """Test status enum generation with PRD analysis"""
        result = generator.generate_status_enum(service_name="user_management", prd_analysis=sample_prd_analysis)

        assert len(result.values) >= 5

    def test_generate_status_enum_with_additional_statuses(self, generator):
        """Test status enum with additional custom statuses"""
        result = generator.generate_status_enum(
            service_name="user_management", additional_statuses=["approved", "rejected", "suspended"]
        )

        value_names = {v.name for v in result.values}
        assert "APPROVED" in value_names
        assert "REJECTED" in value_names
        assert "SUSPENDED" in value_names

    def test_infer_operation_enum_values(self, generator, sample_prd_analysis):
        """Test operation enum value inference from PRD"""
        values = generator.infer_enum_values(prd_analysis=sample_prd_analysis, enum_type="operation")

        assert len(values) > 0
        value_names = {v.name for v in values}

        # Should extract verbs from requirements
        assert "CREATE" in value_names
        assert "UPDATE" in value_names
        assert "DELETE" in value_names
        assert "SEARCH" in value_names
        assert "VALIDATE" in value_names
        assert "LIST" in value_names

    def test_infer_status_enum_values(self, generator):
        """Test status enum value inference from PRD"""
        # Create PRD with status-related text
        parsed_prd = SimpleParsedPRD(
            title="Order Processing Service",
            description="Process orders through pending, processing, and completed states",
            functional_requirements=[
                "Orders start in queued state",
                "Move to processing when worker picks up",
                "Mark as completed or failed based on outcome",
                "Support retry for failed orders",
            ],
            features=["Order tracking", "Retry logic"],
            success_criteria=[],
            technical_details=[],
            dependencies=[],
            extracted_keywords=["order", "processing"],
            sections=["overview"],
            word_count=50,
        )

        decomposition_result = SimpleDecompositionResult(tasks=[], total_tasks=0, verification_successful=True)

        prd_analysis = SimplePRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Sample PRD",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={},
            recommended_mixins=[],
            external_systems=[],
            quality_baseline=0.7,
            confidence_score=0.8,
            analysis_timestamp=datetime.utcnow(),
        )

        values = generator.infer_enum_values(prd_analysis=prd_analysis, enum_type="status")

        value_names = {v.name for v in values}
        assert "PENDING" in value_names
        assert "IN_PROGRESS" in value_names
        assert "COMPLETED" in value_names
        assert "FAILED" in value_names
        assert "RETRYING" in value_names

    def test_validate_enum_code_valid(self, generator):
        """Test validation of valid enum code"""
        valid_code = '''#!/usr/bin/env python3
"""
EnumTestOperationType - ONEX Compliant Enum
"""

from enum import Enum

class EnumTestOperationType(str, Enum):
    """Operation types for test service"""

    CREATE = "create"
    READ = "read"
    UPDATE = "update"

    @classmethod
    def from_string(cls, value: str) -> "EnumTestOperationType":
        """Convert string to enum value"""
        return cls(value.lower())

    def __str__(self) -> str:
        """Return string representation"""
        return self.value
'''

        # Should not raise exception
        assert generator.validate_enum_code(valid_code, "EnumTestOperationType")

    def test_validate_enum_code_missing_imports(self, generator):
        """Test validation fails for missing imports"""
        invalid_code = """
class EnumTestOperationType(str, Enum):
    CREATE = "create"
"""

        with pytest.raises(OnexError) as exc_info:
            generator.validate_enum_code(invalid_code, "EnumTestOperationType")

        error = exc_info.value
        assert "validation failed" in str(error).lower()
        # Check details contain the error (OnexError stores details directly)
        assert hasattr(error, "details")
        assert "errors" in error.details
        assert any("Missing" in err for err in error.details["errors"])

    def test_validate_enum_code_missing_methods(self, generator):
        """Test validation fails for missing required methods"""
        invalid_code = '''#!/usr/bin/env python3
from enum import Enum

class EnumTestOperationType(str, Enum):
    """Test enum"""
    CREATE = "create"
'''

        with pytest.raises(OnexError) as exc_info:
            generator.validate_enum_code(invalid_code, "EnumTestOperationType")

        error = exc_info.value
        assert "validation failed" in str(error).lower()
        # Check details contain method errors (OnexError stores details directly)
        assert hasattr(error, "details")
        assert "errors" in error.details
        error_messages = " ".join(error.details["errors"])
        assert "from_string" in error_messages or "__str__" in error_messages

    def test_to_enum_name_conversion(self, generator):
        """Test conversion to UPPER_SNAKE_CASE"""
        assert generator._to_enum_name("create") == "CREATE"
        assert generator._to_enum_name("create_user") == "CREATE_USER"
        assert generator._to_enum_name("createUser") == "CREATE_USER"
        assert generator._to_enum_name("CreateUser") == "CREATE_USER"
        assert generator._to_enum_name("create-user") == "CREATE_USER"
        assert generator._to_enum_name("create user") == "CREATE_USER"

    def test_to_pascal_case_conversion(self, generator):
        """Test conversion to PascalCase"""
        assert generator._to_pascal_case("user_management") == "UserManagement"
        assert generator._to_pascal_case("user-management") == "UserManagement"
        assert generator._to_pascal_case("user management") == "UserManagement"
        assert generator._to_pascal_case("user") == "User"

    def test_generated_enum_source_code_structure(self, generator, sample_prd_analysis):
        """Test structure of generated enum source code"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        source = result.source_code

        # Check essential elements
        assert "#!/usr/bin/env python3" in source
        assert "from enum import Enum" in source
        assert "class EnumUserManagementOperationType(str, Enum):" in source
        assert "@classmethod" in source
        assert "def from_string(cls" in source
        assert "def __str__(self)" in source
        assert "def display_name(self)" in source

        # Check enum values are present
        assert "CREATE" in source
        assert "UPDATE" in source
        assert "DELETE" in source

    def test_generated_enum_code_is_executable(self, generator, sample_prd_analysis):
        """Test that generated enum code is valid Python"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Try to compile the generated code
        try:
            compile(result.source_code, "<generated>", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")

    def test_generated_enum_json_serialization(self, generator, sample_prd_analysis):
        """Test that generated enums support JSON serialization"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Execute the generated code in a namespace
        namespace = {}
        exec(result.source_code, namespace)

        # Get the enum class
        enum_class = namespace["EnumUserManagementOperationType"]

        # Test JSON serialization
        create_op = enum_class.CREATE
        assert str(create_op) == "create"
        assert json.dumps({"operation": create_op}) == '{"operation": "create"}'

    def test_generated_enum_from_string_method(self, generator, sample_prd_analysis):
        """Test from_string() method in generated enum"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Execute the generated code
        namespace = {}
        exec(result.source_code, namespace)
        enum_class = namespace["EnumUserManagementOperationType"]

        # Test from_string method
        create_op = enum_class.from_string("create")
        assert create_op == enum_class.CREATE

        # Test case insensitivity
        create_op_upper = enum_class.from_string("CREATE")
        assert create_op_upper == enum_class.CREATE

        # Test invalid value raises error
        with pytest.raises(ValueError) as exc_info:
            enum_class.from_string("invalid_operation")
        assert "Invalid" in str(exc_info.value)
        assert "Valid values" in str(exc_info.value)

    def test_generated_enum_display_name(self, generator, sample_prd_analysis):
        """Test display_name property in generated enum"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Execute the generated code
        namespace = {}
        exec(result.source_code, namespace)
        enum_class = namespace["EnumUserManagementOperationType"]

        # Test display_name property
        create_op = enum_class.CREATE
        assert create_op.display_name == "Create"

        # If there's an enum with underscore
        if hasattr(enum_class, "CREATE_USER"):
            assert enum_class.CREATE_USER.display_name == "Create User"

    def test_enum_values_are_sorted(self, generator, sample_prd_analysis):
        """Test that enum values are sorted alphabetically"""
        result = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Check values are sorted
        value_names = [v.name for v in result.values]
        sorted_names = sorted(value_names)
        assert value_names == sorted_names

    def test_multiple_enum_generation_consistency(self, generator, sample_prd_analysis):
        """Test that multiple generations produce consistent results"""
        result1 = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        result2 = generator.generate_operation_type_enum(
            prd_analysis=sample_prd_analysis, service_name="user_management"
        )

        # Should generate same enum values
        assert len(result1.values) == len(result2.values)
        assert {v.name for v in result1.values} == {v.name for v in result2.values}

    def test_enum_generation_for_different_node_types(self, generator):
        """Test enum generation for all 4 ONEX node types"""
        node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

        for node_type in node_types:
            # Create simple PRD for each node type
            parsed_prd = SimpleParsedPRD(
                title=f"{node_type} Node Test",
                description=f"Test {node_type} node operations",
                functional_requirements=[
                    f"Process {node_type.lower()} operations",
                    f"Validate {node_type.lower()} inputs",
                ],
                features=[f"{node_type} processing"],
                success_criteria=[],
                technical_details=[],
                dependencies=[],
                extracted_keywords=[],
                sections=[],
                word_count=50,
            )

            decomposition_result = SimpleDecompositionResult(tasks=[], total_tasks=0, verification_successful=True)

            prd_analysis = SimplePRDAnalysisResult(
                session_id=uuid4(),
                correlation_id=uuid4(),
                prd_content="Test PRD",
                parsed_prd=parsed_prd,
                decomposition_result=decomposition_result,
                node_type_hints={node_type: 0.9},
                recommended_mixins=[],
                external_systems=[],
                quality_baseline=0.7,
                confidence_score=0.8,
                analysis_timestamp=datetime.utcnow(),
            )

            result = generator.generate_operation_type_enum(
                prd_analysis=prd_analysis, service_name=f"{node_type.lower()}_test"
            )

            assert result.class_name == f"Enum{node_type.capitalize()}TestOperationType"
            assert len(result.values) > 0


class TestEnumGeneratorEdgeCases:
    """Test edge cases and error handling"""

    @pytest.fixture
    def generator(self):
        return EnumGenerator()

    def test_empty_prd_analysis(self, generator):
        """Test enum generation with minimal PRD"""
        parsed_prd = SimpleParsedPRD(
            title="",
            description="",
            functional_requirements=[],
            features=[],
            success_criteria=[],
            technical_details=[],
            dependencies=[],
            extracted_keywords=[],
            sections=[],
            word_count=0,
        )

        decomposition_result = SimpleDecompositionResult(tasks=[], total_tasks=0, verification_successful=True)

        prd_analysis = SimplePRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={},
            recommended_mixins=[],
            external_systems=[],
            quality_baseline=0.0,
            confidence_score=0.0,
            analysis_timestamp=datetime.utcnow(),
        )

        # Should still generate at least CRUD operations
        result = generator.generate_operation_type_enum(prd_analysis=prd_analysis, service_name="minimal_service")

        assert len(result.values) >= 4  # At least CREATE, READ, UPDATE, DELETE

    def test_service_name_with_special_characters(self, generator):
        """Test enum generation with service names containing special chars"""
        parsed_prd = SimpleParsedPRD(
            title="Test",
            description="Test service",
            functional_requirements=["Create items"],
            features=[],
            success_criteria=[],
            technical_details=[],
            dependencies=[],
            extracted_keywords=[],
            sections=[],
            word_count=10,
        )

        decomposition_result = SimpleDecompositionResult(tasks=[], total_tasks=0, verification_successful=True)

        prd_analysis = SimplePRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Test",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={},
            recommended_mixins=[],
            external_systems=[],
            quality_baseline=0.5,
            confidence_score=0.6,
            analysis_timestamp=datetime.utcnow(),
        )

        # Test with hyphens
        result = generator.generate_operation_type_enum(prd_analysis=prd_analysis, service_name="user-management")
        assert "UserManagement" in result.class_name

        # Test with mixed case
        result = generator.generate_operation_type_enum(prd_analysis=prd_analysis, service_name="UserManagement")
        assert "UserManagement" in result.class_name

    def test_duplicate_enum_values_are_deduplicated(self, generator):
        """Test that duplicate enum values are handled correctly"""
        parsed_prd = SimpleParsedPRD(
            title="Test Service",
            description="Service with repeated operations",
            functional_requirements=[
                "Create new items",
                "Create users",
                "Create accounts",
                "Update items",
                "Update users",
            ],
            features=["Item creation", "User creation"],
            success_criteria=[],
            technical_details=[],
            dependencies=[],
            extracted_keywords=[],
            sections=[],
            word_count=50,
        )

        decomposition_result = SimpleDecompositionResult(tasks=[], total_tasks=0, verification_successful=True)

        prd_analysis = SimplePRDAnalysisResult(
            session_id=uuid4(),
            correlation_id=uuid4(),
            prd_content="Test",
            parsed_prd=parsed_prd,
            decomposition_result=decomposition_result,
            node_type_hints={},
            recommended_mixins=[],
            external_systems=[],
            quality_baseline=0.7,
            confidence_score=0.8,
            analysis_timestamp=datetime.utcnow(),
        )

        result = generator.generate_operation_type_enum(prd_analysis=prd_analysis, service_name="test_service")

        # Count occurrences of CREATE in values
        create_count = sum(1 for v in result.values if v.name == "CREATE")
        assert create_count == 1  # Should only appear once

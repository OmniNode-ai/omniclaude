"""
Unit tests for Omninode naming convention validator.

Tests enforce the conventions documented in OMNINODE_NAMING_CONVENTIONS.md
based on analysis of 508 files from the omnibase_core codebase.
"""

import pytest

from .lib.validators.naming_validator import NamingValidator, Violation


class TestOmninodeModelClasses:
    """Test Model class naming conventions (100% adherence expected)."""

    def test_valid_model_class_name(self):
        """Valid Model class names should pass."""
        code = """
from pydantic import BaseModel

class ModelTaskData(BaseModel):
    task_id: str
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "model_task_data.py")

        # Should have no violations
        model_violations = [v for v in violations if v.violation_type == "class"]
        assert len(model_violations) == 0

    def test_model_class_without_prefix(self):
        """Model class without 'Model' prefix should fail."""
        code = """
from pydantic import BaseModel

class TaskData(BaseModel):
    task_id: str
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "model_task_data.py")

        # Should have exactly one violation
        model_violations = [v for v in violations if v.violation_type == "class"]
        assert len(model_violations) == 1
        assert "Model" in model_violations[0].message
        assert model_violations[0].suggestion is not None
        assert "ModelTaskData" in model_violations[0].suggestion

    def test_multiple_model_classes(self):
        """Multiple Model classes should all have proper prefixes."""
        code = """
from pydantic import BaseModel

class ModelTaskData(BaseModel):
    task_id: str

class ModelProjectData(BaseModel):
    project_id: str

class ConfigData(BaseModel):  # Missing prefix
    config_id: str
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "models.py")

        # Should have exactly one violation for ConfigData
        model_violations = [v for v in violations if v.violation_type == "class"]
        assert len(model_violations) == 1
        assert "ConfigData" in model_violations[0].name


class TestOmninodeEnumClasses:
    """Test Enum class naming conventions (100% adherence expected)."""

    def test_valid_enum_class_name(self):
        """Valid Enum class names should pass."""
        code = """
from enum import Enum

class EnumTaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "enum_task_status.py")

        # Should have no violations
        enum_violations = [v for v in violations if v.violation_type == "class"]
        assert len(enum_violations) == 0

    def test_enum_class_without_prefix(self):
        """Enum class without 'Enum' prefix should fail."""
        code = """
from enum import Enum

class TaskStatus(str, Enum):
    TODO = "todo"
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "enum_task_status.py")

        # Should have exactly one violation
        enum_violations = [v for v in violations if v.violation_type == "class"]
        assert len(enum_violations) == 1
        assert "Enum" in enum_violations[0].message
        assert enum_violations[0].suggestion is not None
        assert "EnumTaskStatus" in enum_violations[0].suggestion

    def test_enum_members_upper_snake_case(self):
        """Enum members should use UPPER_SNAKE_CASE."""
        code = """
from enum import Enum

class EnumTaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    IN_PROGRESS = "in_progress"
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "enum_task_status.py")

        # Should have no violations
        assert len(violations) == 0


class TestOmninodeExceptionClasses:
    """Test Exception class naming conventions."""

    def test_valid_exception_class_name(self):
        """Valid Exception class names should pass."""
        code = """
class OnexError(Exception):
    pass

class ValidationError(OnexError):
    pass

class ContractValidationError(ValidationError):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "exceptions.py")

        # Should have no violations
        exception_violations = [v for v in violations if v.violation_type == "class"]
        assert len(exception_violations) == 0

    def test_exception_class_without_error_suffix(self):
        """Exception class without 'Error' suffix should fail."""
        code = """
class ValidationException(Exception):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "exceptions.py")

        # Should have exactly one violation
        exception_violations = [v for v in violations if v.violation_type == "class"]
        assert len(exception_violations) == 1
        assert "Error" in exception_violations[0].message


class TestOmninodeProtocolClasses:
    """Test Protocol class naming conventions."""

    def test_valid_simple_protocol_names(self):
        """Simple Protocol names like Serializable should pass."""
        code = """
from typing import Protocol

class Serializable(Protocol):
    def serialize(self) -> dict: ...

class Configurable(Protocol):
    def configure(self, **kwargs) -> bool: ...

class Identifiable(Protocol):
    def get_id(self) -> str: ...
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "protocols.py")

        # Should have no violations
        protocol_violations = [v for v in violations if v.violation_type == "class"]
        assert len(protocol_violations) == 0

    def test_valid_protocol_prefix_names(self):
        """Protocol classes with Protocol prefix should pass."""
        code = """
from typing import Protocol

class ProtocolMetadataProvider(Protocol):
    def get_metadata(self) -> dict: ...

class ProtocolValidatable(Protocol):
    def validate(self) -> bool: ...
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "protocols.py")

        # Should have no violations
        protocol_violations = [v for v in violations if v.violation_type == "class"]
        assert len(protocol_violations) == 0


class TestOmninodeNodeServiceClasses:
    """Test Node service class naming conventions."""

    def test_valid_node_service_names(self):
        """Valid Node service class names should pass."""
        code = """
class NodeEffectService:
    def execute_effect(self, contract):
        pass

class NodeComputeService:
    def execute_compute(self, contract):
        pass

class NodeReducerService:
    def execute_reduction(self, contract):
        pass

class NodeOrchestratorService:
    def execute_orchestration(self, contract):
        pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "node_effect_service.py")

        # Should have no violations
        node_violations = [v for v in violations if v.violation_type == "class"]
        assert len(node_violations) == 0

    def test_invalid_node_service_pattern(self):
        """Invalid Node service pattern should fail."""
        code = """
class NodeeffectService:  # Wrong - lowercase 'e' after Node
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "services.py")

        # Should have violations - NodeeffectService doesn't match Node<Type>Service pattern
        node_violations = [v for v in violations if v.violation_type == "class"]
        assert len(node_violations) > 0

    def test_node_service_file_naming(self):
        """Files with Node services should use node_<type>_service.py naming."""
        code = """
class NodeEffectService:
    pass
"""
        validator = NamingValidator(validation_mode="omninode")

        # Valid file name
        violations = validator.validate_content(code, "node_effect_service.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 0

        # Invalid file name
        violations = validator.validate_content(code, "effect_service.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 1
        assert "node_<type>_service.py" in file_violations[0].expected_format


class TestOmninodeSubcontractClasses:
    """Test Subcontract class naming conventions."""

    def test_valid_subcontract_names(self):
        """Valid Subcontract class names should pass."""
        code = """
from pydantic import BaseModel

class ModelAggregationSubcontract(BaseModel):
    aggregation_type: str

class ModelFSMSubcontract(BaseModel):
    state_machine: dict

class ModelCachingSubcontract(BaseModel):
    cache_config: dict
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(
            code, "model_aggregation_subcontract.py"
        )

        # Should have no violations
        subcontract_violations = [v for v in violations if v.violation_type == "class"]
        assert len(subcontract_violations) == 0

    def test_invalid_subcontract_pattern(self):
        """Invalid Subcontract pattern should fail."""
        code = """
from pydantic import BaseModel

class AggregationSubcontract(BaseModel):  # Missing Model prefix
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "subcontract.py")

        # Should have violations
        subcontract_violations = [v for v in violations if v.violation_type == "class"]
        assert len(subcontract_violations) > 0


class TestOmninodeMixinClasses:
    """Test Mixin class naming conventions."""

    def test_valid_mixin_names(self):
        """Valid Mixin class names should pass."""
        code = """
class MixinNodeService:
    def get_service(self, name: str):
        pass

class MixinHealthCheck:
    def check_health(self) -> bool:
        pass

class MixinEventDrivenNode:
    def handle_event(self, event):
        pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "mixins.py")

        # Should have no violations
        mixin_violations = [v for v in violations if v.violation_type == "class"]
        assert len(mixin_violations) == 0

    def test_invalid_mixin_pattern(self):
        """Invalid Mixin pattern should fail."""
        code = """
class NodeserviceMixin:  # Wrong - lowercase after Mixin prefix
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "mixins.py")

        # Should have violations - doesn't match Mixin<Capability> pattern
        mixin_violations = [v for v in violations if v.violation_type == "class"]
        assert len(mixin_violations) > 0
        assert "Mixin" in mixin_violations[0].message


class TestOmninodeFunctionNaming:
    """Test function naming conventions (100% snake_case adherence expected)."""

    def test_valid_function_names(self):
        """Valid function names should pass."""
        code = """
def execute_effect(contract):
    pass

def validate_contract(data):
    pass

def get_field(path):
    pass

def _private_helper():
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "utils.py")

        # Should have no violations
        function_violations = [v for v in violations if v.violation_type == "function"]
        assert len(function_violations) == 0

    def test_camel_case_function_name(self):
        """camelCase function names should fail."""
        code = """
def executeEffect(contract):
    pass

def validateContract(data):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "utils.py")

        # Should have two violations
        function_violations = [v for v in violations if v.violation_type == "function"]
        assert len(function_violations) == 2
        assert "snake_case" in function_violations[0].message

    def test_pascal_case_function_name(self):
        """PascalCase function names should fail."""
        code = """
def ExecuteEffect(contract):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "utils.py")

        # Should have one violation
        function_violations = [v for v in violations if v.violation_type == "function"]
        assert len(function_violations) == 1


class TestOmninodeVariableNaming:
    """Test variable naming conventions (100% snake_case adherence expected)."""

    def test_valid_variable_names(self):
        """Valid variable names should pass."""
        code = """
task_data = {}
correlation_id = "123"
config_value = 42
is_enabled = True
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "utils.py")

        # Should have no violations
        variable_violations = [v for v in violations if v.violation_type == "variable"]
        assert len(variable_violations) == 0

    def test_camel_case_variable_name(self):
        """camelCase variable names should fail."""
        code = """
taskData = {}
correlationId = "123"
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "utils.py")

        # Should have two violations
        variable_violations = [v for v in violations if v.violation_type == "variable"]
        assert len(variable_violations) == 2
        assert "snake_case" in variable_violations[0].message


class TestOmninodeConstantNaming:
    """Test constant naming conventions (100% UPPER_SNAKE_CASE adherence expected)."""

    def test_valid_constant_names(self):
        """Valid constant names should pass."""
        code = """
MAX_FILE_SIZE = 1024 * 1024
DEFAULT_TIMEOUT = 300
LEGACY_ENUM_VALUES = {}
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "constants.py")

        # Should have no violations
        constant_violations = [v for v in violations if v.violation_type == "constant"]
        assert len(constant_violations) == 0

    def test_lower_case_constant_name(self):
        """lowercase constant names are treated as variables in Omninode."""
        code = """
max_file_size = 1024 * 1024
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "constants.py")

        # lowercase names are treated as variables, not constants
        # Constants MUST be UPPER_SNAKE_CASE to be recognized as constants
        variable_violations = [v for v in violations if v.violation_type == "variable"]
        # Since max_file_size is already snake_case, no violation
        assert len(variable_violations) == 0


class TestOmninodeFileNaming:
    """Test file naming conventions."""

    def test_model_file_naming(self):
        """Files with Model classes should use model_*.py naming."""
        code = """
from pydantic import BaseModel

class ModelTaskData(BaseModel):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")

        # Valid file name
        violations = validator.validate_content(code, "model_task_data.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 0

        # Invalid file name
        violations = validator.validate_content(code, "task_data.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 1
        assert "model_*.py" in file_violations[0].expected_format

    def test_enum_file_naming(self):
        """Files with Enum classes should use enum_*.py naming."""
        code = """
from enum import Enum

class EnumTaskStatus(str, Enum):
    TODO = "todo"
"""
        validator = NamingValidator(validation_mode="omninode")

        # Valid file name
        violations = validator.validate_content(code, "enum_task_status.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 0

        # Invalid file name
        violations = validator.validate_content(code, "task_status.py")
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 1
        assert "enum_*.py" in file_violations[0].expected_format


class TestOmninodeCompleteExamples:
    """Test complete real-world examples from Omninode codebase."""

    def test_complete_model_file(self):
        """Complete model file should pass all checks."""
        code = """
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from enum import Enum


class EnumTaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    REVIEW = "review"
    DONE = "done"


class ModelTaskData(BaseModel):
    task_title: str = Field(..., min_length=1)
    task_order: int = Field(0, ge=0, le=100)
    status: EnumTaskStatus
    correlation_id: UUID
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def validate_business_rules(self) -> bool:
        if self.task_order > 80:
            return False
        return True

    def get_task_title(self) -> str:
        return self.task_title

    @classmethod
    def create_default(cls):
        return cls(
            task_title="New Task",
            status=EnumTaskStatus.TODO,
            correlation_id=UUID("00000000-0000-0000-0000-000000000000")
        )


MAX_TASK_TITLE_LENGTH = 200
DEFAULT_TASK_ORDER = 0
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "model_task_data.py")

        # Should have no violations
        assert len(violations) == 0

    def test_complete_service_file(self):
        """Complete service file should pass all checks."""
        code = """
from datetime import datetime, timedelta
from typing import Optional


class SimplifiedSessionManager:
    def __init__(self, timeout: int = 3600):
        self.sessions: dict[str, datetime] = {}
        self.timeout = timeout

    def create_session(self) -> str:
        import uuid
        session_id = str(uuid.uuid4())
        self.sessions[session_id] = datetime.now()
        return session_id

    def validate_session(self, session_id: str) -> bool:
        if session_id not in self.sessions:
            return False
        return True

    def _cleanup_expired_sessions(self) -> int:
        now = datetime.now()
        expired = []
        for session_id, last_seen in self.sessions.items():
            if now - last_seen > timedelta(seconds=self.timeout):
                expired.append(session_id)
        return len(expired)


DEFAULT_SESSION_TIMEOUT = 3600
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "session_manager.py")

        # Should have no violations
        assert len(violations) == 0


class TestViolationObject:
    """Test Violation object properties."""

    def test_violation_str_format(self):
        """Violation string format should be clear."""
        violation = Violation(
            file="test.py",
            line=10,
            column=5,
            name="TaskData",
            violation_type="class",
            expected_format="Model<Name>",
            message="use 'ModelTaskData' instead",
        )

        str_repr = str(violation)
        assert "test.py:10:5" in str_repr
        assert "TaskData" in str_repr
        assert "Model<Name>" in str_repr

    def test_violation_suggestion_default(self):
        """Violation should use expected_format as default suggestion."""
        violation = Violation(
            file="test.py",
            line=10,
            column=5,
            name="TaskData",
            violation_type="class",
            expected_format="Model<Name>",
            message="use 'ModelTaskData' instead",
        )

        assert violation.suggestion == "Model<Name>"

    def test_violation_properties(self):
        """Violation properties should work correctly."""
        violation = Violation(
            file="test.py",
            line=10,
            column=5,
            name="TaskData",
            violation_type="class",
            expected_format="Model<Name>",
            message="Omninode convention",
        )

        assert violation.rule == "Omninode convention"
        assert violation.type == "class"


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_file(self):
        """Empty file should pass."""
        code = ""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "empty.py")
        assert len(violations) == 0

    def test_init_file(self):
        """__init__.py files should be skipped for file naming checks."""
        code = """
from pydantic import BaseModel

class ModelTaskData(BaseModel):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "__init__.py")

        # Should have no file naming violations
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 0

    def test_test_file(self):
        """test_*.py files should be skipped for file naming checks."""
        code = """
from pydantic import BaseModel

class ModelTaskData(BaseModel):
    pass
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "test_models.py")

        # Should have no file naming violations
        file_violations = [v for v in violations if v.violation_type == "file"]
        assert len(file_violations) == 0

    def test_syntax_error_handling(self):
        """Invalid Python syntax should not crash validator."""
        code = """
def invalid_syntax(
    # Missing closing parenthesis
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "invalid.py")

        # Should handle gracefully
        assert isinstance(violations, list)

    def test_dunder_methods(self):
        """Dunder methods should not trigger violations."""
        code = """
class MyClass:
    def __init__(self):
        pass

    def __str__(self):
        return "test"

    def __repr__(self):
        return "MyClass()"
"""
        validator = NamingValidator(validation_mode="omninode")
        violations = validator.validate_content(code, "my_class.py")

        # Should have no violations for dunder methods
        function_violations = [v for v in violations if v.violation_type == "function"]
        assert len(function_violations) == 0


class TestAutoDetection:
    """Test auto-detection of repository types."""

    def test_omnibase_repo_detection(self):
        """Paths with omnibase_ should be detected as Omninode repos."""
        assert NamingValidator.is_omninode_repo("/path/to/omnibase_core/models.py")
        assert NamingValidator.is_omninode_repo("/path/to/OMNIBASE_SPI/utils.py")
        assert NamingValidator.is_omninode_repo("/home/user/omnibase_auth/service.py")

    def test_omni_repo_detection(self):
        """Paths with /omni + lowercase letter should be detected as Omninode repos."""
        assert NamingValidator.is_omninode_repo("/path/to/omniauth/models.py")
        assert NamingValidator.is_omninode_repo("/path/to/omnitools/utils.py")
        assert NamingValidator.is_omninode_repo("/home/user/omnisync/service.py")

    def test_archon_repo_detection(self):
        """Paths with Archon should NOT be detected as Omninode repos."""
        assert not NamingValidator.is_omninode_repo("/path/to/Archon/models.py")
        assert not NamingValidator.is_omninode_repo("/home/user/archon/service.py")
        assert not NamingValidator.is_omninode_repo("/workspace/Archon/test.py")

    def test_random_repo_detection(self):
        """Random paths should NOT be detected as Omninode repos."""
        assert not NamingValidator.is_omninode_repo("/path/to/django-app/models.py")
        assert not NamingValidator.is_omninode_repo("/home/user/myproject/service.py")
        assert not NamingValidator.is_omninode_repo("/usr/local/lib/python/test.py")

    def test_user_class_valid_in_django_invalid_in_omninode(self):
        """User class should be valid in Django but invalid in Omninode with BaseModel."""
        # Test with Pydantic BaseModel (which Omninode uses)
        code = """
from pydantic import BaseModel

class User(BaseModel):
    username: str
"""
        # In Django/Standard repo - should be valid (just PascalCase)
        validator_pep8 = NamingValidator(validation_mode="pep8")
        violations_pep8 = validator_pep8.validate_content(
            code, "/path/to/django/models.py"
        )
        class_violations_pep8 = [
            v for v in violations_pep8 if v.violation_type == "class"
        ]
        assert len(class_violations_pep8) == 0

        # In Omninode repo - should be invalid (needs Model prefix)
        validator_omninode = NamingValidator(validation_mode="omninode")
        violations_omninode = validator_omninode.validate_content(
            code, "/path/to/omnibase_core/models.py"
        )
        class_violations_omninode = [
            v for v in violations_omninode if v.violation_type == "class"
        ]
        assert len(class_violations_omninode) == 1
        assert "Model" in class_violations_omninode[0].message

    def test_model_user_valid_in_omninode_valid_in_django(self):
        """ModelUser class should be valid in both Omninode and Django repos."""
        code = """
from pydantic import BaseModel

class ModelUser(BaseModel):
    username: str
"""
        # In Omninode repo - should be valid
        validator_omninode = NamingValidator(validation_mode="omninode")
        violations_omninode = validator_omninode.validate_content(
            code, "/path/to/omnibase_core/models.py"
        )
        class_violations_omninode = [
            v for v in violations_omninode if v.violation_type == "class"
        ]
        assert len(class_violations_omninode) == 0

        # In Django/Standard repo - should be valid (just PascalCase)
        validator_pep8 = NamingValidator(validation_mode="pep8")
        violations_pep8 = validator_pep8.validate_content(
            code, "/path/to/django/models.py"
        )
        class_violations_pep8 = [
            v for v in violations_pep8 if v.violation_type == "class"
        ]
        assert len(class_violations_pep8) == 0

    def test_auto_detection_omninode_path(self):
        """Auto mode should detect Omninode repo and enforce Model prefix."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    username: str
"""
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(
            code, "/path/to/omnibase_core/models.py"
        )

        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 1
        assert "Model" in class_violations[0].message
        assert class_violations[0].suggestion is not None
        assert "ModelUser" in class_violations[0].suggestion

    def test_auto_detection_archon_path(self):
        """Auto mode should detect Archon repo and use standard PEP 8."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    username: str
"""
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(code, "/workspace/Archon/models.py")

        # Should have no violations - User is valid PascalCase
        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 0

    def test_auto_detection_generic_django_path(self):
        """Auto mode should detect generic Django repo and use standard PEP 8."""
        code = """
from django.db import models

class User(models.Model):
    username = models.CharField(max_length=100)

class BlogPost(models.Model):
    title = models.CharField(max_length=200)
"""
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(
            code, "/home/projects/my-blog/models.py"
        )

        # Should have no violations - both classes are valid PascalCase
        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 0

    def test_omninode_bridge_excluded(self):
        """omninode_bridge repository should use PEP 8, not Omninode conventions."""
        # Verify omninode_bridge is NOT detected as Omninode repo
        assert not NamingValidator.is_omninode_repo(
            "/path/to/omninode_bridge/models.py"
        )
        assert not NamingValidator.is_omninode_repo(
            "/home/user/omninode_bridge/sync.py"
        )
        assert not NamingValidator.is_omninode_repo(
            "/code/omninode_bridge/api/endpoints.py"
        )

    def test_omninode_bridge_does_not_trigger_model_prefix(self):
        """User class (without Model prefix) should be valid in omninode_bridge."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    username: str
    email: str

class SyncStatus(BaseModel):
    is_synced: bool
    last_sync: str
"""
        # In omninode_bridge - should use standard PEP 8 (no Model prefix required)
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(
            code, "/path/to/omninode_bridge/models.py"
        )

        # Should have no violations - User and SyncStatus are valid PascalCase
        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 0

    def test_omninode_bridge_standard_pep8_functions(self):
        """Functions in omninode_bridge should use standard snake_case (same as Omninode)."""
        code = """
def sync_data(source, target):
    pass

def validate_connection(endpoint):
    pass

def InvalidCamelCase():  # This should fail
    pass
"""
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(
            code, "/path/to/omninode_bridge/sync.py"
        )

        # Should have one violation for InvalidCamelCase (PascalCase function name)
        function_violations = [v for v in violations if v.violation_type == "function"]
        assert len(function_violations) == 1
        assert "InvalidCamelCase" in function_violations[0].name

    def test_omninode_repos_still_require_model_prefix(self):
        """Verify other Omninode repos (omnibase_, omniauth) still require Model prefix."""
        code = """
from pydantic import BaseModel

class User(BaseModel):
    username: str
"""
        # Test omnibase_core - should require Model prefix
        validator = NamingValidator(validation_mode="auto")
        violations = validator.validate_content(
            code, "/path/to/omnibase_core/models.py"
        )
        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 1
        assert "Model" in class_violations[0].message

        # Test omniauth - should require Model prefix
        violations = validator.validate_content(code, "/path/to/omniauth/models.py")
        class_violations = [v for v in violations if v.violation_type == "class"]
        assert len(class_violations) == 1
        assert "Model" in class_violations[0].message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

#!/usr/bin/env python3
"""
Unit tests for framework validation quality gates (FV-001 to FV-002).

Tests:
- LifecycleComplianceValidator (FV-001)
- FrameworkIntegrationValidator (FV-002)
- Lifecycle method validation
- Framework pattern compliance
- Integration point verification

ONEX v2.0 Compliance:
- Async test patterns
- Mock agent classes
- Performance validation
- Type safety
"""

from typing import Any

import pytest

from agents.lib.models.model_quality_gate import EnumQualityGate
from agents.lib.validators.framework_validators import (
    FrameworkIntegrationValidator,
    LifecycleComplianceValidator,
)


# Mock agent classes for testing


class MockValidAgent:
    """Valid ONEX agent with proper lifecycle methods."""

    def __init__(self, container: Any) -> None:
        """Initialize with dependency injection."""
        self.container = container
        self.initialized = False
        self.cleaned_up = False

    async def startup(self) -> None:
        """Initialize resources."""
        self.initialized = True

    async def shutdown(self) -> None:
        """Clean up resources."""
        self.cleaned_up = True


class MockInvalidAgent:
    """Invalid agent missing lifecycle methods."""

    def __init__(self) -> None:
        """Initialize without dependencies."""
        pass


class NodeDatabaseWriterEffect:
    """Mock ONEX Effect node with proper naming."""

    def __init__(self, container: Any) -> None:
        self.container = container
        self.event_publisher = None

    async def startup(self) -> None:
        """Initialize."""
        pass

    async def shutdown(self) -> None:
        """Cleanup."""
        pass


class InvalidNodeName:
    """Node without proper ONEX suffix."""

    def __init__(self, container: Any) -> None:
        self.container = container


class TestLifecycleComplianceValidator:
    """Test suite for FV-001: Lifecycle Compliance Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return LifecycleComplianceValidator()

    @pytest.mark.asyncio
    async def test_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator.gate == EnumQualityGate.LIFECYCLE_COMPLIANCE
        assert validator.gate.category == "framework_validation"
        assert validator.gate.performance_target_ms == 35

    @pytest.mark.asyncio
    async def test_valid_agent_class(self, validator):
        """Test validation passes with valid agent class."""
        context = {"agent_class": MockValidAgent}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.gate == EnumQualityGate.LIFECYCLE_COMPLIANCE
        assert "Lifecycle compliance validated" in result.message
        assert result.metadata["has_init"] is True
        assert "startup" in result.metadata["startup_methods"]
        assert "shutdown" in result.metadata["cleanup_methods"]

    @pytest.mark.asyncio
    async def test_missing_agent(self, validator):
        """Test validation fails when no agent provided."""
        context = {}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "No agent_class or agent_instance provided" in result.message
        assert result.metadata["error"] == "missing_agent"

    @pytest.mark.asyncio
    async def test_agent_instance(self, validator):
        """Test validation works with agent instance."""
        instance = MockValidAgent(container=None)
        context = {"agent_instance": instance}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["agent_class"] == "MockValidAgent"

    @pytest.mark.asyncio
    async def test_missing_startup_method(self, validator):
        """Test warning when startup method is missing."""
        context = {"agent_class": MockInvalidAgent}

        result = await validator.validate(context)

        # Should pass but with warnings
        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("No startup method" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_missing_cleanup_method(self, validator):
        """Test warning when cleanup method is missing."""
        context = {"agent_class": MockInvalidAgent}

        result = await validator.validate(context)

        # Should pass but with warnings
        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("No cleanup method" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_init_without_dependencies(self, validator):
        """Test warning when __init__ has no dependency parameters."""
        context = {"agent_class": MockInvalidAgent}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("no dependency parameters" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_init_with_dependencies(self, validator):
        """Test validation recognizes dependency parameters."""
        context = {"agent_class": MockValidAgent}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert "container" in result.metadata["init_params"]

    @pytest.mark.asyncio
    async def test_initialization_success(self, validator):
        """Test validation with successful initialization."""
        context = {
            "agent_class": MockValidAgent,
            "initialization_result": {
                "success": True,
                "resources_acquired": 3,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["initialization_attempted"] is True
        assert result.metadata["initialization_success"] is True
        assert result.metadata["resources_acquired"] == 3

    @pytest.mark.asyncio
    async def test_initialization_failure(self, validator):
        """Test validation fails when initialization fails."""
        context = {
            "agent_class": MockValidAgent,
            "initialization_result": {
                "success": False,
                "error": "Database connection failed",
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Initialization failed" in result.message

    @pytest.mark.asyncio
    async def test_cleanup_success(self, validator):
        """Test validation with successful cleanup."""
        context = {
            "agent_class": MockValidAgent,
            "cleanup_result": {
                "success": True,
                "resources_released": 3,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["cleanup_attempted"] is True
        assert result.metadata["cleanup_success"] is True
        assert result.metadata["resources_released"] == 3

    @pytest.mark.asyncio
    async def test_cleanup_failure(self, validator):
        """Test validation fails when cleanup fails."""
        context = {
            "agent_class": MockValidAgent,
            "cleanup_result": {
                "success": False,
                "error": "Failed to close connections",
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Cleanup failed" in result.message

    @pytest.mark.asyncio
    async def test_resource_leaks(self, validator):
        """Test validation fails when resource leaks detected."""
        context = {
            "agent_class": MockValidAgent,
            "cleanup_result": {
                "success": True,
                "resources_released": 2,
                "resource_leaks": 1,
            },
        }

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "Resource leaks detected" in result.message

    @pytest.mark.asyncio
    async def test_cleanup_not_in_finally(self, validator):
        """Test warning when cleanup not in finally block."""
        context = {
            "agent_class": MockValidAgent,
            "cleanup_in_finally": False,
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("finally blocks" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_full_lifecycle_validation(self, validator):
        """Test complete lifecycle validation."""
        context = {
            "agent_class": MockValidAgent,
            "initialization_result": {
                "success": True,
                "resources_acquired": 5,
            },
            "cleanup_result": {
                "success": True,
                "resources_released": 5,
                "resource_leaks": 0,
            },
            "cleanup_in_finally": True,
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["initialization_success"] is True
        assert result.metadata["cleanup_success"] is True
        assert result.metadata["cleanup_in_finally"] is True


class TestFrameworkIntegrationValidator:
    """Test suite for FV-002: Framework Integration Validator."""

    @pytest.fixture
    def validator(self):
        """Create validator instance."""
        return FrameworkIntegrationValidator()

    @pytest.mark.asyncio
    async def test_initialization(self, validator):
        """Test validator initializes correctly."""
        assert validator.gate == EnumQualityGate.FRAMEWORK_INTEGRATION
        assert validator.gate.category == "framework_validation"
        assert validator.gate.performance_target_ms == 25

    @pytest.mark.asyncio
    async def test_valid_framework_imports(self, validator):
        """Test validation with framework imports."""
        context = {
            "imports": [
                "omnibase_core",
                "llama_index",
                "pydantic",
                "asyncio",
            ]
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["imports_count"] == 4
        assert len(result.metadata["framework_imports"]) == 3

    @pytest.mark.asyncio
    async def test_missing_framework_imports(self, validator):
        """Test warning when framework imports missing."""
        context = {"imports": ["asyncio", "typing"]}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("Missing recommended framework imports" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_no_imports_provided(self, validator):
        """Test warning when no imports provided."""
        context = {}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("No imports provided" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_onex_node_valid_naming(self, validator):
        """Test validation with valid ONEX node naming."""
        context = {"agent_class": NodeDatabaseWriterEffect}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["onex_node_type"] == "Effect"

    @pytest.mark.asyncio
    async def test_onex_node_invalid_suffix(self, validator):
        """Test failure with invalid ONEX node suffix."""

        class NodeInvalidSuffix:
            pass

        context = {"agent_class": NodeInvalidSuffix}

        result = await validator.validate(context)

        assert result.status == "failed"
        assert "must end with one of" in result.message

    @pytest.mark.asyncio
    async def test_non_onex_class_naming(self, validator):
        """Test warning for non-ONEX class naming."""
        context = {"agent_class": MockValidAgent}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("doesn't follow ONEX naming" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_integration_points_complete(self, validator):
        """Test validation with all integration points."""
        context = {
            "agent_class": NodeDatabaseWriterEffect,
            "integration_points": {
                "contract_yaml": True,
                "event_publisher": True,
                "health_check": True,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["integration_points"]["contract_yaml"] is True
        assert result.metadata["integration_points"]["event_publisher"] is True

    @pytest.mark.asyncio
    async def test_missing_integration_points(self, validator):
        """Test warning for missing integration points."""
        context = {
            "agent_class": NodeDatabaseWriterEffect,
            "integration_points": {
                "health_check": True,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("Missing integration point: contract_yaml" in w for w in warnings)
        assert any("Missing integration point: event_publisher" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_include_directives_present(self, validator):
        """Test validation with @include directives."""
        source_code = """
        # Agent implementation
        # @include @MANDATORY_FUNCTIONS.md
        # @include @COMMON_TEMPLATES.md

        class NodeTestEffect:
            pass
        """

        context = {"source_code": source_code}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["include_directives"] == 2
        assert len(result.metadata["templates_used"]) == 2

    @pytest.mark.asyncio
    async def test_no_include_directives(self, validator):
        """Test warning when no @include directives found."""
        source_code = """
        class NodeTestEffect:
            pass
        """

        context = {"source_code": source_code}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("No @include directives" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_no_source_code(self, validator):
        """Test warning when no source code provided."""
        context = {}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("No source code provided" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_dependency_injection_present(self, validator):
        """Test detection of dependency injection pattern."""
        context = {"agent_class": NodeDatabaseWriterEffect}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["dependency_injection"] is True

    @pytest.mark.asyncio
    async def test_dependency_injection_missing(self, validator):
        """Test warning when dependency injection missing."""
        context = {"agent_class": MockInvalidAgent}

        result = await validator.validate(context)

        assert result.status == "passed"
        warnings = result.metadata["warnings"]
        assert any("container parameter" in w for w in warnings)

    @pytest.mark.asyncio
    async def test_event_publishing_capability(self, validator):
        """Test detection of event publishing capability."""

        # Create a class with event publishing method and proper ONEX naming
        class NodeEventPublisherEffect:
            def __init__(self, container: Any) -> None:
                self.container = container

            async def publish_event(self, event: Any) -> None:
                """Publish event."""
                pass

        context = {"agent_class": NodeEventPublisherEffect}

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata.get("event_publishing") is True

    @pytest.mark.asyncio
    async def test_complete_framework_integration(self, validator):
        """Test complete framework integration validation."""
        source_code = """
        # @include MANDATORY_FUNCTIONS.md
        # @include COMMON_TEMPLATES.md
        # @include COMMON_AGENT_PATTERNS.md

        from omnibase_core import ModelContainer
        from llama_index import EventPublisher
        from pydantic import BaseModel

        class NodeDataProcessorCompute:
            def __init__(self, container: ModelContainer):
                self.container = container
                self.event_publisher = EventPublisher()

            async def startup(self) -> None:
                pass

            async def shutdown(self) -> None:
                pass
        """

        context = {
            "imports": ["omnibase_core", "llama_index", "pydantic"],
            "agent_class": NodeDatabaseWriterEffect,
            "source_code": source_code,
            "patterns_used": [
                "dependency_injection",
                "event_publishing",
                "onex_node_types",
            ],
            "integration_points": {
                "contract_yaml": True,
                "event_publisher": True,
                "health_check": True,
            },
        }

        result = await validator.validate(context)

        assert result.status == "passed"
        assert result.metadata["imports_count"] == 3
        assert result.metadata["include_directives"] == 3
        assert result.metadata["dependency_injection"] is True
        assert result.metadata["onex_node_type"] == "Effect"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

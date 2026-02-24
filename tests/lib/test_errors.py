# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for omniclaude.lib.errors module.

Verifies that ONEX error handling classes are properly re-exported
from omnibase_core and function correctly.
"""

from __future__ import annotations

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


class TestErrorsImports:
    """Tests for error module imports."""

    def test_enum_core_error_code_importable(self) -> None:
        """EnumCoreErrorCode can be imported from omniclaude.lib.errors."""
        from omniclaude.lib.errors import EnumCoreErrorCode

        assert EnumCoreErrorCode is not None

    def test_model_onex_error_importable(self) -> None:
        """ModelOnexError can be imported from omniclaude.lib.errors."""
        from omniclaude.lib.errors import ModelOnexError

        assert ModelOnexError is not None

    def test_onex_error_importable(self) -> None:
        """OnexError can be imported from omniclaude.lib.errors."""
        from omniclaude.lib.errors import OnexError

        assert OnexError is not None

    def test_all_exports_defined(self) -> None:
        """Module __all__ contains expected exports."""
        from omniclaude.lib import errors

        assert hasattr(errors, "__all__")
        assert "EnumCoreErrorCode" in errors.__all__
        assert "ModelOnexError" in errors.__all__
        assert "OnexError" in errors.__all__


class TestEnumCoreErrorCode:
    """Tests for EnumCoreErrorCode enum values."""

    def test_validation_error_exists(self) -> None:
        """EnumCoreErrorCode has VALIDATION_ERROR value."""
        from omniclaude.lib.errors import EnumCoreErrorCode

        assert hasattr(EnumCoreErrorCode, "VALIDATION_ERROR")
        assert EnumCoreErrorCode.VALIDATION_ERROR is not None

    def test_configuration_error_exists(self) -> None:
        """EnumCoreErrorCode has CONFIGURATION_ERROR value."""
        from omniclaude.lib.errors import EnumCoreErrorCode

        assert hasattr(EnumCoreErrorCode, "CONFIGURATION_ERROR")
        assert EnumCoreErrorCode.CONFIGURATION_ERROR is not None

    def test_operation_failed_exists(self) -> None:
        """EnumCoreErrorCode has OPERATION_FAILED value."""
        from omniclaude.lib.errors import EnumCoreErrorCode

        assert hasattr(EnumCoreErrorCode, "OPERATION_FAILED")
        assert EnumCoreErrorCode.OPERATION_FAILED is not None

    def test_error_codes_are_strings(self) -> None:
        """Error code values are string-based."""
        from omniclaude.lib.errors import EnumCoreErrorCode

        # EnumCoreErrorCode should be a StrEnum or have string values
        validation_error = EnumCoreErrorCode.VALIDATION_ERROR
        assert isinstance(validation_error.value, str) or isinstance(
            validation_error, str
        )


class TestModelOnexError:
    """Tests for ModelOnexError Pydantic model."""

    def test_can_instantiate_with_required_fields(self) -> None:
        """ModelOnexError can be instantiated with required fields."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError

        error = ModelOnexError(
            message="Test validation error",
            error_code=EnumCoreErrorCode.VALIDATION_ERROR,
        )
        # error_code is stored as the enum's value (string)
        assert EnumCoreErrorCode.VALIDATION_ERROR.value in str(error.error_code)
        assert error.message == "Test validation error"

    def test_can_instantiate_with_context(self) -> None:
        """ModelOnexError can be instantiated with additional context kwargs."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError

        error = ModelOnexError(
            message="Operation failed",
            error_code=EnumCoreErrorCode.OPERATION_FAILED,
            reason="timeout",
            duration_ms=5000,
        )
        assert error.message == "Operation failed"
        # Context is stored in error.context['additional_context']
        assert error.context is not None
        assert error.context["additional_context"]["reason"] == "timeout"
        assert error.context["additional_context"]["duration_ms"] == 5000

    def test_can_serialize_to_json(self) -> None:
        """ModelOnexError can be serialized to JSON."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError

        error = ModelOnexError(
            message="Missing configuration",
            error_code=EnumCoreErrorCode.CONFIGURATION_ERROR,
        )
        json_str = error.model_dump_json()
        assert "CONFIGURATION_ERROR" in json_str
        assert "Missing configuration" in json_str


class TestOnexError:
    """Tests for OnexError exception class."""

    def test_can_instantiate(self) -> None:
        """OnexError can be instantiated."""
        from omniclaude.lib.errors import OnexError

        error = OnexError("Test error message")
        assert str(error) == "Test error message"

    def test_is_exception(self) -> None:
        """OnexError is an Exception subclass."""
        from omniclaude.lib.errors import OnexError

        assert issubclass(OnexError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        """OnexError can be raised and caught properly."""
        from omniclaude.lib.errors import OnexError

        with pytest.raises(OnexError) as exc_info:
            raise OnexError("Test error for raising")

        assert "Test error for raising" in str(exc_info.value)

    def test_can_be_caught_as_exception(self) -> None:
        """OnexError can be caught as base Exception."""
        from omniclaude.lib.errors import OnexError

        caught = False
        try:
            raise OnexError("Catching as Exception")
        except Exception as e:
            caught = True
            assert isinstance(e, OnexError)

        assert caught

    def test_model_onex_error_and_onex_error_are_same_class(self) -> None:
        """ModelOnexError and OnexError are the same class (alias)."""
        from omniclaude.lib.errors import ModelOnexError, OnexError

        # They are the same class - OnexError is an alias for ModelOnexError
        assert ModelOnexError is OnexError

    def test_can_chain_with_cause(self) -> None:
        """OnexError can be chained with a cause using 'raise ... from'."""
        from omniclaude.lib.errors import OnexError

        original = ValueError("Original error")

        # Use proper exception chaining syntax
        with pytest.raises(OnexError) as exc_info:
            try:
                raise original
            except ValueError as e:
                raise OnexError("Wrapped error") from e

        assert exc_info.value.__cause__ is original
        assert "Wrapped error" in str(exc_info.value)


class TestErrorCodeUsage:
    """Tests for practical error code usage patterns."""

    def test_validation_error_workflow(self) -> None:
        """Validation error can be created and raised in typical workflow."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError, OnexError

        # Create structured error model with context kwargs
        error_model = ModelOnexError(
            message="Field 'name' is required",
            error_code=EnumCoreErrorCode.VALIDATION_ERROR,
            field="name",
            constraint="required",
        )

        # Raise as exception
        with pytest.raises(OnexError) as exc_info:
            raise OnexError(error_model.message)

        assert "name" in str(exc_info.value)
        assert "required" in str(exc_info.value)

    def test_configuration_error_workflow(self) -> None:
        """Configuration error can be created and raised in typical workflow."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError, OnexError

        error_model = ModelOnexError(
            message="KAFKA_BOOTSTRAP_SERVERS not configured",
            error_code=EnumCoreErrorCode.CONFIGURATION_ERROR,
            env_var="KAFKA_BOOTSTRAP_SERVERS",
        )

        with pytest.raises(OnexError) as exc_info:
            raise OnexError(error_model.message)

        assert "KAFKA_BOOTSTRAP_SERVERS" in str(exc_info.value)

    def test_operation_failed_workflow(self) -> None:
        """Operation failed error can be created and raised in typical workflow."""
        from omniclaude.lib.errors import EnumCoreErrorCode, ModelOnexError, OnexError

        error_model = ModelOnexError(
            message="Failed to connect to database",
            error_code=EnumCoreErrorCode.OPERATION_FAILED,
            host="localhost",
            port=5432,
            timeout_ms=5000,
        )

        with pytest.raises(OnexError) as exc_info:
            raise OnexError(error_model.message)

        assert "Failed to connect" in str(exc_info.value)

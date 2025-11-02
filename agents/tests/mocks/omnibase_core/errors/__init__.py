#!/usr/bin/env python3
"""
Mock omnibase_core.errors module for testing Phase 5 components
"""

from enum import Enum


class EnumCoreErrorCode(str, Enum):
    """Mock error codes for testing"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_INPUT = "INVALID_INPUT"
    OPERATION_FAILED = "OPERATION_FAILED"
    INITIALIZATION_ERROR = "INITIALIZATION_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"


# Alias for compatibility
CoreErrorCode = EnumCoreErrorCode


class OnexError(Exception):
    """Mock OnexError for testing"""

    def __init__(
        self,
        message: str = None,
        error_code: EnumCoreErrorCode | str | None = None,
        code: EnumCoreErrorCode | str | None = None,
        details: dict = None,
        **context,
    ):
        """
        Initialize mock ONEX error.

        Args:
            message: Error message
            error_code: Error code enum (optional, for compatibility)
            code: Error code enum (optional, preferred parameter)
            details: Error details dict (optional)
            **context: Additional context information
        """
        # Support both 'code' and 'error_code' parameters
        error_code = code or error_code

        self.message = message
        self.error_code = error_code
        self.code = error_code  # Alias for backward compatibility

        # Build context structure (matching production OnexError)
        # context.additional_context.details contains the error details
        self.details = details or {}
        self.context = context.copy()
        self.context["additional_context"] = {"details": self.details}
        super().__init__(message)

    def __str__(self):
        return (
            f"[{self.error_code}] {self.message}" if self.error_code else self.message
        )

    def __repr__(self):
        return f"OnexError(error_code={self.error_code}, message={self.message}, context={self.context})"


class ModelOnexError(OnexError):
    """Mock ModelOnexError for testing (alias for OnexError)"""

    def __init__(
        self,
        message: str,
        error_code: EnumCoreErrorCode | str | None = None,
        context: dict = None,
    ):
        """
        Initialize mock ModelOnexError.

        Args:
            message: Error message
            error_code: Error code enum (optional)
            context: Error context dictionary (stored in details for compatibility)
        """
        # Match production behavior: context parameter → details attribute
        # Wrap context in "context" key for test compatibility
        wrapped_details = {"context": context} if context else {}
        super().__init__(
            message=message, error_code=error_code, details=wrapped_details
        )

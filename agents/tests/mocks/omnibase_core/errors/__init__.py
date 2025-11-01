#!/usr/bin/env python3
"""
Mock omnibase_core.errors module for testing Phase 5 components
"""

from enum import Enum


class EnumCoreErrorCode(str, Enum):
    """Mock error codes for testing"""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    OPERATION_FAILED = "OPERATION_FAILED"
    INITIALIZATION_ERROR = "INITIALIZATION_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"


# Alias for compatibility
CoreErrorCode = EnumCoreErrorCode


class OnexError(Exception):
    """Mock OnexError for testing"""

    def __init__(self, code: EnumCoreErrorCode, message: str, details: dict = None):
        """
        Initialize mock ONEX error.

        Args:
            code: Error code enum
            message: Error message
            details: Optional error details dictionary
        """
        self.code = code
        self.message = message
        self.details = details or {}
        self.context = {"additional_context": {"details": self.details}}
        super().__init__(message)

    def __str__(self):
        return f"{self.code}: {self.message}"

    def __repr__(self):
        return f"OnexError(code={self.code}, message={self.message}, details={self.details})"


class ModelOnexError(OnexError):
    """Mock ModelOnexError for testing (alias for OnexError)"""

    def __init__(
        self, error_code: EnumCoreErrorCode, message: str, context: dict = None
    ):
        """
        Initialize mock ModelOnexError.

        Args:
            error_code: Error code enum
            message: Error message
            context: Optional error context dictionary
        """
        super().__init__(code=error_code, message=message, details=context)

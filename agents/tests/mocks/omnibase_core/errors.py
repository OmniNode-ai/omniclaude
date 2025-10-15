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


class OnexError(Exception):
    """Mock OnexError for testing"""

    def __init__(
        self,
        code: EnumCoreErrorCode,
        message: str,
        details: dict = None
    ):
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
        super().__init__(message)

    def __str__(self):
        return f"{self.code}: {self.message}"

    def __repr__(self):
        return f"OnexError(code={self.code}, message={self.message}, details={self.details})"

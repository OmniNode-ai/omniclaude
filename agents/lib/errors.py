#!/usr/bin/env python3
"""
Production-safe ONEX Error Handling

This module provides error codes and exception classes for ONEX-compliant
operations. It mirrors the omnibase_core.errors interface but is self-contained
for production deployment.
"""

from enum import Enum


class EnumCoreErrorCode(str, Enum):
    """
    Core error codes for ONEX operations.

    These error codes provide standardized error handling across
    all ONEX-compliant services and nodes.
    """

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
    """
    Base exception class for ONEX operations.

    Provides structured error handling with error codes, messages,
    and contextual details for debugging and monitoring.

    Attributes:
        code: Error code from EnumCoreErrorCode
        message: Human-readable error message
        details: Additional error context and details
        context: Nested context structure for compatibility
    """

    def __init__(self, code: EnumCoreErrorCode, message: str, details: dict = None):
        """
        Initialize ONEX error.

        Args:
            code: Error code enum
            message: Error message
            details: Optional error details dictionary
        """
        self.code = code
        self.error_code = code  # Alias for backward compatibility
        self.message = message
        self.details = details or {}
        self.context = {"additional_context": {"details": self.details}}
        super().__init__(message)

    def __str__(self):
        return f"{self.code}: {self.message}"

    def __repr__(self):
        return f"OnexError(code={self.code}, message={self.message}, details={self.details})"


class ModelOnexError(OnexError):
    """
    Model-specific ONEX error (alias for OnexError).

    Provides compatibility with omnibase_core.errors.ModelOnexError
    while maintaining the same error handling semantics.
    """

    def __init__(
        self, error_code: EnumCoreErrorCode, message: str, context: dict = None
    ):
        """
        Initialize model-specific ONEX error.

        Args:
            error_code: Error code enum
            message: Error message
            context: Optional error context dictionary
        """
        super().__init__(code=error_code, message=message, details=context)
        self.error_code = error_code  # Add error_code attribute for compatibility


__all__ = [
    "EnumCoreErrorCode",
    "CoreErrorCode",
    "OnexError",
    "ModelOnexError",
]

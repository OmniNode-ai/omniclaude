"""ONEX-compliant error handling for OmniClaude.

This module provides error codes and exception classes for ONEX-compliant
operations. It attempts to import from omnibase_core first, falling back
to local definitions if unavailable.

This module serves as the single source of truth for error handling across
all omniclaude modules, preventing duplicate class definitions.
"""

from __future__ import annotations

from typing import Any

# Try to import from omnibase_core (preferred source)
try:
    from omnibase_core.enums.enum_core_error_code import EnumCoreErrorCode
    from omnibase_core.errors import OnexError

    OMNIBASE_ERRORS_AVAILABLE = True
except ImportError:
    # Fallback: Try agents.lib.errors (legacy location)
    try:
        from agents.lib.errors import EnumCoreErrorCode, OnexError

        OMNIBASE_ERRORS_AVAILABLE = True
    except ImportError:
        # Final fallback: Define minimal error classes locally
        from enum import Enum

        OMNIBASE_ERRORS_AVAILABLE = False

        class EnumCoreErrorCode(str, Enum):  # type: ignore[no-redef]
            """Core error codes for ONEX operations.

            These error codes provide standardized error handling across
            all ONEX-compliant services and nodes.
            """

            # Generic validation errors
            VALIDATION_ERROR = "VALIDATION_ERROR"
            VALIDATION_FAILED = "VALIDATION_FAILED"
            INVALID_INPUT = "INVALID_INPUT"

            # Operation errors
            OPERATION_FAILED = "OPERATION_FAILED"
            INITIALIZATION_ERROR = "INITIALIZATION_ERROR"

            # Configuration errors
            CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
            DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
            EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"

            # File/IO errors
            FILE_NOT_FOUND = "FILE_NOT_FOUND"
            IO_ERROR = "IO_ERROR"

        class OnexError(Exception):  # type: ignore[no-redef]
            """Base exception class for ONEX operations.

            Provides structured error handling with error codes, messages,
            and contextual details for debugging and monitoring.

            Attributes:
                code: Error code from EnumCoreErrorCode
                error_code: Alias for code (backward compatibility)
                message: Human-readable error message
                details: Additional error context and details
            """

            def __init__(
                self,
                code: EnumCoreErrorCode,
                message: str,
                details: dict[str, Any] | None = None,
            ) -> None:
                """Initialize ONEX error.

                Args:
                    code: Error code enum
                    message: Error message
                    details: Optional error details dictionary
                """
                self.code = code
                self.error_code = code  # Alias for backward compatibility
                self.message = message
                self.details = details or {}
                super().__init__(message)

            def __str__(self) -> str:
                return f"{self.code}: {self.message}"

            def __repr__(self) -> str:
                return (
                    f"OnexError(code={self.code}, message={self.message}, details={self.details})"
                )


# Alias for compatibility with older code
CoreErrorCode = EnumCoreErrorCode


class ModelOnexError(OnexError):
    """Model-specific ONEX error (alias for OnexError).

    Provides compatibility with omnibase_core.errors.ModelOnexError
    while maintaining the same error handling semantics.
    """

    def __init__(
        self,
        error_code: EnumCoreErrorCode,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize model-specific ONEX error.

        Args:
            error_code: Error code enum
            message: Error message
            context: Optional error context dictionary
        """
        super().__init__(code=error_code, message=message, details=context)


__all__ = [
    "CoreErrorCode",
    "EnumCoreErrorCode",
    "ModelOnexError",
    "OnexError",
    "OMNIBASE_ERRORS_AVAILABLE",
]

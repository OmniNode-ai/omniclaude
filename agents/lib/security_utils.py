#!/usr/bin/env python3
"""
Security Utilities - Input Validation and Sanitization

This module provides security utilities for preventing common vulnerabilities
like SQL injection, command injection, and other input validation issues.

Created: 2025-11-17
Purpose: Centralized security validation for all OmniClaude components
"""

import re
from typing import Optional


def validate_sql_identifier(
    identifier: str, identifier_type: str = "identifier"
) -> None:
    """
    Validate SQL identifier to prevent SQL injection.

    Ensures the identifier (table/column name) only contains safe characters
    and follows PostgreSQL naming rules.

    Args:
        identifier: The identifier to validate (table or column name)
        identifier_type: Type of identifier for error messages (e.g., "table", "column")

    Raises:
        ValueError: If identifier contains invalid characters or is empty

    Security:
        This prevents SQL injection by validating that table and column names
        only contain alphanumeric characters, underscores, and don't start with
        numbers. While PostgreSQL allows quoted identifiers with any characters,
        this validation enforces a safe subset for security.

    Reference:
        https://www.postgresql.org/docs/current/sql-syntax-lexical.html#SQL-SYNTAX-IDENTIFIERS
        https://owasp.org/www-community/attacks/SQL_Injection

    Examples:
        >>> validate_sql_identifier("users", "table")  # OK
        >>> validate_sql_identifier("user_name", "column")  # OK
        >>> validate_sql_identifier("1invalid", "table")  # Raises ValueError
        >>> validate_sql_identifier("table'; DROP TABLE users;--", "table")  # Raises ValueError
    """
    if not identifier:
        raise ValueError(f"Empty {identifier_type} name")

    # PostgreSQL identifiers: alphanumeric + underscore, cannot start with digit
    # Max length 63 characters (PostgreSQL limit)
    if len(identifier) > 63:
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': exceeds 63 character limit"
        )

    # Must start with letter or underscore
    if not (identifier[0].isalpha() or identifier[0] == "_"):
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': must start with letter or underscore"
        )

    # Rest must be alphanumeric or underscore
    if not all(c.isalnum() or c == "_" for c in identifier):
        raise ValueError(
            f"Invalid {identifier_type} '{identifier}': only alphanumeric and underscore allowed"
        )


def validate_file_path(
    file_path: str, allowed_extensions: Optional[list] = None
) -> None:
    """
    Validate file path to prevent path traversal attacks.

    Args:
        file_path: The file path to validate
        allowed_extensions: Optional list of allowed file extensions (e.g., ['.json', '.txt'])

    Raises:
        ValueError: If file path contains invalid characters or attempts path traversal

    Security:
        Prevents path traversal attacks (e.g., "../../../etc/passwd")

    Reference:
        https://owasp.org/www-community/attacks/Path_Traversal

    Examples:
        >>> validate_file_path("data/file.json", ['.json'])  # OK
        >>> validate_file_path("../../../etc/passwd")  # Raises ValueError
    """
    if not file_path:
        raise ValueError("Empty file path")

    # Check for path traversal attempts
    if ".." in file_path:
        raise ValueError(f"Invalid file path '{file_path}': path traversal not allowed")

    # Check for absolute paths (optional - may want to allow in some contexts)
    if file_path.startswith("/"):
        raise ValueError(f"Invalid file path '{file_path}': absolute paths not allowed")

    # Validate extension if provided
    if allowed_extensions:
        if not any(file_path.endswith(ext) for ext in allowed_extensions):
            raise ValueError(
                f"Invalid file path '{file_path}': must have one of {allowed_extensions}"
            )


def sanitize_log_message(message: str, max_length: int = 10000) -> str:
    """
    Sanitize log message to prevent log injection attacks.

    Args:
        message: The log message to sanitize
        max_length: Maximum allowed length (default: 10000)

    Returns:
        Sanitized message with newlines and special characters removed

    Security:
        Prevents log injection attacks where attackers insert newlines to forge log entries

    Reference:
        https://owasp.org/www-community/attacks/Log_Injection

    Examples:
        >>> sanitize_log_message("Normal message")
        'Normal message'
        >>> sanitize_log_message("Message with\\nnewline")
        'Message with newline'
    """
    if not message:
        return ""

    # Truncate to max length
    if len(message) > max_length:
        message = message[:max_length] + "... (truncated)"

    # Remove newlines and carriage returns
    message = message.replace("\n", " ").replace("\r", " ")

    # Remove null bytes
    message = message.replace("\x00", "")

    return message

"""
Environment Variable Configuration Validator.

Provides startup validation for required environment variables to prevent cryptic
runtime failures. This module implements a fail-fast validation pattern that
checks all required environment variables and provides clear, actionable error
messages when configuration is incomplete.

Usage:
    >>> from agents.lib.config_validator import validate_required_env_vars
    >>>
    >>> # Validate at application startup
    >>> try:
    ...     validate_required_env_vars()
    ... except EnvironmentError as e:
    ...     print(f"Configuration error: {e}")
    ...     sys.exit(1)
    >>>
    >>> # Validate with custom required vars
    >>> custom_vars = ["MY_API_KEY", "MY_SERVICE_URL"]
    >>> validate_required_env_vars(additional_vars=custom_vars)

Validation Strategy:
1. Check all required environment variables in a single pass
2. Collect ALL missing variables (not just first failure)
3. Provide clear error message listing missing variables
4. Guide users to check .env file for configuration

Required Environment Variables:
    POSTGRES_HOST: PostgreSQL server hostname
    POSTGRES_PORT: PostgreSQL server port
    POSTGRES_PASSWORD: PostgreSQL authentication password
    KAFKA_BOOTSTRAP_SERVERS: Kafka broker addresses
    QDRANT_URL: Qdrant vector database URL

Created: 2025-11-03
Reference: PR #20 - Environment validation improvements
Pattern: Fail-fast validation with comprehensive error reporting
"""

import os
import sys
from typing import List, Optional

# Import Pydantic Settings for type-safe configuration validation
try:
    from config import settings

    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False

# =============================================================================
# Required Environment Variables
# =============================================================================

REQUIRED_ENV_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_PASSWORD",
    "KAFKA_BOOTSTRAP_SERVERS",
    "QDRANT_URL",
]


# =============================================================================
# Validation Functions
# =============================================================================


def validate_required_env_vars(
    additional_vars: Optional[List[str]] = None,
    strict: bool = True,
) -> None:
    """
    Validate that all required environment variables are set.

    This function implements fail-fast validation by checking all required
    environment variables at application startup. It collects ALL missing
    variables and provides a comprehensive error message listing each one,
    making it easier for users to identify and fix configuration issues.

    The validation follows the fail-fast pattern: detect configuration errors
    immediately at startup rather than encountering cryptic runtime failures
    later in execution.

    Args:
        additional_vars: Optional list of additional required variables to check
        strict: If True, raises exception on missing vars. If False, prints
                warning and continues (useful for development)

    Raises:
        EnvironmentError: If any required environment variables are missing
                         (only when strict=True)

    Example:
        >>> # Basic validation at startup
        >>> validate_required_env_vars()

        >>> # Validate with additional service-specific variables
        >>> validate_required_env_vars(additional_vars=["OPENAI_API_KEY"])

        >>> # Non-strict mode for development
        >>> validate_required_env_vars(strict=False)

    Note:
        - Missing POSTGRES_PASSWORD is a common issue. Ensure .env file
          contains: POSTGRES_PASSWORD=<your_password>
        - KAFKA_BOOTSTRAP_SERVERS format: host:port (e.g., 192.168.86.200:9092)
        - QDRANT_URL format: http://host:port (e.g., from settings.qdrant_url)
        - Consider using the Pydantic settings module (config.settings) for type-safe access
    """
    # Use Pydantic Settings validation if available (more comprehensive)
    if SETTINGS_AVAILABLE:
        try:
            validation_errors = settings.validate_required_services()
            if validation_errors:
                error_message = "\n".join(
                    [
                        "Required configuration variables are missing or invalid:",
                        "",
                    ]
                    + [f"  - {error}" for error in validation_errors]
                    + [
                        "",
                        "Check your .env file and ensure all required variables are set.",
                        "See config/README.md for complete configuration reference.",
                    ]
                )

                if strict:
                    raise EnvironmentError(error_message)
                else:
                    print(f"⚠️  WARNING: {error_message}", file=sys.stderr)
                return
        except Exception as e:
            # If Pydantic validation fails, fall back to os.getenv checks
            print(
                f"⚠️  Pydantic Settings validation failed: {e}. Falling back to environment variable checks.",
                file=sys.stderr,
            )

    # Fallback: Check environment variables directly
    vars_to_check = REQUIRED_ENV_VARS.copy()
    if additional_vars:
        vars_to_check.extend(additional_vars)

    # Check all variables and collect missing ones
    missing = [var for var in vars_to_check if not os.getenv(var)]

    if missing:
        error_message = _format_validation_error(missing)

        if strict:
            raise EnvironmentError(error_message)
        else:
            print(f"⚠️  WARNING: {error_message}", file=sys.stderr)


def validate_env_var_format(var_name: str, expected_format: str) -> None:
    """
    Validate that an environment variable has the expected format.

    This function checks not just that a variable exists, but that it
    conforms to the expected format (e.g., URL, host:port, etc.).

    Args:
        var_name: Name of the environment variable to validate
        expected_format: Description of expected format (e.g., "host:port")

    Raises:
        EnvironmentError: If variable is missing or format is invalid

    Example:
        >>> validate_env_var_format("KAFKA_BOOTSTRAP_SERVERS", "host:port")
        >>> validate_env_var_format("QDRANT_URL", "http://host:port")
    """
    value = os.getenv(var_name)

    if not value:
        raise EnvironmentError(
            f"Environment variable '{var_name}' is required.\n"
            f"Expected format: {expected_format}\n"
            f"Please check your .env file."
        )

    # Format-specific validation
    if expected_format == "host:port":
        if ":" not in value:
            raise EnvironmentError(
                f"Invalid format for '{var_name}': {value}\n"
                f"Expected format: {expected_format}\n"
                f"Example: 192.168.86.200:9092"
            )
    elif expected_format.startswith("http://"):
        if not value.startswith("http://") and not value.startswith("https://"):
            raise EnvironmentError(
                f"Invalid format for '{var_name}': {value}\n"
                f"Expected format: {expected_format}\n"
                f"Example: Use settings.qdrant_url from Pydantic settings"
            )


def get_env_var_with_validation(
    var_name: str,
    default: Optional[str] = None,
    required: bool = True,
) -> Optional[str]:
    """
    Get environment variable with validation and optional default.

    This function provides a safe way to retrieve environment variables
    with explicit handling of missing values and defaults.

    Args:
        var_name: Name of the environment variable to retrieve
        default: Default value if variable is not set (None if not provided)
        required: If True, raises exception when variable is missing and
                 no default is provided

    Returns:
        Environment variable value or default

    Raises:
        EnvironmentError: If variable is required but missing and no default
                         is provided

    Example:
        >>> # Get required variable
        >>> host = get_env_var_with_validation("POSTGRES_HOST")

        >>> # Get optional variable with default
        >>> port = get_env_var_with_validation("POSTGRES_PORT", default="5432")

        >>> # Get optional variable without error
        >>> key = get_env_var_with_validation("API_KEY", required=False)
    """
    value = os.getenv(var_name)

    if value is not None:
        return value

    if default is not None:
        return default

    if required:
        raise EnvironmentError(
            f"Environment variable '{var_name}' is required but not set.\n"
            f"Please check your .env file and ensure this variable is configured."
        )

    return None


# =============================================================================
# Helper Functions
# =============================================================================


def _format_validation_error(missing_vars: List[str]) -> str:
    """
    Format validation error message with helpful guidance.

    Args:
        missing_vars: List of missing environment variable names

    Returns:
        Formatted error message with guidance for users
    """
    var_count = len(missing_vars)
    var_list = "\n  • ".join(missing_vars)

    error_message = (
        f"Missing {var_count} required environment variable{'s' if var_count > 1 else ''}:\n"
        f"  • {var_list}\n\n"
        f"Configuration required:\n"
        f"  1. Copy .env.example to .env: cp .env.example .env\n"
        f"  2. Set missing variables in .env file\n"
        f"  3. Source environment: source .env\n"
        f"  4. Restart application\n\n"
        f"For detailed configuration instructions, see:\n"
        f"  • CLAUDE.md (Environment Configuration section)\n"
        f"  • ~/.claude/CLAUDE.md (Shared Infrastructure section)"
    )

    return error_message


def _check_common_issues() -> List[str]:
    """
    Check for common configuration issues and return warnings.

    Returns:
        List of warning messages for common configuration issues
    """
    warnings = []

    # Check if .env file exists
    if not os.path.exists(".env"):
        warnings.append(".env file not found. Copy .env.example to .env and configure.")

    # Check POSTGRES_PASSWORD specifically (common issue)
    if not os.getenv("POSTGRES_PASSWORD"):
        warnings.append("POSTGRES_PASSWORD not set. Database operations will fail.")

    # Check KAFKA_BOOTSTRAP_SERVERS format
    kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if kafka_servers and ":" not in kafka_servers:
        warnings.append(
            f"KAFKA_BOOTSTRAP_SERVERS format may be incorrect: {kafka_servers}\n"
            f"Expected format: host:port (e.g., 192.168.86.200:9092)"
        )

    # Check QDRANT_URL format
    qdrant_url = os.getenv("QDRANT_URL")
    if qdrant_url and not (
        qdrant_url.startswith("http://") or qdrant_url.startswith("https://")
    ):
        warnings.append(
            f"QDRANT_URL format may be incorrect: {qdrant_url}\n"
            f"Expected format: http://host:port\n"
            f"Note: Consider using Pydantic settings (config.settings.qdrant_url)"
        )

    return warnings


def validate_with_diagnostics(
    additional_vars: Optional[List[str]] = None,
    strict: bool = True,
) -> None:
    """
    Validate environment variables with enhanced diagnostics.

    This function performs the same validation as validate_required_env_vars()
    but also checks for common configuration issues and provides additional
    diagnostic information.

    Args:
        additional_vars: Optional list of additional required variables to check
        strict: If True, raises exception on missing vars. If False, prints
                warning and continues

    Raises:
        EnvironmentError: If any required environment variables are missing
                         (only when strict=True)

    Example:
        >>> # Validate with enhanced diagnostics
        >>> validate_with_diagnostics()
    """
    # Run standard validation
    validate_required_env_vars(additional_vars=additional_vars, strict=strict)

    # Check for common issues
    warnings = _check_common_issues()
    if warnings:
        print("\n⚠️  Configuration warnings:", file=sys.stderr)
        for warning in warnings:
            print(f"  • {warning}", file=sys.stderr)
        print()


# =============================================================================
# Module Initialization
# =============================================================================


if __name__ == "__main__":
    """
    Run validation diagnostics when module is executed directly.

    Usage:
        python3 agents/lib/config_validator.py
    """
    print("=== Environment Configuration Validator ===\n")

    try:
        validate_with_diagnostics(strict=False)
        print("✅ All required environment variables are set.\n")
    except EnvironmentError as e:
        print(f"❌ Configuration error:\n{e}\n")
        sys.exit(1)

    # Display current configuration
    print("Current configuration:")
    for var in REQUIRED_ENV_VARS:
        value = os.getenv(var)
        if value:
            # Mask passwords
            if "PASSWORD" in var or "KEY" in var:
                display_value = "***" + value[-4:] if len(value) > 4 else "***"
            else:
                display_value = value
            print(f"  ✓ {var}: {display_value}")
        else:
            print(f"  ✗ {var}: NOT SET")

    print("\n✅ Validation complete.")

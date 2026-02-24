# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Environment variable validation for production environments.

This module provides functions to detect production environments and
validate that required environment variables are set.
"""

import os
import sys


def is_production_environment() -> bool:
    """
    Detect if running in production environment.

    Checks multiple common environment variable patterns for production detection.

    Returns:
        True if in production, False otherwise (dev/local/test)
    """
    env = os.getenv("ENVIRONMENT", "").lower()
    deployment_env = os.getenv("DEPLOYMENT_ENV", "").lower()
    env_type = os.getenv("ENV", "").lower()

    # Check common environment variable patterns
    return any(
        [
            env == "production",
            env == "prod",
            deployment_env == "production",
            deployment_env == "prod",
            env_type == "production",
            env_type == "prod",
        ]
    )


def validate_required_env_vars(console, required_vars: dict[str, str]) -> None:
    """
    Validate that required environment variables are set in production.

    In production environments, all database connection parameters must be
    explicitly configured. Fallback values are not allowed to prevent
    accidental connections to incorrect databases.

    In development/local environments, fallback values are permitted.

    Args:
        console: Rich Console instance for formatted output
        required_vars: Dictionary mapping variable names to descriptions

    Raises:
        SystemExit: If required variables are missing in production
    """
    if not is_production_environment():
        # In development, fallbacks are allowed
        return

    missing_vars = []
    for var_name, description in required_vars.items():
        if not os.getenv(var_name):
            missing_vars.append(f"  - {var_name}: {description}")

    if missing_vars:
        console.print(
            "[red bold]❌ Production Environment Configuration Error[/red bold]\n"
        )
        console.print("[red]Required environment variables are missing:[/red]\n")
        console.print("\n".join(missing_vars))
        console.print("\n[yellow]Action required:[/yellow]")
        console.print("  1. Set the missing environment variables")
        console.print("  2. Ensure .env file is properly configured")
        console.print("  3. Run: source .env")
        console.print(
            "\n[dim]Note: Fallback values are not allowed in production environments[/dim]"
        )
        sys.exit(1)

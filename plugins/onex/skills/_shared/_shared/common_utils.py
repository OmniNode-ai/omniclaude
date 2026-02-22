#!/usr/bin/env python3
"""
Common Utilities - Shared helper functions across all skill modules.

This module centralizes common functionality to avoid code duplication
across kafka_helper.py, docker_helper.py, qdrant_helper.py, and others.

Provides:
- Timeout configuration from Pydantic Settings
- Other shared utilities (to be added as needed)

Usage:
    from common_utils import get_timeout_seconds

Created: 2025-11-28
"""

import os

from omniclaude.config import settings


def get_timeout_seconds(override_seconds: int | None = None) -> float:
    """
    Get timeout value in seconds from type-safe configuration.

    Returns timeout from Pydantic Settings (default: 5 seconds).
    Configurable via REQUEST_TIMEOUT_MS environment variable.

    Args:
        override_seconds: Optional custom timeout in seconds. If provided,
                         this value takes precedence over configuration.
                         Useful for long-running operations that need
                         extended timeouts.

    Returns:
        Timeout in seconds (float)

    Note:
        Timeout strategy: All helper subprocess/network calls use the same
        timeout to prevent infinite hangs. Default is 5 seconds, configurable
        via .env file (REQUEST_TIMEOUT_MS=5000). Valid range: 100-60000ms.

        Use override_seconds for specific operations that require longer
        timeouts (e.g., generate-status-report --timeout 30).

        Priority order:
        1. override_seconds parameter (highest priority)
        2. OPERATION_TIMEOUT_OVERRIDE environment variable (for CLI scripts)
        3. REQUEST_TIMEOUT_MS from Pydantic Settings (default)
    """
    if override_seconds is not None:
        return float(override_seconds)

    # Check for operation-specific timeout override (for CLI scripts)
    env_override = os.getenv("OPERATION_TIMEOUT_OVERRIDE")
    if env_override is not None:
        try:
            return float(env_override)
        except (ValueError, TypeError):
            pass  # Fall through to default

    return settings.request_timeout_ms / 1000.0

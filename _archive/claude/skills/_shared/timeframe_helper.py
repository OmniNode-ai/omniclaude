#!/usr/bin/env python3
"""
Timeframe Helper - Shared timeframe parsing logic

Provides utilities for converting shorthand timeframe codes to PostgreSQL intervals.
This module provides SQL-safe timeframe parsing with whitelist-based validation
to prevent SQL injection attacks.

Created: 2025-11-16
Updated: 2025-11-21 - Added get_valid_timeframes() and is_valid_timeframe()
"""

import logging

logger = logging.getLogger(__name__)

# Whitelist of valid timeframe mappings (SQL injection protection)
VALID_INTERVALS = {
    "5m": "5 minutes",
    "15m": "15 minutes",
    "1h": "1 hour",
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
}


def parse_timeframe(timeframe: str) -> str:
    """
    Validate and convert timeframe to SQL-safe interval string.

    This function implements SQL injection protection by validating user input
    against a whitelist of allowed timeframe values before using them in SQL queries.

    Args:
        timeframe: User-provided timeframe string (e.g., "5m", "1h", "7d")

    Returns:
        SQL-safe PostgreSQL interval string (e.g., "5 minutes", "1 hour", "7 days")

    Raises:
        ValueError: If timeframe is not in the whitelist of valid values

    Examples:
        >>> parse_timeframe("5m")
        '5 minutes'
        >>> parse_timeframe("1h")
        '1 hour'
        >>> parse_timeframe("30d")
        '30 days'
        >>> parse_timeframe("unknown")
        Traceback (most recent call last):
            ...
        ValueError: Unsupported timeframe: unknown. Valid options: 15m, 1h, 24h, 30d, 5m, 7d
        >>> parse_timeframe("1h'; DROP TABLE--")
        Traceback (most recent call last):
            ...
        ValueError: Unsupported timeframe: 1h'; DROP TABLE--. Valid options: 15m, 1h, 24h, 30d, 5m, 7d
    """
    interval = VALID_INTERVALS.get(timeframe)
    if not interval:
        valid_options = ", ".join(sorted(VALID_INTERVALS.keys()))
        raise ValueError(
            f"Unsupported timeframe: {timeframe}. Valid options: {valid_options}"
        )

    return interval


def get_valid_timeframes() -> list[str]:
    """Get list of valid timeframe options.

    Returns:
        Sorted list of valid timeframe strings (e.g., ["5m", "15m", "1h", "24h", "7d", "30d"])

    Examples:
        >>> get_valid_timeframes()
        ['15m', '1h', '24h', '30d', '5m', '7d']
    """
    return sorted(VALID_INTERVALS.keys())


def is_valid_timeframe(timeframe: str) -> bool:
    """Check if a timeframe is valid without raising an exception.

    Args:
        timeframe: Timeframe string to validate

    Returns:
        True if timeframe is valid, False otherwise

    Examples:
        >>> is_valid_timeframe("1h")
        True
        >>> is_valid_timeframe("30d")
        True
        >>> is_valid_timeframe("invalid")
        False
        >>> is_valid_timeframe("1h'; DROP TABLE--")
        False
    """
    return timeframe in VALID_INTERVALS

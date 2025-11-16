#!/usr/bin/env python3
"""
Timeframe Helper - Shared timeframe parsing logic

Provides utilities for converting shorthand timeframe codes to PostgreSQL intervals.

Created: 2025-11-16
"""

from typing import Optional


def parse_timeframe(timeframe: str, default: Optional[str] = None) -> str:
    """
    Convert shorthand timeframe string to PostgreSQL interval.

    Args:
        timeframe: Shorthand code (e.g., "5m", "1h", "7d")
        default: Optional PostgreSQL interval to return if code not found.
                 If None, returns "1 hour" by default.

    Returns:
        PostgreSQL interval string (e.g., "5 minutes", "1 hour", "7 days")

    Examples:
        >>> parse_timeframe("5m")
        '5 minutes'
        >>> parse_timeframe("1h")
        '1 hour'
        >>> parse_timeframe("unknown")
        '1 hour'
        >>> parse_timeframe("unknown", default="5 minutes")
        '5 minutes'
    """
    mapping = {
        "5m": "5 minutes",
        "15m": "15 minutes",
        "1h": "1 hour",
        "24h": "24 hours",
        "7d": "7 days",
    }

    fallback = default if default is not None else "1 hour"
    return mapping.get(timeframe, fallback)

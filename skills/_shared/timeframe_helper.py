#!/usr/bin/env python3
"""
Timeframe Helper - Shared timeframe parsing logic

Provides utilities for converting shorthand timeframe codes to PostgreSQL intervals.

Created: 2025-11-16
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def parse_timeframe(timeframe: str) -> str:
    """
    Convert shorthand timeframe string to PostgreSQL interval.

    Args:
        timeframe: Shorthand code (e.g., "5m", "1h", "7d")

    Returns:
        PostgreSQL interval string (e.g., "5 minutes", "1 hour", "7 days")

    Raises:
        ValueError: If timeframe is not a valid code

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
        ValueError: Unsupported timeframe: unknown. Valid options: 5m, 15m, 1h, 24h, 7d, 30d
    """
    mapping = {
        "5m": "5 minutes",
        "15m": "15 minutes",
        "1h": "1 hour",
        "24h": "24 hours",
        "7d": "7 days",
        "30d": "30 days",
    }

    if timeframe not in mapping:
        raise ValueError(
            f"Unsupported timeframe: {timeframe}. "
            f"Valid options: {', '.join(mapping.keys())}"
        )

    return mapping[timeframe]

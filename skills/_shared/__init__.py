"""
Shared utilities for Claude Code skills.

Provides reusable infrastructure helpers for database, Kafka, Docker, Qdrant,
and common utilities like timeframe parsing and status formatting.
"""

# Import commonly used utilities for convenience
from .constants import (
    DEFAULT_ACTIVITY_LIMIT,
    DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    DEFAULT_LOG_LINES,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_TOP_AGENTS,
    MAX_CONNECTIONS_THRESHOLD,
    MAX_CONTAINERS_DISPLAY,
    MAX_LIMIT,
    MAX_LOG_LINES,
    MAX_RECENT_ERRORS_DISPLAY,
    MAX_RESTART_COUNT_THRESHOLD,
    MAX_TOP_AGENTS,
    MIN_DIVISOR,
    MIN_LIMIT,
    MIN_LOG_LINES,
    MIN_TOP_AGENTS,
    PERCENT_MULTIPLIER,
    QUERY_TIMEOUT_THRESHOLD_MS,
    ROUTING_TIMEOUT_THRESHOLD_MS,
)
from .status_formatter import (
    format_bytes,
    format_duration,
    format_json,
    format_markdown_table,
    format_percentage,
    format_status_indicator,
    format_status_summary,
    format_table,
    format_timestamp,
    generate_markdown_report,
)
from .timeframe_helper import (
    VALID_INTERVALS,
    get_valid_timeframes,
    is_valid_timeframe,
    parse_timeframe,
)


__version__ = "1.0.0"
__all__ = [
    "VALID_INTERVALS",
    "parse_timeframe",
    "get_valid_timeframes",
    "is_valid_timeframe",
    "format_json",
    "format_status_indicator",
    "format_table",
    "format_markdown_table",
    "format_status_summary",
    "format_percentage",
    "format_duration",
    "format_bytes",
    "format_timestamp",
    "generate_markdown_report",
]

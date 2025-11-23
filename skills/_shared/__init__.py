"""
Shared utilities for Claude Code skills.

Provides reusable infrastructure helpers for database, Kafka, Docker, Qdrant,
and common utilities like timeframe parsing and status formatting.

Usage:
    # Import specific helpers
    from skills._shared import get_db_connection, execute_query
    from skills._shared import check_kafka_connection, list_topics
    from skills._shared import list_containers, get_container_status
    from skills._shared import check_qdrant_connection, list_collections
    from skills._shared import format_percentage, format_timestamp

    # Or import the module
    from skills import _shared
    result = _shared.execute_query("SELECT * FROM users")

Modules:
    - db_helper: PostgreSQL connection and query utilities
    - kafka_helper: Kafka connectivity, topic listing, message sampling
    - docker_helper: Container status, health checks, resource monitoring
    - qdrant_helper: Vector database connectivity and collection management
    - timeframe_helper: Timeframe parsing and validation
    - status_formatter: Output formatting (JSON, tables, percentages, bytes)
    - constants: Shared constants and thresholds
"""

# Database helper (PostgreSQL)
# Constants
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
from .db_helper import (
    execute_query,
    get_connection,
    get_connection_pool,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
    release_connection,
    test_connection,
)

# Docker helper
from .docker_helper import (
    check_container_health,
    get_container_logs,
    get_container_stats,
    get_container_status,
    get_service_summary,
    list_containers,
)

# Kafka helper
from .kafka_helper import (
    check_kafka_connection,
    check_topic_exists,
    get_consumer_groups,
    get_kafka_bootstrap_servers,
    get_recent_message_count,
    get_timeout_command,
    get_timeout_seconds,
    get_topic_stats,
    list_topics,
)

# Qdrant helper
from .qdrant_helper import (
    check_collection_exists,
    check_qdrant_connection,
    get_all_collections_stats,
    get_collection_health,
    get_collection_stats,
    get_qdrant_url,
    list_collections,
    validate_qdrant_url,
)

# Status formatter
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

# Timeframe helper
from .timeframe_helper import (
    VALID_INTERVALS,
    get_valid_timeframes,
    is_valid_timeframe,
    parse_timeframe,
)


__version__ = "1.0.0"
__all__ = [
    # Database helpers
    "get_connection_pool",
    "get_connection",
    "release_connection",
    "execute_query",
    "get_correlation_id",
    "handle_db_error",
    "test_connection",
    "parse_json_param",
    # Kafka helpers
    "get_timeout_seconds",
    "get_kafka_bootstrap_servers",
    "get_timeout_command",
    "check_kafka_connection",
    "list_topics",
    "get_topic_stats",
    "get_consumer_groups",
    "check_topic_exists",
    "get_recent_message_count",
    # Docker helpers
    "list_containers",
    "get_container_status",
    "check_container_health",
    "get_container_stats",
    "get_container_logs",
    "get_service_summary",
    # Qdrant helpers
    "validate_qdrant_url",
    "get_qdrant_url",
    "check_qdrant_connection",
    "list_collections",
    "get_collection_stats",
    "get_all_collections_stats",
    "check_collection_exists",
    "get_collection_health",
    # Constants
    "DEFAULT_ACTIVITY_LIMIT",
    "DEFAULT_CONNECTION_TIMEOUT_SECONDS",
    "DEFAULT_LOG_LINES",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "DEFAULT_TOP_AGENTS",
    "MAX_CONNECTIONS_THRESHOLD",
    "MAX_CONTAINERS_DISPLAY",
    "MAX_LIMIT",
    "MAX_LOG_LINES",
    "MAX_RECENT_ERRORS_DISPLAY",
    "MAX_RESTART_COUNT_THRESHOLD",
    "MAX_TOP_AGENTS",
    "MIN_DIVISOR",
    "MIN_LIMIT",
    "MIN_LOG_LINES",
    "MIN_TOP_AGENTS",
    "PERCENT_MULTIPLIER",
    "QUERY_TIMEOUT_THRESHOLD_MS",
    "ROUTING_TIMEOUT_THRESHOLD_MS",
    # Status formatters
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
    # Timeframe helpers
    "VALID_INTERVALS",
    "parse_timeframe",
    "get_valid_timeframes",
    "is_valid_timeframe",
]

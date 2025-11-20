"""Shared constants for system-status skills.

This module centralizes all magic numbers to improve maintainability.
Adjust thresholds here to tune system behavior globally.

Created: 2025-11-20
"""

# =============================================================================
# Performance Thresholds
# =============================================================================

# PostgreSQL connection pool warning threshold (out of 100 max connections)
# Alerts when active connections exceed this value
# Adjust: Increase if you have a larger connection pool configured
MAX_CONNECTIONS_THRESHOLD: int = 80

# Slow query warning threshold (milliseconds)
# Manifest injections taking longer than this trigger warnings
# Adjust: Based on your p95 latency requirements
QUERY_TIMEOUT_THRESHOLD_MS: int = 5000

# Slow routing warning threshold (milliseconds)
# Agent routing decisions taking longer than this trigger warnings
# Target: <100ms for good user experience
ROUTING_TIMEOUT_THRESHOLD_MS: int = 100

# Container restart count threshold
# Containers restarting more than this many times trigger warnings
# Indicates potential crash loops or stability issues
MAX_RESTART_COUNT_THRESHOLD: int = 5

# =============================================================================
# Display Limits
# =============================================================================

# Maximum containers to show in status reports
# Prevents overwhelming output in large deployments
MAX_CONTAINERS_DISPLAY: int = 20

# Default number of top agents to display
# Used when --top-agents not specified
DEFAULT_TOP_AGENTS: int = 10

# Maximum number of recent errors to show
# Limits error output to most recent N entries
MAX_RECENT_ERRORS_DISPLAY: int = 5

# Default number of log lines to retrieve
# Balance between context and performance
DEFAULT_LOG_LINES: int = 50

# Default activity limit
# Number of recent activity records to show
DEFAULT_ACTIVITY_LIMIT: int = 20

# =============================================================================
# Input Validation Bounds
# =============================================================================

# Limit parameter bounds (for --limit flags)
MIN_LIMIT: int = 1
MAX_LIMIT: int = 1000

# Log lines parameter bounds (for --log-lines flags)
MIN_LOG_LINES: int = 1
MAX_LOG_LINES: int = 10000

# Top agents parameter bounds (for --top-agents flags)
MIN_TOP_AGENTS: int = 1
MAX_TOP_AGENTS: int = 100

# =============================================================================
# Mathematical Constants
# =============================================================================

# Percentage multiplier (converts 0.95 -> 95%)
PERCENT_MULTIPLIER: int = 100

# Minimum divisor to avoid division by zero
# Used when calculating percentage changes
MIN_DIVISOR: int = 1

# =============================================================================
# Timeouts (seconds)
# =============================================================================

# Default request timeout for external services
DEFAULT_REQUEST_TIMEOUT_SECONDS: int = 5

# Default connection timeout for database/infrastructure
DEFAULT_CONNECTION_TIMEOUT_SECONDS: int = 10

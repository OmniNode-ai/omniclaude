# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
# Display Precision (decimal places)
# =============================================================================

# Decimal places for routing time display (e.g., 7.8 ms)
ROUTING_TIME_DECIMALS: int = 1

# Decimal places for confidence score display (e.g., 0.92)
CONFIDENCE_DECIMALS: int = 2

# =============================================================================
# Timeouts (seconds)
# =============================================================================

# Default request timeout for external services
DEFAULT_REQUEST_TIMEOUT_SECONDS: int = 5

# Default connection timeout for database/infrastructure
DEFAULT_CONNECTION_TIMEOUT_SECONDS: int = 10

# =============================================================================
# Exit Codes
# =============================================================================

# Success exit code - no issues found
EXIT_SUCCESS: int = 0

# Warning exit code - non-critical issues found
EXIT_WARNING: int = 1

# Critical exit code - critical issues found requiring immediate attention
EXIT_CRITICAL: int = 2

# Error exit code - diagnostic/execution failed
EXIT_ERROR: int = 3

# =============================================================================
# PostgreSQL Thresholds
# =============================================================================

# Default PostgreSQL max_connections value (fallback when SHOW max_connections fails)
# PostgreSQL default is 100, but many installations increase this
DEFAULT_POSTGRES_MAX_CONNECTIONS: int = 100

# Connection pool warning threshold (percentage)
# Triggers warning when active connections exceed this percentage of max_connections
CONN_POOL_WARNING_THRESHOLD_PCT: int = 60

# Connection pool critical threshold (percentage)
# Triggers critical alert when active connections exceed this percentage
CONN_POOL_CRITICAL_THRESHOLD_PCT: int = 80

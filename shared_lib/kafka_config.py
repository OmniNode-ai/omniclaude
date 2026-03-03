#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Centralized Kafka Configuration

Single source of truth for Kafka broker configuration across all OmniClaude services.
Used by: agent-tracking skills, intelligence services, consumers, hooks.

This module eliminates tech debt from duplicate fallback logic across 8+ services
by providing a single, consistent way to resolve Kafka bootstrap servers.

Usage:
    from lib.kafka_config import get_kafka_bootstrap_servers

    brokers = get_kafka_bootstrap_servers()
    # Returns: "localhost:19092" if KAFKA_BOOTSTRAP_SERVERS is unset (bus_local default)

Integration:
    - agent-tracking skills (log-routing-decision, log-agent-action, etc.)
    - intelligence services (request-intelligence)
    - event clients (intelligence_event_client)
    - consumers and hooks

Environment Variable Priority:
    1. KAFKA_BOOTSTRAP_SERVERS (general config)
    2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)
    3. KAFKA_BROKERS (legacy compatibility)
    4. Default: localhost:19092 (bus_local — local Docker Redpanda, OMN-3431)

Two-bus policy (OMN-3431):
    bus_local (default): localhost:19092  — local Docker Redpanda, always-on
    bus_cloud:           localhost:29092  — cloud Kafka via launchd tunnel

Created: 2025-10-28
Version: 1.1.0
Correlation ID: cec9c22e-0944-4eae-9f9f-08803f056aeb
"""

import logging
import os
import warnings

_log = logging.getLogger(__name__)

_BUS_LOCAL_DEFAULT = "localhost:19092"


def get_kafka_bootstrap_servers() -> str:
    """
    Get Kafka bootstrap servers from environment with proper fallback chain.

    Centralizes Kafka broker resolution, eliminating duplicate fallback logic
    across all OmniClaude services.

    Priority order:
    1. KAFKA_BOOTSTRAP_SERVERS (general config)
    2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)
    3. KAFKA_BROKERS (legacy compatibility)
    4. Default: localhost:19092 (bus_local — local Docker Redpanda, OMN-3431)

    Returns:
        str: Comma-separated bootstrap servers (e.g., "localhost:19092")

    Examples:
        >>> # With no environment variables set (warns and returns bus_local default)
        >>> get_kafka_bootstrap_servers()
        'localhost:19092'

        >>> # With KAFKA_BOOTSTRAP_SERVERS set
        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:19092'
        >>> get_kafka_bootstrap_servers()
        'localhost:19092'

        >>> # Cloud bus (activate with: bus-cloud in shell)
        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:29092'
        >>> get_kafka_bootstrap_servers()
        'localhost:29092'

    Notes:
        - Returns a string suitable for both kafka-python and confluent-kafka
        - For list format, use get_kafka_bootstrap_servers_list()
        - Logs a warning when falling back to the default (bus_local)
        - bus_local: localhost:19092 (local Docker Redpanda, always-on)
        - bus_cloud: localhost:29092 (cloud Kafka via launchd tunnel, activate with bus-cloud)
    """
    result = (
        os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        or os.environ.get("KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS")
        or os.environ.get("KAFKA_BROKERS")
    )
    if result:
        return result
    default = _BUS_LOCAL_DEFAULT
    _log.warning(
        "KAFKA_BOOTSTRAP_SERVERS not set — defaulting to %s (bus_local). "
        "Set KAFKA_BOOTSTRAP_SERVERS=localhost:19092 (bus_local) or "
        "localhost:29092 (bus_cloud).",
        default,
    )
    warnings.warn(
        f"KAFKA_BOOTSTRAP_SERVERS not set — using bus_local default {default}.",
        stacklevel=2,
    )
    return default


def get_kafka_bootstrap_servers_list() -> list[str]:
    """
    Get Kafka bootstrap servers as list (for confluent-kafka).

    Some Kafka clients expect bootstrap servers as a list instead of a
    comma-separated string. This function provides that format.

    Returns:
        List[str]: List of bootstrap server addresses

    Examples:
        >>> get_kafka_bootstrap_servers_list()
        ['localhost:19092']

        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:19092,localhost:19093'
        >>> get_kafka_bootstrap_servers_list()
        ['localhost:19092', 'localhost:19093']

    Notes:
        - Suitable for confluent-kafka Consumer/Producer configuration
        - Automatically splits comma-separated values
    """
    return get_kafka_bootstrap_servers().split(",")


# For backward compatibility with direct imports
# Example: from lib.kafka_config import KAFKA_BOOTSTRAP_SERVERS
KAFKA_BOOTSTRAP_SERVERS = get_kafka_bootstrap_servers()


__all__ = [
    "get_kafka_bootstrap_servers",
    "get_kafka_bootstrap_servers_list",
    "KAFKA_BOOTSTRAP_SERVERS",
]

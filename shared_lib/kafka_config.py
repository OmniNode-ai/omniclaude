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
    # Returns: "192.168.86.200:29092" (or value from environment)

Integration:
    - agent-tracking skills (log-routing-decision, log-agent-action, etc.)
    - intelligence services (request-intelligence)
    - event clients (intelligence_event_client)
    - consumers and hooks

Environment Variable Priority:
    1. KAFKA_BOOTSTRAP_SERVERS (general config)
    2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)
    3. KAFKA_BROKERS (legacy compatibility)
    4. Default: 192.168.86.200:29092 (external port for host scripts)

Created: 2025-10-28
Version: 1.0.0
Correlation ID: cec9c22e-0944-4eae-9f9f-08803f056aeb
"""

import os


def get_kafka_bootstrap_servers() -> str:
    """
    Get Kafka bootstrap servers from environment with proper fallback chain.

    This function provides a single source of truth for Kafka broker configuration,
    eliminating duplicate fallback logic across all OmniClaude services.

    Priority order:
    1. KAFKA_BOOTSTRAP_SERVERS (general config)
    2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)
    3. KAFKA_BROKERS (legacy compatibility)
    4. Default: 192.168.86.200:29092 (external port for host scripts)

    Returns:
        str: Comma-separated bootstrap servers (e.g., "192.168.86.200:9092")

    Examples:
        >>> # With no environment variables set
        >>> get_kafka_bootstrap_servers()
        '192.168.86.200:29092'

        >>> # With KAFKA_BOOTSTRAP_SERVERS set
        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:9092'
        >>> get_kafka_bootstrap_servers()
        'localhost:9092'

        >>> # With multiple brokers
        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = '192.168.86.200:29092,192.168.86.201:29092'
        >>> get_kafka_bootstrap_servers()
        '192.168.86.200:29092,192.168.86.201:29092'

    Notes:
        - Returns a string suitable for both kafka-python and confluent-kafka
        - For list format, use get_kafka_bootstrap_servers_list()
        - Default broker uses external port 29092 for host scripts (port 9092 is internal Docker only)
    """
    return (
        os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
        or os.environ.get("KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS")
        or os.environ.get("KAFKA_BROKERS")
        or "192.168.86.200:29092"
    )


def get_kafka_bootstrap_servers_list() -> list[str]:
    """
    Get Kafka bootstrap servers as list (for confluent-kafka).

    Some Kafka clients expect bootstrap servers as a list instead of a
    comma-separated string. This function provides that format.

    Returns:
        List[str]: List of bootstrap server addresses

    Examples:
        >>> get_kafka_bootstrap_servers_list()
        ['192.168.86.200:29092']

        >>> os.environ['KAFKA_BOOTSTRAP_SERVERS'] = 'localhost:9092,localhost:9093'
        >>> get_kafka_bootstrap_servers_list()
        ['localhost:9092', 'localhost:9093']

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

#!/usr/bin/env python3
"""
Kafka Helper - Shared utilities for Kafka operations

Provides functions for:
- Kafka connectivity checking
- Topic listing and stats
- Consumer group status
- Message throughput monitoring

Usage:
    from kafka_helper import check_kafka_connection, list_topics, get_consumer_lag

Created: 2025-11-12
"""

import json
import subprocess
from typing import Any, Dict, List, Optional

# Import type-safe configuration (Phase 2 - Pydantic Settings migration)
from config import settings


def get_kafka_bootstrap_servers() -> str:
    """
    Get Kafka bootstrap servers from type-safe configuration.

    Uses Pydantic Settings framework for validated configuration.
    Raises ValueError if KAFKA_BOOTSTRAP_SERVERS is not properly configured.

    Returns:
        Bootstrap server address (e.g., "192.168.86.200:29092" for host scripts
        or "omninode-bridge-redpanda:9092" for Docker services)

    Raises:
        ValueError: If KAFKA_BOOTSTRAP_SERVERS is not set in environment

    Note:
        Configuration context matters:
        - Docker services: Use "omninode-bridge-redpanda:9092"
        - Host scripts: Use "192.168.86.200:29092"
        Set via KAFKA_BOOTSTRAP_SERVERS in .env file
    """
    bootstrap = settings.get_effective_kafka_bootstrap_servers()

    if not bootstrap:
        raise ValueError(
            "KAFKA_BOOTSTRAP_SERVERS not configured. "
            "Set KAFKA_BOOTSTRAP_SERVERS in .env file. "
            "Use 'omninode-bridge-redpanda:9092' for Docker services "
            "or '192.168.86.200:29092' for host scripts. "
            "See CLAUDE.md for deployment context details."
        )

    return bootstrap


def check_kafka_connection() -> Dict[str, Any]:
    """
    Check if Kafka is reachable and responsive.

    Returns:
        Dictionary with connection status and metadata
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        # Use kcat to test connection
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode == 0:
            return {
                "status": "connected",
                "broker": bootstrap_servers,
                "reachable": True,
                "error": None,
            }
        else:
            return {
                "status": "error",
                "broker": bootstrap_servers,
                "reachable": False,
                "error": result.stderr.strip(),
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": "Connection timeout after 5s",
        }
    except FileNotFoundError:
        return {
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": "kcat command not found. Install with: brew install kcat",
        }
    except Exception as e:
        return {
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": str(e),
        }


def list_topics() -> Dict[str, Any]:
    """
    List all Kafka topics.

    Returns:
        Dictionary with topic list and count
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "topics": [],
                "count": 0,
                "error": result.stderr.strip(),
            }

        # Parse topic names from output
        topics = []
        for line in result.stdout.split("\n"):
            if 'topic "' in line:
                # Extract topic name between quotes
                start = line.find('topic "') + 7
                end = line.find('"', start)
                if end > start:
                    topics.append(line[start:end])

        return {"success": True, "topics": topics, "count": len(topics), "error": None}
    except Exception as e:
        return {"success": False, "topics": [], "count": 0, "error": str(e)}


def get_topic_stats(topic_name: str) -> Dict[str, Any]:
    """
    Get statistics for a specific topic.

    Args:
        topic_name: Name of the topic

    Returns:
        Dictionary with topic statistics
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers, "-t", topic_name],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "topic": topic_name,
                "error": result.stderr.strip(),
            }

        # Parse partition count from output
        partitions = 0
        for line in result.stdout.split("\n"):
            if "partition" in line.lower() and topic_name in line:
                partitions += 1

        return {
            "success": True,
            "topic": topic_name,
            "partitions": partitions,
            "error": None,
        }
    except Exception as e:
        return {"success": False, "topic": topic_name, "error": str(e)}


def get_consumer_groups() -> Dict[str, Any]:
    """
    List all consumer groups.

    Returns:
        Dictionary with consumer group list
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if result.returncode != 0:
            return {
                "success": False,
                "groups": [],
                "count": 0,
                "error": result.stderr.strip(),
            }

        # Note: kcat -L doesn't show consumer groups
        # This would require kafka-consumer-groups command or admin API
        # For now, return placeholder
        return {
            "success": True,
            "groups": [],
            "count": 0,
            "error": "Consumer group listing requires kafka-consumer-groups command",
        }
    except Exception as e:
        return {"success": False, "groups": [], "count": 0, "error": str(e)}


def check_topic_exists(topic_name: str) -> bool:
    """
    Check if a topic exists.

    Args:
        topic_name: Name of the topic to check

    Returns:
        True if topic exists, False otherwise
    """
    topics_result = list_topics()
    if not topics_result["success"]:
        return False

    return topic_name in topics_result["topics"]


def get_recent_message_count(
    topic_name: str, timeout_seconds: int = 2
) -> Dict[str, Any]:
    """
    Get count of recent messages in a topic (sample).

    Args:
        topic_name: Name of the topic
        timeout_seconds: How long to consume messages (default: 2s)

    Returns:
        Dictionary with message count estimate
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        # Consume from end for a short time to estimate throughput
        result = subprocess.run(
            [
                "timeout",
                str(timeout_seconds),
                "kcat",
                "-C",
                "-b",
                bootstrap_servers,
                "-t",
                topic_name,
                "-o",
                "end",
                "-e",
            ],
            capture_output=True,
            text=True,
        )

        # Count lines (each line is a message)
        message_count = len(
            [line for line in result.stdout.split("\n") if line.strip()]
        )

        return {
            "success": True,
            "topic": topic_name,
            "messages_sampled": message_count,
            "sample_duration_s": timeout_seconds,
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "topic": topic_name,
            "messages_sampled": 0,
            "error": str(e),
        }


if __name__ == "__main__":
    # Test kafka helper functions
    print("Testing Kafka Helper...")
    print("\n1. Checking Kafka connection...")
    conn = check_kafka_connection()
    print(json.dumps(conn, indent=2))

    print("\n2. Listing topics...")
    topics = list_topics()
    print(json.dumps(topics, indent=2))

    if topics["success"] and topics["count"] > 0:
        test_topic = topics["topics"][0]
        print(f"\n3. Getting stats for topic: {test_topic}")
        stats = get_topic_stats(test_topic)
        print(json.dumps(stats, indent=2))

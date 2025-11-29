#!/usr/bin/env python3
"""
Kafka Helper - Shared utilities for Kafka operations

Provides functions for:
- Kafka connectivity checking
- Topic listing and stats
- Consumer group status
- Message throughput monitoring

All functions follow a standardized API contract with TypedDict return values.
See kafka_types.py for complete API documentation.

Example:
    from kafka_helper import check_kafka_connection, list_topics, get_topic_stats

    # Check Kafka connectivity
    connection = check_kafka_connection()
    if connection["success"] and connection["reachable"]:
        # List available topics
        topics = list_topics()
        print(f"Found {topics['count']} topics")

        # Get stats for specific topic
        stats = get_topic_stats("my-topic")
        if stats["success"]:
            print(f"Partitions: {stats['partitions']}")

Created: 2025-11-12
Updated: 2025-11-23 - Added standardized type hints and API contract
"""

import json
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional


# Import standardized Kafka result types (same package)
try:
    from .kafka_types import (
        KafkaConnectionResult,
        KafkaConsumerGroupsResult,
        KafkaMessageCountResult,
        KafkaTopicsResult,
        KafkaTopicStatsResult,
    )
except ImportError:
    from kafka_types import (
        KafkaConnectionResult,
        KafkaConsumerGroupsResult,
        KafkaMessageCountResult,
        KafkaTopicsResult,
        KafkaTopicStatsResult,
    )

# Add project root for config module (type-safe Pydantic Settings) and ONEX errors
# Path: claude/skills/_shared/ -> claude/skills/ -> claude/ -> project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Import shared timeout utility using relative import (same package)
# Fallback to absolute import for direct script execution
try:
    from .common_utils import get_timeout_seconds
except ImportError:
    from common_utils import get_timeout_seconds

from config import settings


# ONEX-compliant error handling
# Try to import from agents.lib.errors, fallback to local definitions
try:
    from agents.lib.errors import EnumCoreErrorCode, OnexError
except ImportError:
    # Fallback: Define locally if import fails (for standalone usage)
    from enum import Enum as FallbackEnum

    class EnumCoreErrorCode(str, FallbackEnum):  # type: ignore[no-redef]
        """Core error codes for ONEX operations."""

        CONFIGURATION_ERROR = "CONFIGURATION_ERROR"

    class OnexError(Exception):  # type: ignore[no-redef]
        """Base exception class for ONEX operations."""

        def __init__(
            self,
            code: EnumCoreErrorCode,
            message: str,
            details: dict | None = None,
        ):
            self.code = code
            self.error_code = code
            self.message = message
            self.details = details or {}
            super().__init__(message)

        def __str__(self):
            return f"{self.code}: {self.message}"


def get_kafka_bootstrap_servers() -> str:
    """
    Get Kafka bootstrap servers from type-safe configuration.

    Uses Pydantic Settings framework for validated configuration.
    Raises OnexError if KAFKA_BOOTSTRAP_SERVERS is not properly configured.

    Returns:
        Bootstrap server address (e.g., "192.168.86.200:29092" for host scripts
        or "omninode-bridge-redpanda:9092" for Docker services)

    Raises:
        OnexError: If KAFKA_BOOTSTRAP_SERVERS is not set in environment
            (code: CONFIGURATION_ERROR)

    Note:
        Configuration context matters:
        - Docker services: Use "omninode-bridge-redpanda:9092"
        - Host scripts: Use "192.168.86.200:29092"
        Set via KAFKA_BOOTSTRAP_SERVERS in .env file
    """
    bootstrap = settings.get_effective_kafka_bootstrap_servers()

    if not bootstrap:
        raise OnexError(
            code=EnumCoreErrorCode.CONFIGURATION_ERROR,
            message=(
                "KAFKA_BOOTSTRAP_SERVERS not configured. "
                "Set KAFKA_BOOTSTRAP_SERVERS in .env file. "
                "Use 'omninode-bridge-redpanda:9092' for Docker services "
                "or '192.168.86.200:29092' for host scripts. "
                "See CLAUDE.md for deployment context details."
            ),
            details={
                "setting": "KAFKA_BOOTSTRAP_SERVERS",
                "docker_value": "omninode-bridge-redpanda:9092",
                "host_value": "192.168.86.200:29092",
            },
        )

    return bootstrap


def get_timeout_command() -> str:
    """
    Get platform-specific timeout command.

    Returns:
        "gtimeout" on macOS (Darwin), "timeout" on Linux

    Note:
        macOS requires GNU coreutils: brew install coreutils
        Provides gtimeout command for shell timeout operations.
        Linux has timeout built-in from coreutils package.
    """
    return "gtimeout" if platform.system() == "Darwin" else "timeout"


def check_kafka_connection() -> KafkaConnectionResult:
    """
    Check if Kafka is reachable and responsive.

    Returns:
        KafkaConnectionResult with:
        - success: True if connected, False otherwise
        - status: Connection status ("connected", "error", "timeout")
        - broker: Bootstrap server address
        - reachable: Whether broker is reachable
        - error: Error message on failure, None on success
        - return_code: Process return code if applicable

    Example:
        >>> result = check_kafka_connection()
        >>> if result["success"] and result["reachable"]:
        ...     print(f"Connected to {result['broker']}")
        ... else:
        ...     print(f"Connection failed: {result['error']}")
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        # Use kcat to test connection
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode == 0:
            return {
                "success": True,
                "status": "connected",
                "broker": bootstrap_servers,
                "reachable": True,
                "error": None,
                "return_code": 0,
            }
        else:
            return {
                "success": False,
                "status": "error",
                "broker": bootstrap_servers,
                "reachable": False,
                "error": result.stderr.strip(),
                "return_code": result.returncode,
            }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "status": "timeout",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": f"Connection timeout after {get_timeout_seconds()}s",
            "return_code": 1,
        }
    except FileNotFoundError:
        install_instructions = (
            "kcat command not found. "
            "Install: macOS: 'brew install kcat' | "
            "Ubuntu/Debian: 'sudo apt-get install kafkacat' | "
            "Alpine/Docker: 'apk add kafkacat' | "
            "See deployment/README.md for details"
        )
        return {
            "success": False,
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": install_instructions,
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def list_topics() -> KafkaTopicsResult:
    """
    List all Kafka topics.

    Returns:
        KafkaTopicsResult with:
        - success: True if topics retrieved, False otherwise
        - topics: List of topic names (empty list on failure)
        - count: Number of topics found
        - error: Error message on failure, None on success
        - return_code: Process return code if applicable

    Example:
        >>> result = list_topics()
        >>> if result["success"]:
        ...     print(f"Found {result['count']} topics: {result['topics']}")
        ... else:
        ...     print(f"Failed to list topics: {result['error']}")
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "topics": [],
                "count": 0,
                "error": f"kcat failed: {result.stderr.strip()}",
                "return_code": result.returncode,
            }

        # Parse topic names from output using regex for robustness
        topics = []
        for line in result.stdout.split("\n"):
            # Use regex to extract topic name (handles format changes gracefully)
            match = re.search(r'topic "([^"]+)"', line)
            if match:
                topic_name = match.group(1)
                topics.append(topic_name)

        return {
            "success": True,
            "topics": topics,
            "count": len(topics),
            "error": None,
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "topics": [],
            "count": 0,
            "error": f"kcat timed out after {get_timeout_seconds()}s (Kafka unreachable?)",
            "return_code": 1,
        }
    except FileNotFoundError:
        install_instructions = (
            "kcat command not found. "
            "Install: macOS: 'brew install kcat' | "
            "Ubuntu/Debian: 'sudo apt-get install kafkacat' | "
            "Alpine/Docker: 'apk add kafkacat' | "
            "See deployment/README.md for details"
        )
        return {
            "success": False,
            "topics": [],
            "count": 0,
            "error": install_instructions,
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "topics": [],
            "count": 0,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def get_topic_stats(topic_name: str) -> KafkaTopicStatsResult:
    """
    Get statistics for a specific topic.

    Args:
        topic_name: Name of the topic

    Returns:
        KafkaTopicStatsResult with:
        - success: True if stats retrieved, False otherwise
        - topic: Topic name
        - partitions: Number of partitions
        - error: Error message on failure, None on success
        - return_code: Process return code if applicable

    Example:
        >>> result = get_topic_stats("my-topic")
        >>> if result["success"]:
        ...     print(f"Topic '{result['topic']}' has {result['partitions']} partitions")
        ... else:
        ...     print(f"Failed to get stats: {result['error']}")
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers, "-t", topic_name],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "topic": topic_name,
                "partitions": 0,
                "error": f"kcat failed: {result.stderr.strip()}",
                "return_code": result.returncode,
            }

        # Parse partition count from output
        # kcat format: topic "name" with X partitions:
        #              partition 0, leader ...
        # Extract partition count directly from the "with X partitions:" line
        partitions = 0
        for line in result.stdout.split("\n"):
            # Match: topic "topic-name" with X partitions:
            match = re.search(
                rf'topic "{re.escape(topic_name)}" with (\d+) partitions?:', line
            )
            if match:
                partitions = int(match.group(1))
                break

        return {
            "success": True,
            "topic": topic_name,
            "partitions": partitions,
            "error": None,
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "topic": topic_name,
            "partitions": 0,
            "error": f"kcat timed out after {get_timeout_seconds()}s (Kafka unreachable?)",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "topic": topic_name,
            "partitions": 0,
            "error": "kcat not installed. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "topic": topic_name,
            "partitions": 0,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
        }


def get_consumer_groups() -> KafkaConsumerGroupsResult:
    """
    List all consumer groups.

    Returns:
        KafkaConsumerGroupsResult with:
        - success: True if groups retrieved, False otherwise
        - groups: List of consumer group names (empty list on failure)
        - count: Number of consumer groups found
        - error: Error message on failure, None on success
        - implemented: Whether the operation is implemented (False for placeholder)
        - return_code: Process return code if applicable

    Note:
        This operation is not yet fully implemented.
        Requires kafka-consumer-groups command or Kafka Admin API.

    Example:
        >>> result = get_consumer_groups()
        >>> if result["success"] and result["implemented"]:
        ...     print(f"Found {result['count']} consumer groups")
        ... elif not result["implemented"]:
        ...     print("Consumer group listing not yet implemented")
        ... else:
        ...     print(f"Failed: {result['error']}")
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        result = subprocess.run(
            ["kcat", "-L", "-b", bootstrap_servers],
            capture_output=True,
            text=True,
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "groups": [],
                "count": 0,
                "error": f"kcat failed: {result.stderr.strip()}",
                "implemented": False,
                "return_code": result.returncode,
            }

        # Note: kcat -L doesn't show consumer groups
        # This would require kafka-consumer-groups command or admin API
        # For now, return placeholder
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": "Consumer group listing not yet implemented (requires kafka-consumer-groups command or Kafka Admin API)",
            "implemented": False,
            "return_code": 1,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": f"kcat timed out after {get_timeout_seconds()}s (Kafka unreachable?)",
            "implemented": False,
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": "kcat not installed. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
            "implemented": False,
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": f"Subprocess error: {str(e)}",
            "implemented": False,
            "return_code": 1,
        }


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
) -> KafkaMessageCountResult:
    """
    Get count of recent messages in a topic (sample).

    Args:
        topic_name: Name of the topic
        timeout_seconds: How long to consume messages (default: 2s)

    Returns:
        KafkaMessageCountResult with:
        - success: True if operation succeeded, False otherwise
        - topic: Topic name
        - messages_sampled: Number of messages found (0 on failure)
        - sample_duration_s: Sampling duration in seconds
        - error: Error message on failure, None on success
        - return_code: Process return code if applicable

    Note:
        Distinguishes between:
        - "0 messages found" (success=True, messages_sampled=0)
        - "operation failed" (success=False, error contains details)

    Example:
        >>> result = get_recent_message_count("my-topic", timeout_seconds=5)
        >>> if result["success"]:
        ...     print(f"Found {result['messages_sampled']} messages in {result['sample_duration_s']}s")
        ... else:
        ...     print(f"Failed to sample messages: {result['error']}")
    """
    bootstrap_servers = get_kafka_bootstrap_servers()

    try:
        # Consume from end for a short time to estimate throughput
        # Use Python's built-in timeout for cross-platform compatibility
        result = subprocess.run(
            [
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
            timeout=timeout_seconds,
        )

        # Check if kcat command failed (non-zero exit code)
        if result.returncode != 0:
            return {
                "success": False,
                "topic": topic_name,
                "messages_sampled": 0,
                "sample_duration_s": timeout_seconds,
                "error": f"kcat failed (exit {result.returncode}): {result.stderr.strip()}",
                "return_code": result.returncode,
            }

        # Check stderr for connection/broker errors even when returncode is 0
        # kcat may exit 0 but report broker issues in stderr
        stderr_lower = result.stderr.lower()
        error_indicators = [
            "failed to connect",
            "connection refused",
            "no brokers",
            "broker transport failure",
            "all broker connections are down",
            "timed out",
            "authentication failure",
            "sasl authentication",
        ]
        for indicator in error_indicators:
            if indicator in stderr_lower:
                return {
                    "success": False,
                    "topic": topic_name,
                    "messages_sampled": 0,
                    "sample_duration_s": timeout_seconds,
                    "error": f"kcat connection error: {result.stderr.strip()}",
                    "return_code": result.returncode,
                }

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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        # Timeout occurred - kcat didn't complete in time (likely broker unreachable)
        return {
            "success": False,
            "topic": topic_name,
            "messages_sampled": 0,
            "sample_duration_s": timeout_seconds,
            "error": f"kcat timed out after {timeout_seconds}s (broker may be unreachable)",
            "return_code": 1,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "topic": topic_name,
            "messages_sampled": 0,
            "sample_duration_s": timeout_seconds,
            "error": "kcat command not found. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
            "return_code": 1,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "topic": topic_name,
            "messages_sampled": 0,
            "sample_duration_s": timeout_seconds,
            "error": f"Subprocess error: {str(e)}",
            "return_code": 1,
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

#!/usr/bin/env python3
"""
Kafka Helper - Shared utilities for Kafka operations

Provides functions for:
- Kafka connectivity checking
- Topic listing and stats
- Consumer group status
- Message throughput monitoring

Example:
    from kafka_helper import check_kafka_connection, list_topics, get_topic_stats

    # Check Kafka connectivity
    connection = check_kafka_connection()
    if connection["reachable"]:
        # List available topics
        topics = list_topics()
        print(f"Found {topics['count']} topics")

        # Get stats for specific topic
        stats = get_topic_stats("my-topic")
        print(f"Partitions: {stats['partitions']}")

Created: 2025-11-12
"""

import json
import os
import platform
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional


# Import type-safe configuration (Phase 2 - Pydantic Settings migration)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from config import settings


def get_timeout_seconds(override_seconds: Optional[int] = None) -> float:
    """
    Get timeout value in seconds from type-safe configuration.

    Returns timeout from Pydantic Settings (default: 5 seconds).
    Configurable via REQUEST_TIMEOUT_MS environment variable.

    Args:
        override_seconds: Optional custom timeout in seconds. If provided,
                         this value takes precedence over configuration.
                         Useful for long-running operations that need
                         extended timeouts.

    Returns:
        Timeout in seconds (float)

    Note:
        Timeout strategy: All helper subprocess/network calls use the same
        timeout to prevent infinite hangs. Default is 5 seconds, configurable
        via .env file (REQUEST_TIMEOUT_MS=5000). Valid range: 100-60000ms.

        Use override_seconds for specific operations that require longer
        timeouts (e.g., generate-status-report --timeout 30).

        Priority order:
        1. override_seconds parameter (highest priority)
        2. OPERATION_TIMEOUT_OVERRIDE environment variable (for CLI scripts)
        3. REQUEST_TIMEOUT_MS from Pydantic Settings (default)
    """
    if override_seconds is not None:
        return float(override_seconds)

    # Check for operation-specific timeout override (for CLI scripts)
    env_override = os.getenv("OPERATION_TIMEOUT_OVERRIDE")
    if env_override is not None:
        try:
            return float(env_override)
        except (ValueError, TypeError):
            pass  # Fall through to default

    return settings.request_timeout_ms / 1000.0


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
            timeout=get_timeout_seconds(),
        )

        if result.returncode == 0:
            return {
                "status": "connected",
                "broker": bootstrap_servers,
                "reachable": True,
                "error": None,
                "return_code": 0,
            }
        else:
            return {
                "status": "error",
                "broker": bootstrap_servers,
                "reachable": False,
                "error": result.stderr.strip(),
                "return_code": result.returncode,
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": f"Connection timeout after {get_timeout_seconds()}s",
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
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": install_instructions,
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "status": "error",
            "broker": bootstrap_servers,
            "reachable": False,
            "error": f"Subprocess error: {str(e)}",
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
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "topics": [],
            "count": 0,
            "error": f"Subprocess error: {str(e)}",
        }


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
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "topic": topic_name,
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
            "error": f"kcat timed out after {get_timeout_seconds()}s (Kafka unreachable?)",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "topic": topic_name,
            "error": "kcat not installed. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "topic": topic_name,
            "error": f"Subprocess error: {str(e)}",
        }


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
            timeout=get_timeout_seconds(),
        )

        if result.returncode != 0:
            return {
                "success": False,
                "groups": [],
                "count": 0,
                "error": f"kcat failed: {result.stderr.strip()}",
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
            "return_code": 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": f"kcat timed out after {get_timeout_seconds()}s (Kafka unreachable?)",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": "kcat not installed. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
        }
    except (subprocess.SubprocessError, OSError) as e:
        # SubprocessError: subprocess-related failures
        # OSError: system-level errors (permissions, resource limits, etc.)
        return {
            "success": False,
            "groups": [],
            "count": 0,
            "error": f"Subprocess error: {str(e)}",
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
) -> Dict[str, Any]:
    """
    Get count of recent messages in a topic (sample).

    Args:
        topic_name: Name of the topic
        timeout_seconds: How long to consume messages (default: 2s)

    Returns:
        Dictionary with message count estimate. Always includes:
        - success: bool - True only when kcat executed successfully
        - topic: str - Topic name
        - messages_sampled: int - Number of messages found (0 on failure)
        - sample_duration_s: int - Sampling duration
        - error: Optional[str] - Error message if success is False
        - return_code: Optional[int] - kcat exit code (None for non-kcat errors)

    Note:
        Distinguishes between:
        - "0 messages found" (success=True, messages_sampled=0)
        - "kcat failed" (success=False, error contains details)
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
            "return_code": None,
        }
    except FileNotFoundError:
        return {
            "success": False,
            "topic": topic_name,
            "messages_sampled": 0,
            "sample_duration_s": timeout_seconds,
            "error": "kcat command not found. Install: macOS: 'brew install kcat' | Ubuntu/Debian: 'sudo apt-get install kafkacat'",
            "return_code": None,
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
            "return_code": None,
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

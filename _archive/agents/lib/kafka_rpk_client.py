#!/usr/bin/env python3
"""
Redpanda rpk-based Kafka client (workaround for advertised listener issues).

Uses docker exec with rpk CLI to publish/consume messages.
More reliable than Python Kafka clients when dealing with Docker-mapped ports.

All methods follow standardized API contract with TypedDict return values.
See kafka_types.py for complete API documentation.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Import standardized Kafka result types
# Add _shared to path for skills compatibility
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "skills" / "_shared"))
from kafka_types import KafkaConsumeResult, KafkaPublishResult


class RpkKafkaClient:
    """
    Kafka client using Redpanda rpk CLI via docker exec.

    Workaround for advertised listener issues with confluent-kafka and aiokafka
    when connecting to Redpanda running in Docker with port mapping.
    """

    def __init__(self, container_name: str = "omninode-bridge-redpanda") -> None:
        """
        Initialize rpk client.

        Args:
            container_name: Docker container name for Redpanda

        Raises:
            RuntimeError: If docker executable is not available
        """
        self.container_name = container_name

        # Verify docker is available
        try:
            subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                check=True,
                timeout=5,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                "Docker executable not found in PATH. "
                "RpkKafkaClient requires docker to be installed and accessible. "
                "Set KAFKA_ENABLE_LOGGING=false to disable Kafka event publishing."
            ) from e
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Docker is installed but not functional: {e}") from e
        except subprocess.TimeoutExpired:
            raise RuntimeError("Docker check timed out. Docker may not be running.")

    def publish(self, topic: str, payload: dict[str, Any]) -> KafkaPublishResult:
        """
        Publish message to Kafka topic using rpk.

        Args:
            topic: Kafka topic name
            payload: Message payload (will be JSON-encoded)

        Returns:
            KafkaPublishResult with:
            - success: True if message published, False otherwise
            - topic: Topic name
            - data: Publish metadata on success (None for rpk - metadata not easily parsable)
            - error: Error message on failure, None on success

        Example:
            >>> client = RpkKafkaClient("omninode-bridge-redpanda")
            >>> result = client.publish("my-topic", {"key": "value"})
            >>> if result["success"]:
            ...     print("Message published successfully")
            ... else:
            ...     print(f"Publish failed: {result['error']}")
        """
        data = json.dumps(payload)

        try:
            # Use rpk to produce message
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-i",
                    self.container_name,
                    "rpk",
                    "topic",
                    "produce",
                    topic,
                ],
                input=data.encode("utf-8"),
                capture_output=True,
                check=True,
                timeout=10,
            )

            # Parse output to verify success
            # rpk sends success output to stdout, errors to stderr
            # Success format: "Produced to partition N at offset M with timestamp T."
            if result.returncode == 0:
                return {
                    "success": True,
                    "topic": topic,
                    "data": None,  # rpk output not easily parsable for metadata
                    "error": None,
                }
            else:
                # This shouldn't happen due to check=True, but handle anyway
                output = result.stdout.decode("utf-8") if result.stdout else ""
                error = result.stderr.decode("utf-8") if result.stderr else ""
                return {
                    "success": False,
                    "topic": topic,
                    "data": None,
                    "error": f"rpk failed with code {result.returncode}: {output} {error}",
                }

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode("utf-8") if e.stderr else str(e)
            return {
                "success": False,
                "topic": topic,
                "data": None,
                "error": f"rpk publish failed: {error_msg}",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "topic": topic,
                "data": None,
                "error": "rpk publish timed out after 10 seconds",
            }
        except Exception as e:
            return {
                "success": False,
                "topic": topic,
                "data": None,
                "error": f"rpk publish error: {str(e)}",
            }

    def consume_one(self, topic: str, timeout_sec: float = 10.0) -> KafkaConsumeResult:
        """
        Consume one message from topic.

        Args:
            topic: Kafka topic name
            timeout_sec: Timeout in seconds

        Returns:
            KafkaConsumeResult with:
            - success: True if message consumed or no message available, False on error
            - topic: Topic name
            - data: Message payload on success, None if no message or error
            - error: Error message on failure, None on success
            - timeout: True if no message within timeout, False otherwise

        Example:
            >>> client = RpkKafkaClient("omninode-bridge-redpanda")
            >>> result = client.consume_one("my-topic", timeout_sec=5.0)
            >>> if result["success"] and result["data"]:
            ...     print(f"Received: {result['data']}")
            ... elif result.get("timeout"):
            ...     print("No message available within timeout")
            ... else:
            ...     print(f"Consume failed: {result['error']}")
        """
        try:
            # Use rpk to consume one message
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    "rpk",
                    "topic",
                    "consume",
                    topic,
                    "--num",
                    "1",
                    "--offset",
                    "end",
                    "--format",
                    "%v",
                ],
                capture_output=True,
                check=True,
                timeout=timeout_sec,
            )

            output = result.stdout.decode("utf-8").strip()
            if output:
                try:
                    data = json.loads(output)
                    return {
                        "success": True,
                        "topic": topic,
                        "data": data,
                        "error": None,
                        "timeout": False,
                    }
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "topic": topic,
                        "data": None,
                        "error": f"JSON decode error: {str(e)}",
                        "timeout": False,
                    }
            else:
                # No message available
                return {
                    "success": True,
                    "topic": topic,
                    "data": None,
                    "error": None,
                    "timeout": False,
                }

        except subprocess.TimeoutExpired:
            # No message within timeout
            return {
                "success": True,
                "topic": topic,
                "data": None,
                "error": None,
                "timeout": True,
            }
        except subprocess.CalledProcessError as e:
            # Topic doesn't exist or other rpk error
            error_msg = e.stderr.decode("utf-8") if e.stderr else str(e)
            return {
                "success": False,
                "topic": topic,
                "data": None,
                "error": f"rpk consume failed: {error_msg}",
                "timeout": False,
            }
        except Exception as e:
            return {
                "success": False,
                "topic": topic,
                "data": None,
                "error": f"Consume error: {str(e)}",
                "timeout": False,
            }

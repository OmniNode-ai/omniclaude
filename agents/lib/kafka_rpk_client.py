#!/usr/bin/env python3
"""
Redpanda rpk-based Kafka client (workaround for advertised listener issues).

Uses docker exec with rpk CLI to publish/consume messages.
More reliable than Python Kafka clients when dealing with Docker-mapped ports.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, Optional


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

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """
        Publish message to Kafka topic using rpk.

        Args:
            topic: Kafka topic name
            payload: Message payload (will be JSON-encoded)

        Raises:
            RuntimeError: If publish fails
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
                return  # Success (rpk returned 0)
            else:
                # This shouldn't happen due to check=True, but handle anyway
                output = result.stdout.decode("utf-8") if result.stdout else ""
                error = result.stderr.decode("utf-8") if result.stderr else ""
                raise RuntimeError(
                    f"rpk failed with code {result.returncode}: {output} {error}"
                )

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode("utf-8") if e.stderr else str(e)
            raise RuntimeError(f"rpk publish failed: {error_msg}") from e
        except subprocess.TimeoutExpired:
            raise RuntimeError("rpk publish timed out after 10 seconds")
        except Exception as e:
            raise RuntimeError(f"rpk publish error: {e}") from e

    def consume_one(
        self, topic: str, timeout_sec: float = 10.0
    ) -> Optional[Dict[str, Any]]:
        """
        Consume one message from topic.

        Args:
            topic: Kafka topic name
            timeout_sec: Timeout in seconds

        Returns:
            Parsed JSON message or None if no message available
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
                return json.loads(output)
            else:
                return None

        except subprocess.TimeoutExpired:
            return None  # No message within timeout
        except subprocess.CalledProcessError:
            return None  # Topic doesn't exist or other error
        except json.JSONDecodeError:
            return None  # Invalid JSON
        except Exception:
            return None

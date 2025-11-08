#!/usr/bin/env python3
"""
Request Agent Routing Skill - Kafka Version

Requests agent routing via Kafka event bus with async, non-blocking pattern.
Follows the same event-driven architecture as manifest injection.

Usage:
  python3 execute_kafka.py --user-request "optimize my database queries" --max-recommendations 3

Options:
  --user-request: User's task description (required)
  --context: JSON object with execution context (optional)
  --max-recommendations: Number of recommendations to return (default: 5)
  --timeout-ms: Response timeout in milliseconds (default: 5000)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)

Output: JSON with recommendations or error
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

# Add _shared to path for utilities
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id

# Add lib to path for kafka_config
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
from kafka_config import get_kafka_bootstrap_servers


def load_env_file():
    """Load environment variables from project .env file."""
    # Calculate project root from this file's location (skills/routing/request-agent-routing/)
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env_paths = [
        project_root / ".env",
        Path.home() / "Code" / "omniclaude" / ".env",
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if key not in os.environ:
                            os.environ[key] = value.strip('"').strip("'")
            return


# Load .env on import
load_env_file()


class RoutingEventClient:
    """
    Kafka client for agent routing requests.

    Implements request-response pattern similar to DatabaseEventClient
    and IntelligenceEventClient.
    """

    # Kafka topic names
    TOPIC_REQUEST = "agent.routing.requested.v1"
    TOPIC_COMPLETED = "agent.routing.completed.v1"
    TOPIC_FAILED = "agent.routing.failed.v1"

    def __init__(self, bootstrap_servers=None, request_timeout_ms=5000):
        """
        Initialize routing event client.

        Args:
            bootstrap_servers: Kafka bootstrap servers
            request_timeout_ms: Default timeout for requests in milliseconds
        """
        self.bootstrap_servers = bootstrap_servers or get_kafka_bootstrap_servers()
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers must be provided or set via environment variables.\n"
                "Checked variables (in order):\n"
                "  1. KAFKA_BOOTSTRAP_SERVERS (general config)\n"
                "  2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)\n"
                "  3. KAFKA_BROKERS (legacy compatibility)\n"
                "Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092"
            )
        self.request_timeout_ms = request_timeout_ms
        self.consumer_group_id = f"omniclaude-routing-{uuid4().hex[:8]}"

        self._producer = None
        self._consumer = None
        self._started = False
        self._pending_requests = {}
        self._consumer_ready = asyncio.Event()

    async def start(self):
        """Initialize Kafka producer and consumer."""
        if self._started:
            return

        try:
            # Lazy import aiokafka
            from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

            # Initialize producer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="gzip",
                linger_ms=20,
                acks="all",
                api_version="auto",
                request_timeout_ms=30000,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()

            # Initialize consumer for response topics
            self._consumer = AIOKafkaConsumer(
                self.TOPIC_COMPLETED,
                self.TOPIC_FAILED,
                bootstrap_servers=self.bootstrap_servers,
                group_id=self.consumer_group_id,
                enable_auto_commit=True,
                auto_offset_reset="earliest",
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await self._consumer.start()

            # Wait for consumer partition assignment
            max_wait_seconds = 10
            start_time = asyncio.get_event_loop().time()

            while not self._consumer.assignment():
                await asyncio.sleep(0.1)
                if asyncio.get_event_loop().time() - start_time > max_wait_seconds:
                    raise TimeoutError(
                        f"Consumer failed to get partition assignment after {max_wait_seconds}s"
                    )

            # Start background consumer task
            asyncio.create_task(self._consume_responses())

            # Wait for consumer task to start polling
            await asyncio.wait_for(self._consumer_ready.wait(), timeout=5.0)

            self._started = True

        except Exception:
            await self.stop()
            raise

    async def stop(self):
        """Close Kafka connections gracefully."""
        if not self._started:
            return

        try:
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

            if self._consumer is not None:
                await self._consumer.stop()
                self._consumer = None

            for correlation_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(
                        RuntimeError("Client stopped while request pending")
                    )
            self._pending_requests.clear()
            self._consumer_ready.clear()

            self._started = False

        except Exception as e:
            print(f"Error stopping routing event client: {e}", file=sys.stderr)

    async def request_routing(
        self,
        user_request,
        context=None,
        max_recommendations=5,
        timeout_ms=None,
        correlation_id=None,
    ):
        """
        Request agent routing via events.

        Args:
            user_request: User's input text
            context: Optional execution context
            max_recommendations: Maximum recommendations
            timeout_ms: Response timeout in milliseconds
            correlation_id: Optional correlation ID

        Returns:
            Dictionary with recommendations or error

        Raises:
            TimeoutError: If no response within timeout
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms
        correlation_id = correlation_id or str(uuid4())

        # Build request payload
        request_payload = {
            "event_id": str(uuid4()),
            "event_type": "AGENT_ROUTING_REQUESTED",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "polymorphic-agent",
            "payload": {
                "user_request": user_request,
                "context": context or {},
                "options": {
                    "max_recommendations": max_recommendations,
                    "min_confidence": 0.6,
                    "routing_strategy": "enhanced_fuzzy_matching",
                },
            },
        }

        # Publish and wait for response
        try:
            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            return {
                "success": True,
                "correlation_id": correlation_id,
                "recommendations": result.get("recommendations", []),
                "routing_metadata": result.get("routing_metadata", {}),
            }

        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Routing request timeout after {timeout}ms",
                "correlation_id": correlation_id,
                "fallback_attempted": False,
            }

    async def _publish_and_wait(self, correlation_id, payload, timeout_ms):
        """Publish request and wait for response with timeout."""
        future = asyncio.Future()
        self._pending_requests[correlation_id] = future

        try:
            # Publish request
            if self._producer is None:
                raise RuntimeError("Producer not initialized")
            await self._producer.send_and_wait(self.TOPIC_REQUEST, payload)

            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=timeout_ms / 1000.0)
            return result

        finally:
            self._pending_requests.pop(correlation_id, None)

    async def _consume_responses(self):
        """Background task to consume response events."""
        try:
            if self._consumer is None:
                raise RuntimeError("Consumer not initialized")

            # Signal that consumer is ready
            self._consumer_ready.set()

            async for msg in self._consumer:
                try:
                    response = msg.value
                    correlation_id = response.get("correlation_id")
                    if not correlation_id:
                        continue

                    future = self._pending_requests.get(correlation_id)
                    if future is None:
                        continue

                    event_type = response.get("event_type", "")

                    if (
                        event_type == "AGENT_ROUTING_COMPLETED"
                        or msg.topic == self.TOPIC_COMPLETED
                    ):
                        payload = response.get("payload", {})
                        if not future.done():
                            future.set_result(payload)

                    elif (
                        event_type == "AGENT_ROUTING_FAILED"
                        or msg.topic == self.TOPIC_FAILED
                    ):
                        payload = response.get("payload", {})
                        error_message = payload.get("error", "Routing failed")
                        if not future.done():
                            future.set_exception(Exception(error_message))

                except Exception as e:
                    print(f"Error processing response: {e}", file=sys.stderr)
                    continue

        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Response consumer task failed: {e}", file=sys.stderr)
            raise


async def request_routing_async(
    user_request,
    context=None,
    max_recommendations=5,
    timeout_ms=5000,
    correlation_id=None,
):
    """
    Request routing via Kafka (async wrapper).

    Args:
        user_request: User's task description
        context: Optional execution context dictionary
        max_recommendations: Number of recommendations
        timeout_ms: Response timeout in milliseconds
        correlation_id: Optional correlation ID

    Returns:
        Dictionary with routing result
    """
    client = RoutingEventClient(request_timeout_ms=timeout_ms)

    try:
        await client.start()
        result = await client.request_routing(
            user_request=user_request,
            context=context,
            max_recommendations=max_recommendations,
            timeout_ms=timeout_ms,
            correlation_id=correlation_id,
        )
        return result

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "correlation_id": correlation_id or str(uuid4()),
            "fallback_attempted": False,
        }

    finally:
        await client.stop()


def main():
    """Main entry point for skill."""
    parser = argparse.ArgumentParser(
        description="Request agent routing via Kafka event bus"
    )
    parser.add_argument("--user-request", required=True, help="User's task description")
    parser.add_argument(
        "--context",
        help="Execution context as JSON (optional)",
        default="{}",
    )
    parser.add_argument(
        "--max-recommendations",
        type=int,
        default=5,
        help="Maximum number of recommendations (default: 5)",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="Response timeout in milliseconds (default: 5000)",
    )
    parser.add_argument(
        "--correlation-id",
        help="Correlation ID for tracking (optional, auto-generated)",
    )

    args = parser.parse_args()

    # Parse context JSON
    try:
        context = json.loads(args.context) if args.context else {}
    except json.JSONDecodeError as e:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Invalid context JSON: {e}",
                }
            )
        )
        sys.exit(1)

    # Get or generate correlation ID
    correlation_id = args.correlation_id or get_correlation_id()

    # Request routing via Kafka
    result = asyncio.run(
        request_routing_async(
            user_request=args.user_request,
            context=context,
            max_recommendations=args.max_recommendations,
            timeout_ms=args.timeout_ms,
            correlation_id=correlation_id,
        )
    )

    # Output result as JSON
    print(json.dumps(result, indent=2))

    # Exit with success/failure code
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()

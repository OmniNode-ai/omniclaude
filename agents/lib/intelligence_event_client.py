#!/usr/bin/env python3
"""
Intelligence Event Client - Kafka-based Intelligence Discovery

This module provides a Kafka client for event-based intelligence discovery,
replacing hard-coded omniarchon repository paths with event-driven pattern discovery.

Key Features:
- Request-response pattern with correlation tracking
- Async producer/consumer using aiokafka
- Timeout handling with graceful fallback
- Health check for circuit breaker integration
- Connection pooling and management

Event Flow:
1. Client publishes CODE_ANALYSIS_REQUESTED event
2. omniarchon Intelligence Adapter handler processes request
3. Client waits for CODE_ANALYSIS_COMPLETED or CODE_ANALYSIS_FAILED response
4. On timeout/error: graceful degradation with caller handling fallback

Integration:
- Uses omniarchon event contracts (single source of truth)
- Compatible with omniarchon's confluent-kafka handler (wire protocol)
- Designed for request-response client usage (not 24/7 consumer service)

Performance Targets:
- Response time: <100ms p95
- Timeout: 5000ms default (configurable)
- Memory overhead: <20MB
- Success rate: >95%

Created: 2025-10-23
Reference: EVENT_INTELLIGENCE_INTEGRATION_PLAN.md Section 2.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import os

# Import centralized Kafka configuration
import sys
from datetime import UTC, datetime
from pathlib import Path
from pathlib import Path as PathLib
from typing import Any, Dict, List, Optional
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError

sys.path.insert(0, str(PathLib.home() / ".claude" / "lib"))
from kafka_config import get_kafka_bootstrap_servers

logger = logging.getLogger(__name__)


class IntelligenceEventClient:
    """
    Kafka client for intelligence event publishing and consumption.

    Provides request-response pattern with correlation tracking,
    timeout handling, and graceful fallback for intelligence operations.

    This client uses aiokafka for native async/await integration, perfect
    for request-response patterns. It is wire-compatible with omniarchon's
    confluent-kafka service-side handler.

    Usage:
        client = IntelligenceEventClient(
            bootstrap_servers="localhost:9092",
            enable_intelligence=True,
            request_timeout_ms=5000,
        )

        await client.start()

        try:
            patterns = await client.request_pattern_discovery(
                source_path="node_*_effect.py",
                language="python",
                timeout_ms=5000,
            )
        except TimeoutError:
            # Graceful fallback to built-in patterns
            patterns = fallback_patterns()
        finally:
            await client.stop()
    """

    # Kafka topic names (ONEX event bus architecture)
    TOPIC_REQUEST = "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
    TOPIC_COMPLETED = "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
    TOPIC_FAILED = "dev.archon-intelligence.intelligence.code-analysis-failed.v1"

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_intelligence: bool = True,
        request_timeout_ms: int = 5000,
        consumer_group_id: Optional[str] = None,
    ):
        """
        Initialize intelligence event client.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_intelligence: Enable event-based intelligence (feature flag)
            request_timeout_ms: Default timeout for requests in milliseconds
            consumer_group_id: Optional consumer group ID (default: auto-generated)
        """
        # Bootstrap servers - use centralized configuration if not provided
        self.bootstrap_servers = bootstrap_servers or get_kafka_bootstrap_servers()
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers must be provided or set via environment variables.\n"
                "Checked variables (in order):\n"
                "  1. KAFKA_BOOTSTRAP_SERVERS (general config)\n"
                "  2. KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS (intelligence-specific)\n"
                "  3. KAFKA_BROKERS (legacy compatibility)\n"
                "Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092\n"
                "Current values: KAFKA_BOOTSTRAP_SERVERS={}, KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS={}, KAFKA_BROKERS={}".format(
                    os.getenv("KAFKA_BOOTSTRAP_SERVERS", "not set"),
                    os.getenv("KAFKA_INTELLIGENCE_BOOTSTRAP_SERVERS", "not set"),
                    os.getenv("KAFKA_BROKERS", "not set"),
                )
            )
        self.enable_intelligence = enable_intelligence
        self.request_timeout_ms = request_timeout_ms
        self.consumer_group_id = (
            consumer_group_id or f"omniclaude-intelligence-{uuid4().hex[:8]}"
        )

        self._producer: Optional[AIOKafkaProducer] = None
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._started = False
        self._pending_requests: Dict[str, asyncio.Future] = {}
        self._consumer_ready = asyncio.Event()  # Signal when consumer is polling

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Initialize Kafka producer and consumer.

        Creates producer for publishing requests and consumer for receiving responses.
        Should be called once before making requests.

        Raises:
            KafkaError: If Kafka connection fails
        """
        if self._started:
            self.logger.debug("Intelligence event client already started")
            return

        if not self.enable_intelligence:
            self.logger.info("Intelligence event client disabled via feature flag")
            return

        try:
            self.logger.info(
                f"Starting intelligence event client (broker: {self.bootstrap_servers})"
            )

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
                auto_offset_reset="earliest",  # CRITICAL: Changed from "latest" to fix race condition
                # With random consumer groups per request, we need to see
                # messages published before subscription completes
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await self._consumer.start()

            # CRITICAL: Wait for consumer to have partition assignments
            # This ensures consumer is ready to receive messages BEFORE we return
            # Without this, there's a race condition where requests are published
            # before the consumer finishes subscribing, causing missed responses
            self.logger.info(
                f"Waiting for consumer partition assignment (topics: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED})..."
            )
            max_wait_seconds = 10  # Increased from 5s for slow networks
            start_time = asyncio.get_event_loop().time()
            check_count = 0

            while not self._consumer.assignment():
                check_count += 1
                await asyncio.sleep(0.1)
                elapsed = asyncio.get_event_loop().time() - start_time

                # Log progress every 1 second
                if check_count % 10 == 0:
                    self.logger.debug(
                        f"Still waiting for partition assignment... ({elapsed:.1f}s elapsed)"
                    )

                if elapsed > max_wait_seconds:
                    # Provide detailed error with troubleshooting guidance
                    error_msg = (
                        f"Consumer failed to get partition assignment after {max_wait_seconds}s.\n"
                        f"Troubleshooting:\n"
                        f"  1. Check Kafka broker is accessible: {self.bootstrap_servers}\n"
                        f"  2. Verify topics exist: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}\n"
                        f"  3. Check consumer group permissions: {self.consumer_group_id}\n"
                        f"  4. Review Kafka broker logs for connection issues\n"
                        f"  5. Verify network connectivity to Kafka cluster"
                    )
                    self.logger.error(error_msg)
                    raise TimeoutError(error_msg)

            partition_count = len(self._consumer.assignment())
            self.logger.info(
                f"Consumer ready with {partition_count} partition(s): {self._consumer.assignment()}"
            )

            # Start background consumer task AFTER partition assignment confirmed
            asyncio.create_task(self._consume_responses())

            # CRITICAL FIX: Wait for consumer task to actually start polling
            # This prevents race condition where requests are published before
            # consumer is ready to receive responses
            self.logger.info("Waiting for consumer task to start polling...")
            consumer_ready_timeout = 5.0  # 5 seconds
            try:
                await asyncio.wait_for(
                    self._consumer_ready.wait(), timeout=consumer_ready_timeout
                )
                self.logger.info("Consumer task confirmed polling - ready for requests")
            except asyncio.TimeoutError:
                error_msg = (
                    f"Consumer task failed to start polling within {consumer_ready_timeout}s.\n"
                    f"This indicates the consumer loop did not start properly."
                )
                self.logger.error(error_msg)
                raise TimeoutError(error_msg)

            self._started = True
            self.logger.info("Intelligence event client started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start intelligence event client: {e}")
            await self.stop()
            raise KafkaError(f"Failed to start Kafka client: {e}") from e

    async def stop(self) -> None:
        """
        Close Kafka connections gracefully.

        Stops producer and consumer, cleans up pending requests.
        Should be called when client is no longer needed.
        """
        if not self._started:
            return

        self.logger.info("Stopping intelligence event client")

        try:
            # Stop producer
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

            # Stop consumer
            if self._consumer is not None:
                await self._consumer.stop()
                self._consumer = None

            # Cancel pending requests
            for correlation_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(
                        RuntimeError("Client stopped while request pending")
                    )
            self._pending_requests.clear()

            # Clear consumer ready flag for restart capability
            self._consumer_ready.clear()

            self._started = False
            self.logger.info("Intelligence event client stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping intelligence event client: {e}")

    async def health_check(self) -> bool:
        """
        Check Kafka connection health.

        Returns:
            True if Kafka connection is healthy, False otherwise

        Usage:
            if await client.health_check():
                patterns = await client.request_pattern_discovery(...)
            else:
                patterns = fallback_patterns()
        """
        if not self.enable_intelligence or not self._started:
            return False

        try:
            # Simple health check: verify producer is connected
            if self._producer is None:
                return False

            # Producer API doesn't have direct health check, but we can check metadata
            # If producer is started successfully, it's healthy
            return True

        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            return False

    async def request_pattern_discovery(
        self,
        source_path: str,
        language: str,
        timeout_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Request pattern discovery via events.

        This is the main method for discovering patterns from omniarchon
        codebase using event-based communication.

        Args:
            source_path: Pattern to search for (e.g., "node_*_effect.py") or actual file path
            language: Programming language (e.g., "python")
            timeout_ms: Response timeout in milliseconds (default: request_timeout_ms)

        Returns:
            List of discovered patterns with metadata

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            patterns = await client.request_pattern_discovery(
                source_path="node_*_effect.py",
                language="python",
                timeout_ms=5000,
            )

            for pattern in patterns:
                print(f"Found: {pattern['file_path']} (confidence: {pattern['confidence']})")
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Read file content if source_path is an actual file (not a pattern)
        content = None
        file_path = Path(source_path)
        if file_path.exists() and file_path.is_file():
            try:
                content = file_path.read_text(encoding="utf-8")
                self.logger.debug(
                    f"Read file content from {source_path} ({len(content)} bytes)"
                )
            except Exception as e:
                self.logger.warning(
                    f"Failed to read file {source_path}: {e}. Proceeding with empty content."
                )

        # Use PATTERN_EXTRACTION operation type for pattern discovery
        result = await self.request_code_analysis(
            content=content,
            source_path=source_path,
            language=language,
            options={
                "operation_type": "PATTERN_EXTRACTION",
                "include_patterns": True,
                "include_metrics": False,
            },
            timeout_ms=timeout,
        )

        # Extract patterns list from result dict
        return result.get("patterns", [])

    async def request_code_analysis(
        self,
        content: Optional[str],
        source_path: str,
        language: str,
        options: Optional[Dict[str, Any]] = None,
        timeout_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Request comprehensive code analysis via events.

        More general method that supports all analysis operation types.
        Use request_pattern_discovery() for simpler pattern discovery use case.

        Args:
            content: Code content to analyze (None to read from source_path)
            source_path: File path for context
            language: Programming language
            options: Analysis options dictionary
            timeout_ms: Response timeout in milliseconds

        Returns:
            Analysis results dictionary containing:
                - patterns: List of discovered patterns (if requested)
                - quality_score: Overall quality score
                - onex_compliance: ONEX compliance score
                - issues: List of identified issues
                - recommendations: List of recommendations

        Raises:
            TimeoutError: If response not received within timeout
            KafkaError: If Kafka communication fails
            RuntimeError: If client not started

        Example:
            result = await client.request_code_analysis(
                content="def hello(): pass",
                source_path="test.py",
                language="python",
                options={
                    "operation_type": "QUALITY_ASSESSMENT",
                    "include_metrics": True,
                },
                timeout_ms=10000,
            )
        """
        if not self._started:
            raise RuntimeError("Client not started. Call start() first.")

        timeout = timeout_ms or self.request_timeout_ms

        # Create request payload
        correlation_id = str(uuid4())
        request_payload = self._create_request_payload(
            correlation_id=correlation_id,
            content=content,
            source_path=source_path,
            language=language,
            options=options or {},
        )

        # Publish request and wait for response
        try:
            self.logger.debug(
                f"Publishing code analysis request (correlation_id: {correlation_id}, source_path: {source_path})"
            )

            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            self.logger.debug(
                f"Code analysis completed (correlation_id: {correlation_id})"
            )

            return result

        except asyncio.TimeoutError:
            self.logger.warning(
                f"Code analysis request timeout (correlation_id: {correlation_id}, timeout: {timeout}ms)"
            )
            raise TimeoutError(
                f"Request timeout after {timeout}ms (correlation_id: {correlation_id})"
            )

        except Exception as e:
            self.logger.error(
                f"Code analysis request failed (correlation_id: {correlation_id}): {e}"
            )
            raise

    def _create_request_payload(
        self,
        correlation_id: str,
        content: Optional[str],
        source_path: str,
        language: str,
        options: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build request payload compatible with omniarchon event contracts.

        Creates a payload that matches ModelCodeAnalysisRequestPayload schema
        from omniarchon intelligence adapter events.

        Args:
            correlation_id: Unique request identifier
            content: Optional code content
            source_path: File path or pattern
            language: Programming language
            options: Analysis options

        Returns:
            Request payload dictionary
        """
        # Extract operation type from options (default: PATTERN_EXTRACTION)
        operation_type = options.get("operation_type", "PATTERN_EXTRACTION")

        # Build event payload matching omniarchon ModelCodeAnalysisRequestPayload
        payload = {
            "event_id": str(uuid4()),
            "event_type": "CODE_ANALYSIS_REQUESTED",
            "correlation_id": correlation_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "service": "omniclaude",
            "payload": {
                "source_path": source_path,
                "content": content,  # Keep None as None for pattern discovery
                "language": language,
                "operation_type": operation_type,
                "options": options,
                "project_id": "omniclaude",
                "user_id": "system",
            },
        }

        return payload

    async def _publish_and_wait(
        self,
        correlation_id: str,
        payload: Dict[str, Any],
        timeout_ms: int,
    ) -> Dict[str, Any]:
        """
        Publish request and wait for response with timeout.

        Implements request-response pattern:
        1. Create future for this correlation_id
        2. Publish request event
        3. Wait for response with timeout
        4. Return response or raise timeout

        Args:
            correlation_id: Request correlation ID
            payload: Request payload
            timeout_ms: Response timeout in milliseconds

        Returns:
            Response payload

        Raises:
            asyncio.TimeoutError: If timeout occurs
            KafkaError: If Kafka operation fails
        """
        # Create future for this request
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[correlation_id] = future

        try:
            # Publish request
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")
            await self._producer.send_and_wait(self.TOPIC_REQUEST, payload)

            # Wait for response with timeout
            result = await asyncio.wait_for(
                future, timeout=timeout_ms / 1000.0  # Convert to seconds
            )

            return result

        finally:
            # Clean up pending request
            self._pending_requests.pop(correlation_id, None)

    async def _consume_responses(self) -> None:
        """
        Background task to consume response events.

        Continuously polls for CODE_ANALYSIS_COMPLETED and CODE_ANALYSIS_FAILED
        events, matches them to pending requests by correlation_id, and resolves
        the corresponding futures.

        This task runs in the background for the lifetime of the client.
        """
        self.logger.info("Starting response consumer task")
        self.logger.info(
            f"Consumer subscribed to topics: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}"
        )

        try:
            if self._consumer is None:
                raise RuntimeError("Consumer not initialized. Call start() first.")

            # Signal that consumer is ready to poll (fixes race condition)
            self._consumer_ready.set()
            self.logger.debug("Consumer task entered polling loop - signaling ready")

            async for msg in self._consumer:
                self.logger.debug(
                    f"[CONSUMER] Received message: topic={msg.topic}, partition={msg.partition}, offset={msg.offset}"
                )
                try:
                    # Parse response
                    response = msg.value

                    # Extract correlation_id
                    correlation_id = response.get("correlation_id")
                    if not correlation_id:
                        self.logger.warning(
                            f"Response missing correlation_id, skipping: {response}"
                        )
                        continue

                    # Find pending request
                    future = self._pending_requests.get(correlation_id)
                    if future is None:
                        self.logger.debug(
                            f"No pending request for correlation_id: {correlation_id}"
                        )
                        continue

                    # Determine event type
                    event_type = response.get("event_type", "")

                    if (
                        event_type == "CODE_ANALYSIS_COMPLETED"
                        or msg.topic == self.TOPIC_COMPLETED
                    ):
                        # Success response
                        payload = response.get("payload", {})
                        if not future.done():
                            future.set_result(payload)
                            self.logger.debug(
                                f"Completed request (correlation_id: {correlation_id})"
                            )

                    elif (
                        event_type == "CODE_ANALYSIS_FAILED"
                        or msg.topic == self.TOPIC_FAILED
                    ):
                        # Error response
                        payload = response.get("payload", {})
                        error_code = payload.get("error_code", "UNKNOWN")
                        error_message = payload.get("error_message", "Analysis failed")

                        if not future.done():
                            future.set_exception(
                                KafkaError(f"{error_code}: {error_message}")
                            )
                            self.logger.warning(
                                f"Failed request (correlation_id: {correlation_id}, error: {error_code})"
                            )

                    else:
                        self.logger.warning(
                            f"Unknown event type: {event_type} (correlation_id: {correlation_id})"
                        )

                except Exception as e:
                    self.logger.error(f"Error processing response: {e}", exc_info=True)
                    continue

        except asyncio.CancelledError:
            self.logger.debug("Response consumer task cancelled")
            raise

        except Exception as e:
            self.logger.error(f"Response consumer task failed: {e}", exc_info=True)
            raise

        finally:
            self.logger.debug("Response consumer task stopped")


# Convenience context manager for automatic start/stop
class IntelligenceEventClientContext:
    """
    Context manager for automatic client lifecycle management.

    Usage:
        async with IntelligenceEventClientContext() as client:
            patterns = await client.request_pattern_discovery(...)
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_intelligence: bool = True,
        request_timeout_ms: int = 5000,
    ):
        self.client = IntelligenceEventClient(
            bootstrap_servers=bootstrap_servers,
            enable_intelligence=enable_intelligence,
            request_timeout_ms=request_timeout_ms,
        )

    async def __aenter__(self) -> IntelligenceEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.stop()
        return False


__all__ = [
    "IntelligenceEventClient",
    "IntelligenceEventClientContext",
]

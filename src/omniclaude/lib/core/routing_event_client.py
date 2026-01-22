#!/usr/bin/env python3
"""
Routing Event Client - Kafka-based Agent Routing

This module provides a Kafka client for event-based agent routing requests,
enabling agents to request intelligent routing decisions via Kafka events
instead of direct AgentRouter instantiation.

Key Features:
- Request-response pattern with correlation tracking
- Async producer/consumer using aiokafka
- Timeout handling with graceful fallback to local routing
- Health check for circuit breaker integration
- Connection pooling and management
- Context manager support (async with)

Event Flow:
1. Client publishes AGENT_ROUTING_REQUESTED event
2. agent-router-service processes request
3. Client waits for AGENT_ROUTING_COMPLETED or AGENT_ROUTING_FAILED response
4. On timeout/error: graceful degradation with local routing fallback

Integration:
- Wire-compatible with routing_adapter service
- Designed for request-response client usage (not 24/7 consumer service)
- Supports all routing options (max_recommendations, min_confidence, etc.)

Performance Targets:
- Response time: <100ms p95
- Timeout: 5000ms default (configurable)
- Memory overhead: <20MB
- Success rate: >95%

Created: 2025-10-30
Reference: database_event_client.py (proven pattern)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path as PathLib
from typing import Any, cast
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.errors import KafkaError as AIOKafkaError

# CRITICAL: Add project root FIRST to avoid config module conflicts
# There's a config module in agents/lib/config/ that conflicts with main config/
# Note: 4 parents needed (core/ -> lib/ -> claude/ -> project_root)
_project_root = PathLib(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Add routing adapter schemas to path (AFTER project root)
_routing_adapter_path = str(_project_root / "services" / "routing_adapter")
if _routing_adapter_path not in sys.path:
    sys.path.append(_routing_adapter_path)

# Import routing event schemas
try:
    from schemas.model_routing_event_envelope import ModelRoutingEventEnvelope
    from schemas.model_routing_request import ModelRoutingOptions

    SCHEMAS_AVAILABLE = True
except ImportError as e:
    SCHEMAS_AVAILABLE = False
    logging.error(f"Failed to import routing schemas: {e}")

logger = logging.getLogger(__name__)

# ONEX-compliant error handling from shared module
from omniclaude.lib.errors import EnumCoreErrorCode, OnexError

# Import agent execution logger for observability
try:
    from omniclaude.lib.agent_execution_logger import log_agent_execution

    AGENT_LOGGER_AVAILABLE = True
except ImportError:
    try:
        from agents.lib.agent_execution_logger import log_agent_execution

        AGENT_LOGGER_AVAILABLE = True
    except ImportError:
        AGENT_LOGGER_AVAILABLE = False
        logging.debug("Agent execution logger not available - execution logging disabled")

try:
    from omniclaude.config import settings

    SETTINGS_AVAILABLE = True
except ImportError:
    SETTINGS_AVAILABLE = False
    logging.warning("config.settings not available, falling back to environment variables")

# Import Slack notifier for error notifications
try:
    from omniclaude.lib.slack_notifier import get_slack_notifier

    SLACK_NOTIFIER_AVAILABLE = True
except ImportError:
    try:
        from agents.lib.slack_notifier import get_slack_notifier

        SLACK_NOTIFIER_AVAILABLE = True
    except ImportError:
        SLACK_NOTIFIER_AVAILABLE = False
        logging.warning("SlackNotifier not available - error notifications disabled")


class RoutingEventClient:
    """
    Kafka client for routing event publishing and consumption.

    Provides request-response pattern with correlation tracking,
    timeout handling, and graceful fallback for agent routing requests.

    This client uses aiokafka for native async/await integration, perfect
    for request-response patterns. It is wire-compatible with the
    routing_adapter service.

    Usage:
        client = RoutingEventClient(
            bootstrap_servers="localhost:9092",
            request_timeout_ms=5000,
        )

        await client.start()

        try:
            # Request routing
            recommendations = await client.request_routing(
                user_request="optimize my database queries",
                context={"domain": "database_optimization"},
                max_recommendations=3,
                timeout_ms=5000,
            )

            # Extract best recommendation
            if recommendations:
                best = recommendations[0]
                print(f"Selected agent: {best['agent_name']}")
                print(f"Confidence: {best['confidence']['total']:.2%}")

        finally:
            await client.stop()

    Or use context manager:
        async with RoutingEventClientContext() as client:
            recommendations = await client.request_routing(
                user_request="optimize my database queries"
            )
    """

    # Kafka topic names (following EVENT_BUS_INTEGRATION_GUIDE standard)
    # Format: omninode.{domain}.{entity}.{action}.v{major}
    TOPIC_REQUEST = "omninode.agent.routing.requested.v1"
    TOPIC_COMPLETED = "omninode.agent.routing.completed.v1"
    TOPIC_FAILED = "omninode.agent.routing.failed.v1"

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        request_timeout_ms: int = 5000,
        consumer_group_id: str | None = None,
    ):
        """
        Initialize routing event client.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            request_timeout_ms: Default timeout for requests in milliseconds
            consumer_group_id: Optional consumer group ID (default: auto-generated)
        """
        if not SCHEMAS_AVAILABLE:
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message="Routing schemas not available. Cannot initialize RoutingEventClient.",
                details={
                    "component": "RoutingEventClient",
                    "required_path": "services/routing_adapter/schemas/",
                    "suggestion": "Ensure services/routing_adapter/schemas/ exists",
                },
            )

        # Bootstrap servers - use type-safe configuration if not provided
        if bootstrap_servers:
            self.bootstrap_servers = bootstrap_servers
        elif SETTINGS_AVAILABLE:
            self.bootstrap_servers = settings.get_effective_kafka_bootstrap_servers()
        else:
            # This should not happen - settings should always be available
            raise OnexError(
                code=EnumCoreErrorCode.CONFIGURATION_ERROR,
                message="config.settings not available. Cannot initialize RoutingEventClient.",
                details={
                    "component": "RoutingEventClient",
                    "required_module": "config/settings.py",
                    "required_env_var": "KAFKA_BOOTSTRAP_SERVERS",
                    "suggestion": "Ensure config/settings.py is accessible and KAFKA_BOOTSTRAP_SERVERS is set in .env",
                },
            )

        if not self.bootstrap_servers:
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="bootstrap_servers must be provided or set via KAFKA_BOOTSTRAP_SERVERS in .env file",
                details={
                    "component": "RoutingEventClient",
                    "operation": "initialization",
                    "current_value": self.bootstrap_servers,
                    "suggestion": "Set KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092 in .env file",
                },
            )
        self.request_timeout_ms = request_timeout_ms
        self.consumer_group_id = consumer_group_id or f"omniclaude-routing-{uuid4().hex[:8]}"

        self._producer: AIOKafkaProducer | None = None
        self._consumer: AIOKafkaConsumer | None = None
        self._started = False
        self._pending_requests: dict[str, asyncio.Future] = {}
        self._consumer_ready = asyncio.Event()  # Signal when consumer is polling
        self._consumer_task: asyncio.Task | None = None  # Store task to prevent GC

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Initialize Kafka producer and consumer.

        Creates producer for publishing requests and consumer for receiving responses.
        Should be called once before making requests.

        Raises:
            OnexError: With OPERATION_FAILED if Kafka connection fails or
                       partition assignment times out
        """
        if self._started:
            self.logger.debug("Routing event client already started")
            return

        # Validate required services before attempting connection
        # This follows coding guidelines for service validation at startup
        if SETTINGS_AVAILABLE:
            validation_errors = settings.validate_required_services()
            # Filter to only Kafka-related errors for this client
            kafka_errors = [e for e in validation_errors if "kafka" in e.lower()]
            if kafka_errors:
                self.logger.warning(f"Service validation warnings: {kafka_errors}")
                # Log but don't fail - allow connection attempt to provide
                # more specific error messages

        # Validate bootstrap servers format
        if not self.bootstrap_servers or not isinstance(self.bootstrap_servers, str):
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Invalid Kafka bootstrap servers configuration",
                details={
                    "component": "RoutingEventClient",
                    "operation": "service_validation",
                    "bootstrap_servers": self.bootstrap_servers,
                    "suggestion": "Set valid KAFKA_BOOTSTRAP_SERVERS in .env (e.g., 192.168.86.200:9092)",
                },
            )

        try:
            self.logger.info(f"Starting routing event client (broker: {self.bootstrap_servers})")

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
                auto_offset_reset="earliest",  # CRITICAL: Prevent race condition
                value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            )
            await self._consumer.start()

            # CRITICAL: Wait for consumer to have partition assignments
            self.logger.info(
                f"Waiting for consumer partition assignment (topics: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED})..."
            )
            max_wait_seconds = 10
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
                    error_msg = (
                        f"Consumer failed to get partition assignment after {max_wait_seconds}s"
                    )
                    self.logger.error(error_msg)
                    raise OnexError(
                        code=EnumCoreErrorCode.OPERATION_FAILED,
                        message=error_msg,
                        details={
                            "error_type": "TIMEOUT",
                            "component": "RoutingEventClient",
                            "operation": "partition_assignment",
                            "timeout_seconds": max_wait_seconds,
                            "bootstrap_servers": self.bootstrap_servers,
                            "topics": [self.TOPIC_COMPLETED, self.TOPIC_FAILED],
                            "consumer_group": self.consumer_group_id,
                            "troubleshooting": [
                                f"Check Kafka broker is accessible: {self.bootstrap_servers}",
                                f"Verify topics exist: {self.TOPIC_COMPLETED}, {self.TOPIC_FAILED}",
                                f"Check consumer group permissions: {self.consumer_group_id}",
                                "Review Kafka broker logs for connection issues",
                                "Verify network connectivity to Kafka cluster",
                            ],
                        },
                    )

            partition_count = len(self._consumer.assignment())
            self.logger.info(
                f"Consumer ready with {partition_count} partition(s): {self._consumer.assignment()}"
            )

            # Start background consumer task AFTER partition assignment confirmed
            # Store task reference to prevent garbage collection
            self._consumer_task = asyncio.create_task(self._consume_responses())

            # CRITICAL: Wait for consumer task to actually start polling
            self.logger.info("Waiting for consumer task to start polling...")
            consumer_ready_timeout = 5.0
            try:
                await asyncio.wait_for(self._consumer_ready.wait(), timeout=consumer_ready_timeout)
                self.logger.info("Consumer task confirmed polling - ready for requests")
            except TimeoutError:
                error_msg = (
                    f"Consumer task failed to start polling within {consumer_ready_timeout}s"
                )
                self.logger.error(error_msg)
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message=error_msg,
                    details={
                        "error_type": "TIMEOUT",
                        "component": "RoutingEventClient",
                        "operation": "consumer_polling_start",
                        "timeout_seconds": consumer_ready_timeout,
                        "suggestion": "The consumer loop did not start properly",
                    },
                )

            self._started = True
            self.logger.info("Routing event client started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start routing event client: {e}")

            # Send Slack notification for Kafka connection failure
            if SLACK_NOTIFIER_AVAILABLE:
                try:
                    notifier = get_slack_notifier()
                    await notifier.send_error_notification(
                        error=e,
                        context={
                            "service": "routing_event_client",
                            "operation": "kafka_connection",
                            "kafka_servers": self.bootstrap_servers,
                            "consumer_group": self.consumer_group_id,
                        },
                    )
                except Exception as notify_error:
                    self.logger.debug(f"Failed to send Slack notification: {notify_error}")

            await self.stop()
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to start Kafka client: {e}",
                details={
                    "component": "RoutingEventClient",
                    "operation": "kafka_client_start",
                    "bootstrap_servers": self.bootstrap_servers,
                    "consumer_group": self.consumer_group_id,
                    "original_error": str(e),
                },
            ) from e

    async def stop(self) -> None:
        """
        Close Kafka connections gracefully.

        Stops producer and consumer, cleans up pending requests.
        Should be called when client is no longer needed.

        Always attempts cleanup of all resources independently, even if
        start() failed mid-execution or if cleanup of one resource fails.
        """
        # Always run cleanup, even after partial startup failures
        if not self._started:
            self.logger.info("Stopping routing event client after partial startup failure")
        else:
            self.logger.info("Stopping routing event client")

        # Track cleanup errors to report at the end
        cleanup_errors = []

        # Cancel consumer task first (independent error handling)
        if self._consumer_task is not None:
            try:
                if not self._consumer_task.done():
                    self._consumer_task.cancel()
                    try:
                        await self._consumer_task
                    except asyncio.CancelledError:
                        pass  # Expected when cancelling
                self.logger.debug("Consumer task cancelled successfully")
            except Exception as e:
                self.logger.error(f"Error cancelling consumer task: {e}")
                cleanup_errors.append(f"consumer_task: {e}")
            finally:
                self._consumer_task = None

        # Stop producer (independent error handling)
        if self._producer is not None:
            try:
                await self._producer.stop()
                self.logger.debug("Producer stopped successfully")
            except Exception as e:
                self.logger.error(f"Error stopping producer: {e}")
                cleanup_errors.append(f"producer: {e}")
            finally:
                self._producer = None

        # Stop consumer (independent error handling)
        if self._consumer is not None:
            try:
                await self._consumer.stop()
                self.logger.debug("Consumer stopped successfully")
            except Exception as e:
                self.logger.error(f"Error stopping consumer: {e}")
                cleanup_errors.append(f"consumer: {e}")
            finally:
                self._consumer = None

        # Cancel pending requests (independent error handling)
        try:
            for correlation_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(
                        OnexError(
                            code=EnumCoreErrorCode.OPERATION_FAILED,
                            message="Client stopped while request pending",
                            details={
                                "component": "RoutingEventClient",
                                "operation": "request_cancellation",
                                "correlation_id": correlation_id,
                            },
                        )
                    )
            self._pending_requests.clear()
            self.logger.debug("Pending requests cancelled")
        except Exception as e:
            self.logger.error(f"Error cancelling pending requests: {e}")
            cleanup_errors.append(f"pending_requests: {e}")

        # Clear consumer ready flag for restart capability
        self._consumer_ready.clear()

        # Reset state
        self._started = False

        # Report final status
        if cleanup_errors:
            self.logger.warning(
                f"Routing event client stopped with {len(cleanup_errors)} error(s): {', '.join(cleanup_errors)}"
            )
        else:
            self.logger.info("Routing event client stopped successfully")

    async def health_check(self) -> bool:
        """
        Check Kafka connection health.

        Returns:
            True if Kafka connection is healthy, False otherwise

        Usage:
            if await client.health_check():
                recommendations = await client.request_routing(...)
            else:
                # Use fallback local routing
                pass
        """
        if not self._started:
            return False

        try:
            # Verify producer is connected
            return self._producer is not None

        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            return False

    async def request_routing(
        self,
        user_request: str,
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
        min_confidence: float = 0.6,
        routing_strategy: str = "enhanced_fuzzy_matching",
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Request agent routing via events.

        Args:
            user_request: User's input text requiring agent routing
            context: Optional execution context (domain, previous_agent, current_file)
            max_recommendations: Maximum number of agent recommendations (default: 5)
            min_confidence: Minimum confidence threshold 0.0-1.0 (default: 0.6)
            routing_strategy: Routing strategy name (default: "enhanced_fuzzy_matching")
            timeout_ms: Response timeout in milliseconds (default: request_timeout_ms)

        Returns:
            List of agent recommendations, each containing:
            - agent_name: Agent identifier
            - agent_title: Human-readable agent title
            - confidence: Confidence score breakdown (total, trigger, context, capability, historical)
            - reason: Human-readable reason for recommendation
            - definition_path: Absolute path to agent YAML definition
            - alternatives: Optional list of alternative agents

        Raises:
            OnexError: With OPERATION_FAILED code if:
                - Response not received within timeout (details["error_type"] == "TIMEOUT")
                - Kafka communication fails
                - Client not started (call start() first)

        Example:
            recommendations = await client.request_routing(
                user_request="optimize my database queries",
                context={
                    "domain": "database_optimization",
                    "previous_agent": "agent-api-architect"
                },
                max_recommendations=3,
            )

            if recommendations:
                best = recommendations[0]
                print(f"Agent: {best['agent_name']}")
                print(f"Confidence: {best['confidence']['total']:.2%}")
                print(f"Reason: {best['reason']}")
        """
        if not self._started:
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message="Client not started. Call start() first.",
                details={
                    "component": "RoutingEventClient",
                    "operation": "request_routing",
                    "suggestion": "Call await client.start() before making requests",
                },
            )

        timeout = timeout_ms or self.request_timeout_ms

        # Create request envelope using factory
        correlation_id = str(uuid4())

        # Structured logging context for correlation ID tracking
        log_extra = {
            "correlation_id": correlation_id,
            "component": "RoutingEventClient",
            "operation": "request_routing",
        }

        try:
            # Log routing request start with correlation ID
            self.logger.info(
                "Routing request started",
                extra={
                    **log_extra,
                    "user_request_preview": (user_request[:100] if user_request else None),
                    "max_recommendations": max_recommendations,
                    "min_confidence": min_confidence,
                    "routing_strategy": routing_strategy,
                    "timeout_ms": timeout,
                },
            )

            envelope = ModelRoutingEventEnvelope.create_request(
                user_request=user_request,
                correlation_id=correlation_id,
                service="omniclaude-routing-client",
                context=context,
                options=ModelRoutingOptions(
                    max_recommendations=max_recommendations,
                    min_confidence=min_confidence,
                    routing_strategy=routing_strategy,
                ),
                timeout_ms=timeout,  # Single source of truth for timeout
            )

            # Convert to dict for Kafka
            request_payload = envelope.model_dump()

            # Publish request and wait for response
            self.logger.debug(
                "Publishing routing request to Kafka",
                extra={
                    **log_extra,
                    "topic": self.TOPIC_REQUEST,
                },
            )

            result = await self._publish_and_wait(
                correlation_id=correlation_id,
                payload=request_payload,
                timeout_ms=timeout,
            )

            recommendation_count = len(result.get("recommendations", []))
            recommendations = result.get("recommendations", [])

            # Log successful completion with correlation ID
            self.logger.info(
                "Routing request completed successfully",
                extra={
                    **log_extra,
                    "recommendation_count": recommendation_count,
                    "status": "success",
                },
            )

            # Optionally log to agent execution logger for full observability
            # This provides database persistence of routing decisions
            if AGENT_LOGGER_AVAILABLE and recommendations:
                try:
                    top_agent = recommendations[0].get("agent_name", "unknown")
                    top_confidence = recommendations[0].get("confidence", {}).get("total", 0.0)
                    execution_logger = await log_agent_execution(
                        agent_name=f"routing-decision:{top_agent}",
                        user_prompt=user_request[:500] if user_request else None,
                        correlation_id=correlation_id,
                    )
                    await execution_logger.complete(
                        status="completed",
                        quality_score=top_confidence,
                        metadata={
                            "routing_method": "event_driven",
                            "recommendation_count": recommendation_count,
                            "top_agent": top_agent,
                            "top_confidence": top_confidence,
                            "all_recommendations": [
                                {
                                    "agent": r.get("agent_name"),
                                    "confidence": r.get("confidence", {}).get("total", 0.0),
                                }
                                for r in recommendations[:5]
                            ],
                        },
                    )
                except Exception as log_error:
                    # Non-blocking - don't fail routing if logging fails
                    self.logger.debug(
                        f"Agent execution logging failed (non-critical): {log_error}",
                        extra=log_extra,
                    )

            return cast(list[dict[str, Any]], recommendations)

        except TimeoutError:
            # Log timeout with structured correlation ID tracking
            self.logger.warning(
                "Routing request timeout",
                extra={
                    **log_extra,
                    "timeout_ms": timeout,
                    "status": "timeout",
                    "error_type": "TIMEOUT",
                },
            )

            # Send Slack notification for timeout (indicates potential Kafka/router service issues)
            if SLACK_NOTIFIER_AVAILABLE:
                try:
                    notifier = get_slack_notifier()
                    await notifier.send_error_notification(
                        error=TimeoutError(f"Routing request timeout after {timeout}ms"),
                        context={
                            "service": "routing_event_client",
                            "operation": "routing_request",
                            "correlation_id": correlation_id,
                            "timeout_ms": timeout,
                            "user_request": user_request[:200],
                        },
                    )
                except Exception as notify_error:
                    self.logger.debug(f"Failed to send Slack notification: {notify_error}")

            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Routing request timeout after {timeout}ms",
                details={
                    "error_type": "TIMEOUT",
                    "component": "RoutingEventClient",
                    "operation": "routing_request",
                    "correlation_id": correlation_id,
                    "timeout_ms": timeout,
                    "user_request_preview": (user_request[:100] if user_request else None),
                },
            )

        except Exception as e:
            # Log error with structured correlation ID tracking
            self.logger.error(
                "Routing request failed",
                extra={
                    **log_extra,
                    "status": "error",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

            # Send Slack notification for routing failure
            if SLACK_NOTIFIER_AVAILABLE:
                try:
                    notifier = get_slack_notifier()
                    await notifier.send_error_notification(
                        error=e,
                        context={
                            "service": "routing_event_client",
                            "operation": "routing_request",
                            "correlation_id": correlation_id,
                            "user_request": user_request[:200],
                        },
                    )
                except Exception as notify_error:
                    self.logger.debug(f"Failed to send Slack notification: {notify_error}")

            # Wrap non-OnexError exceptions for ONEX compliance
            if isinstance(e, OnexError):
                raise
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Routing request failed: {e}",
                details={
                    "component": "RoutingEventClient",
                    "operation": "request_routing",
                    "correlation_id": correlation_id,
                    "user_request_preview": (user_request[:100] if user_request else None),
                    "original_error_type": type(e).__name__,
                    "original_error": str(e),
                },
            ) from e

    async def _publish_and_wait(
        self,
        correlation_id: str,
        payload: dict[str, Any],
        timeout_ms: int,
    ) -> dict[str, Any]:
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
            asyncio.TimeoutError: If timeout occurs (caught by caller)
            OnexError: With OPERATION_FAILED if producer not initialized
        """
        # Create future for this request
        future: asyncio.Future = asyncio.Future()
        self._pending_requests[correlation_id] = future

        try:
            # Publish request
            if self._producer is None:
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message="Producer not initialized. Call start() first.",
                    details={
                        "component": "RoutingEventClient",
                        "operation": "publish_request",
                        "correlation_id": correlation_id,
                        "suggestion": "Call await client.start() before making requests",
                    },
                )
            await self._producer.send_and_wait(self.TOPIC_REQUEST, payload)

            # Wait for response with timeout
            result = await asyncio.wait_for(
                future,
                timeout=timeout_ms / 1000.0,  # Convert to seconds
            )

            return cast(dict[str, Any], result)

        finally:
            # Clean up pending request
            self._pending_requests.pop(correlation_id, None)

    async def _consume_responses(self) -> None:
        """
        Background task to consume response events.

        Continuously polls for AGENT_ROUTING_COMPLETED and AGENT_ROUTING_FAILED
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
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message="Consumer not initialized. Call start() first.",
                    details={
                        "component": "RoutingEventClient",
                        "operation": "consume_responses",
                        "suggestion": "Call await client.start() before consuming",
                    },
                )

            # Signal that consumer is ready to poll (fixes race condition)
            self._consumer_ready.set()
            self.logger.debug("Consumer task entered polling loop - signaling ready")

            async for msg in self._consumer:
                self.logger.debug(
                    f"[CONSUMER] Received message: topic={msg.topic}, partition={msg.partition}, offset={msg.offset}"
                )
                try:
                    # Parse response envelope
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

                    # Determine event type (lowercase dot notation per EVENT_BUS_INTEGRATION_GUIDE)
                    event_type = response.get("event_type", "")

                    if (
                        event_type == "omninode.agent.routing.completed.v1"
                        or msg.topic == self.TOPIC_COMPLETED
                    ):
                        # Success response
                        payload = response.get("payload", {})
                        if not future.done():
                            # Extract recommendations from payload
                            recommendations = payload.get("recommendations", [])

                            # Convert ModelAgentRecommendation to dicts
                            formatted_recommendations = []
                            for rec in recommendations:
                                if isinstance(rec, dict):
                                    # Already a dict
                                    formatted_recommendations.append(rec)
                                else:
                                    # Convert Pydantic model to dict
                                    formatted_recommendations.append(
                                        rec.model_dump() if hasattr(rec, "model_dump") else rec
                                    )

                            result = {
                                "recommendations": formatted_recommendations,
                                "routing_metadata": payload.get("routing_metadata", {}),
                            }

                            future.set_result(result)
                            self.logger.debug(
                                f"Completed request (correlation_id: {correlation_id})"
                            )

                    elif (
                        event_type == "omninode.agent.routing.failed.v1"
                        or msg.topic == self.TOPIC_FAILED
                    ):
                        # Error response
                        payload = response.get("payload", {})
                        error_code = payload.get("error_code", "UNKNOWN")
                        error_message = payload.get("error_message", "Routing failed")

                        if not future.done():
                            future.set_exception(
                                OnexError(
                                    code=EnumCoreErrorCode.OPERATION_FAILED,
                                    message=f"{error_code}: {error_message}",
                                    details={
                                        "component": "RoutingEventClient",
                                        "operation": "routing_response",
                                        "correlation_id": correlation_id,
                                        "error_code": error_code,
                                        "error_message": error_message,
                                    },
                                )
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
class RoutingEventClientContext:
    """
    Context manager for automatic client lifecycle management.

    Usage:
        async with RoutingEventClientContext() as client:
            recommendations = await client.request_routing(
                user_request="optimize my database queries"
            )
    """

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        request_timeout_ms: int = 5000,
    ):
        self.client = RoutingEventClient(
            bootstrap_servers=bootstrap_servers,
            request_timeout_ms=request_timeout_ms,
        )

    async def __aenter__(self) -> RoutingEventClient:
        await self.client.start()
        return self.client

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.stop()
        return False


def _format_recommendations(recommendations: list) -> list[dict[str, Any]]:
    """
    Convert AgentRecommendation objects to dict format.

    This helper function extracts recommendation data into a consistent
    dictionary format, avoiding code duplication.

    Args:
        recommendations: List of AgentRecommendation objects from router.route()

    Returns:
        List of recommendation dictionaries with agent details and confidence scores
    """
    return [
        {
            "agent_name": rec.agent_name,
            "agent_title": rec.agent_title,
            "confidence": {
                "total": rec.confidence.total,
                "trigger_score": rec.confidence.trigger_score,
                "context_score": rec.confidence.context_score,
                "capability_score": rec.confidence.capability_score,
                "historical_score": rec.confidence.historical_score,
                "explanation": rec.confidence.explanation,
            },
            "reason": rec.reason,
            "definition_path": rec.definition_path,
        }
        for rec in recommendations
    ]


# Backward compatibility wrapper for existing code
async def route_via_events(
    user_request: str,
    context: dict[str, Any] | None = None,
    max_recommendations: int = 5,
    min_confidence: float = 0.6,
    timeout_ms: int = 5000,
    fallback_to_local: bool = True,
) -> list[dict[str, Any]]:
    """
    Convenience function for one-off routing requests via events.

    Automatically manages client lifecycle (start/stop).
    Falls back to local AgentRouter on timeout/error if fallback_to_local=True.

    Args:
        user_request: User's input text requiring agent routing
        context: Optional execution context
        max_recommendations: Maximum number of agent recommendations
        min_confidence: Minimum confidence threshold
        timeout_ms: Response timeout in milliseconds
        fallback_to_local: If True, use local AgentRouter on failure (default: True)

    Returns:
        List of agent recommendations

    Raises:
        OnexError: If both event-based routing and local fallback fail,
            or if fallback_to_local is False and event routing fails.
            Error details include correlation_id for tracing.

    Example:
        recommendations = await route_via_events(
            user_request="optimize my database queries",
            context={"domain": "database_optimization"},
            max_recommendations=3,
        )
    """
    # Feature flag: USE_EVENT_ROUTING (default: True)
    if SETTINGS_AVAILABLE:
        use_events = settings.use_event_routing
    else:
        # Fallback for when settings not available
        use_events = os.getenv("USE_EVENT_ROUTING", "true").lower() in (
            "true",
            "1",
            "yes",
        )

    if not use_events and fallback_to_local:
        # Skip events, go straight to local routing
        logger.info("USE_EVENT_ROUTING=false, using local AgentRouter")
        from .agent_router import AgentRouter

        router = AgentRouter()
        recommendations = router.route(
            user_request=user_request,
            context=context or {},
            max_recommendations=max_recommendations,
        )
        return _format_recommendations(recommendations)

    # Try event-based routing first
    try:
        async with RoutingEventClientContext(request_timeout_ms=timeout_ms) as client:
            return await client.request_routing(
                user_request=user_request,
                context=context,
                max_recommendations=max_recommendations,
                min_confidence=min_confidence,
                timeout_ms=timeout_ms,
            )

    except (OnexError, AIOKafkaError) as e:
        logger.warning(f"Event-based routing failed: {e}")

        if fallback_to_local:
            # Fallback to local AgentRouter
            logger.info("Falling back to local AgentRouter")
            try:
                from .agent_router import AgentRouter

                router = AgentRouter()
                recommendations = router.route(
                    user_request=user_request,
                    context=context or {},
                    max_recommendations=max_recommendations,
                )
                return _format_recommendations(recommendations)
            except Exception as fallback_error:
                logger.error(f"Local routing fallback also failed: {fallback_error}")
                raise OnexError(
                    code=EnumCoreErrorCode.OPERATION_FAILED,
                    message="Both event-based and local routing failed",
                    details={
                        "component": "route_via_events",
                        "event_routing_error": str(e),
                        "local_routing_error": str(fallback_error),
                        "user_request_preview": (user_request[:100] if user_request else None),
                    },
                ) from e
        else:
            # No fallback, re-raise original error
            raise


__all__ = [
    "RoutingEventClient",
    "RoutingEventClientContext",
    "route_via_events",
]

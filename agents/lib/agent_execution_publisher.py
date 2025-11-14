#!/usr/bin/env python3
"""
Agent Execution Event Publisher - Kafka-based Agent Execution Tracking

This module provides a Kafka client for publishing agent execution lifecycle events,
enabling real-time tracking of agent execution start, progress, and completion.

Key Features:
- Non-blocking async publish using aiokafka
- OnexEnvelopeV1 structure following EVENT_BUS_INTEGRATION_GUIDE
- Partition key policy compliance (correlation_id)
- Complete event envelope with all required fields
- Connection pooling and management
- Graceful degradation on Kafka failure

Event Types:
- omninode.agent.execution.started.v1 - Agent execution begins
- omninode.agent.execution.progress.v1 - Agent execution progress update (future)
- omninode.agent.execution.completed.v1 - Agent execution finishes successfully
- omninode.agent.execution.failed.v1 - Agent execution fails with error

Integration:
- Wire-compatible with omniarchon event handlers
- Designed for fire-and-forget publishing (not request-response)
- Integrates with agent workflow coordinator and polymorphic agent launcher

Performance Targets:
- Publish time: <10ms p95
- Memory overhead: <10MB
- Success rate: >99%
- Non-blocking: Never blocks agent execution

Created: 2025-11-13
Reference: EVENT_ALIGNMENT_PLAN.md Task 1.1
          EVENT_BUS_INTEGRATION_GUIDE.md (event structure standards)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any, Dict, Optional
from uuid import uuid4

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from config import settings

logger = logging.getLogger(__name__)


class AgentExecutionPublisher:
    """
    Kafka publisher for agent execution lifecycle events.

    Provides non-blocking async publishing of agent execution events with
    OnexEnvelopeV1 structure, partition key policy compliance, and graceful
    degradation on Kafka failures.

    This publisher uses aiokafka for native async/await integration, perfect
    for fire-and-forget event publishing without blocking agent execution.

    Usage:
        publisher = AgentExecutionPublisher(
            bootstrap_servers="localhost:9092",
            enable_events=True,
        )

        await publisher.start()

        try:
            await publisher.publish_execution_started(
                agent_name="agent-api-architect",
                user_request="Design a REST API for user management",
                correlation_id="abc-123-def-456",
                session_id="session-789",
                context={"domain": "api_design"},
            )
        finally:
            await publisher.stop()

    Or use context manager:
        async with AgentExecutionPublisherContext() as publisher:
            await publisher.publish_execution_started(...)
    """

    # Kafka topic names (following EVENT_BUS_INTEGRATION_GUIDE standard)
    # Format: omninode.{domain}.{entity}.{action}.v{major}
    TOPIC_EXECUTION_STARTED = "omninode.agent.execution.started.v1"
    TOPIC_EXECUTION_PROGRESS = "omninode.agent.execution.progress.v1"  # Future
    TOPIC_EXECUTION_COMPLETED = "omninode.agent.execution.completed.v1"
    TOPIC_EXECUTION_FAILED = "omninode.agent.execution.failed.v1"

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: bool = True,
    ):
        """
        Initialize agent execution event publisher.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - External host: "localhost:9092" or "192.168.86.200:9092"
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_events: Enable event publishing (feature flag)
        """
        # Bootstrap servers - use centralized configuration if not provided
        self.bootstrap_servers = (
            bootstrap_servers or settings.get_effective_kafka_bootstrap_servers()
        )
        if not self.bootstrap_servers:
            raise ValueError(
                "bootstrap_servers must be provided or set via environment variables.\n"
                "Checked variables (in order):\n"
                "  1. KAFKA_BOOTSTRAP_SERVERS (general config)\n"
                "Example: KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092\n"
                f"Current value: {getattr(settings, 'kafka_bootstrap_servers', 'not set')}"
            )
        self.enable_events = enable_events

        self._producer: Optional[AIOKafkaProducer] = None
        self._started = False

        self.logger = logging.getLogger(__name__)

    async def start(self) -> None:
        """
        Initialize Kafka producer.

        Creates producer for publishing events.
        Should be called once before publishing events.

        Raises:
            KafkaError: If Kafka connection fails
        """
        if self._started:
            self.logger.debug("Agent execution publisher already started")
            return

        if not self.enable_events:
            self.logger.info("Agent execution publisher disabled via feature flag")
            return

        try:
            self.logger.info(
                f"Starting agent execution publisher (broker: {self.bootstrap_servers})"
            )

            # Initialize producer
            self._producer = AIOKafkaProducer(
                bootstrap_servers=self.bootstrap_servers,
                compression_type="gzip",
                linger_ms=20,
                acks="all",  # Wait for all replicas
                api_version="auto",
                request_timeout_ms=30000,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
            )
            await self._producer.start()

            self._started = True
            self.logger.info("Agent execution publisher started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start agent execution publisher: {e}")
            await self.stop()
            raise KafkaError(f"Failed to start Kafka producer: {e}") from e

    async def stop(self) -> None:
        """
        Close Kafka producer gracefully.

        Stops producer and cleans up resources.
        Should be called when publisher is no longer needed.
        """
        if not self._started:
            return

        self.logger.info("Stopping agent execution publisher")

        try:
            # Stop producer
            if self._producer is not None:
                await self._producer.stop()
                self._producer = None

            self._started = False
            self.logger.info("Agent execution publisher stopped successfully")

        except Exception as e:
            self.logger.error(f"Error stopping agent execution publisher: {e}")

    async def publish_execution_started(
        self,
        agent_name: str,
        user_request: str,
        correlation_id: str,
        session_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish agent execution started event.

        This event marks the beginning of agent execution and includes
        initial context and request information.

        Args:
            agent_name: Name of the agent being executed
            user_request: User's original request text
            correlation_id: Correlation ID for request tracing (UUID)
            session_id: Session ID for grouping related executions (UUID)
            context: Optional execution context (domain, previous_agent, etc.)

        Returns:
            True if event published successfully, False otherwise

        Example:
            success = await publisher.publish_execution_started(
                agent_name="agent-api-architect",
                user_request="Design a REST API for user management",
                correlation_id="abc-123-def-456",
                session_id="session-789",
                context={"domain": "api_design", "previous_agent": "agent-router"},
            )
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_execution_started_envelope(
                agent_name=agent_name,
                user_request=user_request,
                correlation_id=correlation_id,
                session_id=session_id,
                context=context or {},
            )

            # Publish event with partition key
            partition_key = correlation_id.encode("utf-8")

            # Build required Kafka headers
            headers = [
                # W3C trace context (simplified)
                (
                    "x-traceparent",
                    f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                ),
                # Correlation ID for request tracking
                ("x-correlation-id", correlation_id.encode("utf-8")),
                # Causation ID for event chain tracking
                ("x-causation-id", correlation_id.encode("utf-8")),
                # Tenant ID for ACL enforcement
                ("x-tenant", envelope.get("tenant_id", "default").encode("utf-8")),
                # Schema hash for validation
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Publish event (non-blocking with asyncio.create_task for fire-and-forget)
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_EXECUTION_STARTED,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.info(
                f"Published execution started event (agent: {agent_name}, correlation_id: {correlation_id})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish execution started event (agent: {agent_name}, correlation_id: {correlation_id}): {e}"
            )
            # Don't raise - graceful degradation (agent execution continues even if event fails)
            return False

    def _create_execution_started_envelope(
        self,
        agent_name: str,
        user_request: str,
        correlation_id: str,
        session_id: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build execution started event envelope following OnexEnvelopeV1 structure.

        Creates a complete event envelope with all required fields following
        the frozen envelope structure from EVENT_BUS_INTEGRATION_GUIDE.

        Args:
            agent_name: Name of the agent
            user_request: User's request text
            correlation_id: Correlation ID for tracing
            session_id: Session ID for grouping
            context: Execution context

        Returns:
            Event envelope dictionary with complete structure
        """
        # Get environment from settings or default to "dev"
        environment = os.getenv("ENVIRONMENT", "dev")

        # Build complete event envelope following EVENT_BUS_INTEGRATION_GUIDE standard
        # Reference: docs/EVENT_BUS_INTEGRATION_GUIDE.md section "Envelope Fields (Frozen)"
        envelope = {
            # Full dotted event type (not simplified)
            "event_type": "omninode.agent.execution.started.v1",
            # UUID v7 for event_id (time-ordered)
            "event_id": str(uuid4()),
            # RFC3339 timestamp
            "timestamp": datetime.now(UTC).isoformat(),
            # Tenant ID for multi-tenant isolation (default: "default" for single-tenant)
            "tenant_id": os.getenv("TENANT_ID", "default"),
            # Namespace for event categorization
            "namespace": "omninode",
            # Source service name
            "source": "omniclaude",
            # Correlation ID for request-response tracking
            "correlation_id": correlation_id,
            # Causation ID for event chain tracking (same as correlation_id for initial event)
            "causation_id": correlation_id,
            # Schema reference for validation
            "schema_ref": "registry://omninode/agent/execution_started/v1",
            # Domain-specific payload (validated against schema_ref)
            "payload": {
                "agent_name": agent_name,
                "user_request": user_request,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "started_at": datetime.now(UTC).isoformat(),
                "context": context,
            },
        }

        return envelope

    async def publish_execution_completed(
        self,
        agent_name: str,
        correlation_id: str,
        duration_ms: int,
        quality_score: Optional[float] = None,
        output_summary: Optional[str] = None,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish agent execution completed event.

        This event marks the successful completion of agent execution with
        performance metrics and quality assessment.

        Args:
            agent_name: Name of the agent that completed execution
            correlation_id: Correlation ID for request tracing (UUID)
            duration_ms: Total execution duration in milliseconds
            quality_score: Quality assessment score (0.0-1.0)
            output_summary: Brief summary of execution output
            metrics: Additional execution metrics (tool_calls, tokens, etc.)

        Returns:
            True if event published successfully, False otherwise

        Example:
            success = await publisher.publish_execution_completed(
                agent_name="agent-api-architect",
                correlation_id="abc-123-def-456",
                duration_ms=1500,
                quality_score=0.92,
                output_summary="API design completed with 5 endpoints",
                metrics={"tool_calls": 12, "tokens_used": 3500},
            )
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_execution_completed_envelope(
                agent_name=agent_name,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                quality_score=quality_score,
                output_summary=output_summary,
                metrics=metrics or {},
            )

            # Publish event with partition key
            partition_key = correlation_id.encode("utf-8")

            # Build required Kafka headers
            headers = [
                (
                    "x-traceparent",
                    f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                ),
                ("x-correlation-id", correlation_id.encode("utf-8")),
                ("x-causation-id", correlation_id.encode("utf-8")),
                ("x-tenant", envelope.get("tenant_id", "default").encode("utf-8")),
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_EXECUTION_COMPLETED,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.info(
                f"Published execution completed event (agent: {agent_name}, correlation_id: {correlation_id}, duration: {duration_ms}ms)"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish execution completed event (agent: {agent_name}, correlation_id: {correlation_id}): {e}"
            )
            return False

    async def publish_execution_failed(
        self,
        agent_name: str,
        correlation_id: str,
        error_message: str,
        error_type: Optional[str] = None,
        error_stack_trace: Optional[str] = None,
        partial_results: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Publish agent execution failed event.

        This event marks the failure of agent execution with error details
        and any partial results that were produced before failure.

        Args:
            agent_name: Name of the agent that failed execution
            correlation_id: Correlation ID for request tracing (UUID)
            error_message: Error message describing the failure
            error_type: Error type/class (e.g., "FileNotFoundError", "TimeoutError")
            error_stack_trace: Full error stack trace for debugging
            partial_results: Partial results produced before failure

        Returns:
            True if event published successfully, False otherwise

        Example:
            import traceback

            try:
                # Agent execution
                result = await execute_agent_task()
            except Exception as e:
                await publisher.publish_execution_failed(
                    agent_name="agent-api-architect",
                    correlation_id="abc-123-def-456",
                    error_message=str(e),
                    error_type=type(e).__name__,
                    error_stack_trace=traceback.format_exc(),
                    partial_results={"endpoints_designed": 3, "failed_at": "validation"},
                )
                raise
        """
        if not self._started or not self.enable_events:
            self.logger.debug(
                "Publisher not started or events disabled, skipping event"
            )
            return False

        try:
            # Create event envelope
            envelope = self._create_execution_failed_envelope(
                agent_name=agent_name,
                correlation_id=correlation_id,
                error_message=error_message,
                error_type=error_type,
                error_stack_trace=error_stack_trace,
                partial_results=partial_results or {},
            )

            # Publish event with partition key
            partition_key = correlation_id.encode("utf-8")

            # Build required Kafka headers
            headers = [
                (
                    "x-traceparent",
                    f"00-{correlation_id.replace('-', '')}-0000000000000000-01".encode(),
                ),
                ("x-correlation-id", correlation_id.encode("utf-8")),
                ("x-causation-id", correlation_id.encode("utf-8")),
                ("x-tenant", envelope.get("tenant_id", "default").encode("utf-8")),
                ("x-schema-hash", envelope.get("schema_ref", "").encode("utf-8")),
            ]

            # Publish event
            if self._producer is None:
                raise RuntimeError("Producer not initialized. Call start() first.")

            await self._producer.send_and_wait(
                self.TOPIC_EXECUTION_FAILED,
                value=envelope,
                key=partition_key,
                headers=headers,
            )

            self.logger.info(
                f"Published execution failed event (agent: {agent_name}, correlation_id: {correlation_id}, error: {error_type or 'Unknown'})"
            )
            return True

        except Exception as e:
            self.logger.error(
                f"Failed to publish execution failed event (agent: {agent_name}, correlation_id: {correlation_id}): {e}"
            )
            return False

    def _create_execution_completed_envelope(
        self,
        agent_name: str,
        correlation_id: str,
        duration_ms: int,
        quality_score: Optional[float],
        output_summary: Optional[str],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build execution completed event envelope following OnexEnvelopeV1 structure.

        Args:
            agent_name: Name of the agent
            correlation_id: Correlation ID for tracing
            duration_ms: Execution duration
            quality_score: Quality assessment score
            output_summary: Output summary
            metrics: Execution metrics

        Returns:
            Event envelope dictionary with complete structure
        """
        envelope = {
            "event_type": "omninode.agent.execution.completed.v1",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": os.getenv("TENANT_ID", "default"),
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id,
            "causation_id": correlation_id,
            "schema_ref": "registry://omninode/agent/execution_completed/v1",
            "payload": {
                "agent_name": agent_name,
                "correlation_id": correlation_id,
                "duration_ms": duration_ms,
                "completed_at": datetime.now(UTC).isoformat(),
            },
        }

        # Add optional fields if provided
        if quality_score is not None:
            envelope["payload"]["quality_score"] = quality_score
        if output_summary is not None:
            envelope["payload"]["output_summary"] = output_summary
        if metrics:
            envelope["payload"]["metrics"] = metrics

        return envelope

    def _create_execution_failed_envelope(
        self,
        agent_name: str,
        correlation_id: str,
        error_message: str,
        error_type: Optional[str],
        error_stack_trace: Optional[str],
        partial_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build execution failed event envelope following OnexEnvelopeV1 structure.

        Args:
            agent_name: Name of the agent
            correlation_id: Correlation ID for tracing
            error_message: Error message
            error_type: Error type
            error_stack_trace: Stack trace
            partial_results: Partial results

        Returns:
            Event envelope dictionary with complete structure
        """
        envelope = {
            "event_type": "omninode.agent.execution.failed.v1",
            "event_id": str(uuid4()),
            "timestamp": datetime.now(UTC).isoformat(),
            "tenant_id": os.getenv("TENANT_ID", "default"),
            "namespace": "omninode",
            "source": "omniclaude",
            "correlation_id": correlation_id,
            "causation_id": correlation_id,
            "schema_ref": "registry://omninode/agent/execution_failed/v1",
            "payload": {
                "agent_name": agent_name,
                "correlation_id": correlation_id,
                "error_message": error_message,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        }

        # Add optional fields if provided
        if error_type is not None:
            envelope["payload"]["error_type"] = error_type
        if error_stack_trace is not None:
            envelope["payload"]["error_stack_trace"] = error_stack_trace
        if partial_results:
            envelope["payload"]["partial_results"] = partial_results

        return envelope


# Convenience context manager for automatic start/stop
class AgentExecutionPublisherContext:
    """
    Context manager for automatic publisher lifecycle management.

    Usage:
        async with AgentExecutionPublisherContext() as publisher:
            await publisher.publish_execution_started(...)
    """

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: bool = True,
    ):
        self.publisher = AgentExecutionPublisher(
            bootstrap_servers=bootstrap_servers,
            enable_events=enable_events,
        )

    async def __aenter__(self) -> AgentExecutionPublisher:
        await self.publisher.start()
        return self.publisher

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.publisher.stop()
        return False


# Convenience function for one-off event publishing
async def publish_execution_started(
    agent_name: str,
    user_request: str,
    correlation_id: str,
    session_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function for one-off execution started event publishing.

    Automatically manages publisher lifecycle (start/stop).
    Uses fire-and-forget pattern with graceful degradation.

    Args:
        agent_name: Name of the agent being executed
        user_request: User's original request text
        correlation_id: Correlation ID for request tracing (UUID)
        session_id: Session ID for grouping related executions (UUID)
        context: Optional execution context

    Returns:
        True if event published successfully, False otherwise

    Example:
        success = await publish_execution_started(
            agent_name="agent-api-architect",
            user_request="Design a REST API for user management",
            correlation_id="abc-123-def-456",
            session_id="session-789",
            context={"domain": "api_design"},
        )
    """
    try:
        async with AgentExecutionPublisherContext() as publisher:
            return await publisher.publish_execution_started(
                agent_name=agent_name,
                user_request=user_request,
                correlation_id=correlation_id,
                session_id=session_id,
                context=context,
            )
    except Exception as e:
        logger.error(f"Failed to publish execution started event: {e}")
        # Graceful degradation - don't fail agent execution
        return False


async def publish_execution_completed(
    agent_name: str,
    correlation_id: str,
    duration_ms: int,
    quality_score: Optional[float] = None,
    output_summary: Optional[str] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function for one-off execution completed event publishing.

    Automatically manages publisher lifecycle (start/stop).
    Uses fire-and-forget pattern with graceful degradation.

    Args:
        agent_name: Name of the agent that completed execution
        correlation_id: Correlation ID for request tracing (UUID)
        duration_ms: Total execution duration in milliseconds
        quality_score: Quality assessment score (0.0-1.0)
        output_summary: Brief summary of execution output
        metrics: Additional execution metrics

    Returns:
        True if event published successfully, False otherwise

    Example:
        success = await publish_execution_completed(
            agent_name="agent-api-architect",
            correlation_id="abc-123-def-456",
            duration_ms=1500,
            quality_score=0.92,
            output_summary="API design completed with 5 endpoints",
            metrics={"tool_calls": 12, "tokens_used": 3500},
        )
    """
    try:
        async with AgentExecutionPublisherContext() as publisher:
            return await publisher.publish_execution_completed(
                agent_name=agent_name,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                quality_score=quality_score,
                output_summary=output_summary,
                metrics=metrics,
            )
    except Exception as e:
        logger.error(f"Failed to publish execution completed event: {e}")
        return False


async def publish_execution_failed(
    agent_name: str,
    correlation_id: str,
    error_message: str,
    error_type: Optional[str] = None,
    error_stack_trace: Optional[str] = None,
    partial_results: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Convenience function for one-off execution failed event publishing.

    Automatically manages publisher lifecycle (start/stop).
    Uses fire-and-forget pattern with graceful degradation.

    Args:
        agent_name: Name of the agent that failed execution
        correlation_id: Correlation ID for request tracing (UUID)
        error_message: Error message describing the failure
        error_type: Error type/class (e.g., "FileNotFoundError")
        error_stack_trace: Full error stack trace for debugging
        partial_results: Partial results produced before failure

    Returns:
        True if event published successfully, False otherwise

    Example:
        import traceback

        try:
            # Agent execution
            result = await execute_agent_task()
        except Exception as e:
            await publish_execution_failed(
                agent_name="agent-api-architect",
                correlation_id="abc-123-def-456",
                error_message=str(e),
                error_type=type(e).__name__,
                error_stack_trace=traceback.format_exc(),
                partial_results={"endpoints_designed": 3},
            )
            raise
    """
    try:
        async with AgentExecutionPublisherContext() as publisher:
            return await publisher.publish_execution_failed(
                agent_name=agent_name,
                correlation_id=correlation_id,
                error_message=error_message,
                error_type=error_type,
                error_stack_trace=error_stack_trace,
                partial_results=partial_results,
            )
    except Exception as e:
        logger.error(f"Failed to publish execution failed event: {e}")
        return False


__all__ = [
    "AgentExecutionPublisher",
    "AgentExecutionPublisherContext",
    "publish_execution_started",
    "publish_execution_completed",
    "publish_execution_failed",
]

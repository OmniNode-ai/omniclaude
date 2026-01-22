#!/usr/bin/env python3
"""
Hook Event Adapter - Unified Event Publishing for Hooks

Provides a synchronous wrapper around the event publishing infrastructure
for use in hooks. Uses the same Kafka infrastructure as IntelligenceEventClient
but with a synchronous interface suitable for hook scripts.

This adapter publishes observability events (routing decisions, agent actions,
performance metrics, etc.) through the unified event bus architecture.

Usage:
    from hook_event_adapter import HookEventAdapter

    adapter = HookEventAdapter()

    # Publish routing decision
    adapter.publish_routing_decision(
        agent_name="agent-research",
        confidence=0.95,
        strategy="fuzzy_matching",
        latency_ms=45,
        correlation_id="uuid",
    )

    # Publish agent action
    adapter.publish_agent_action(
        agent_name="agent-research",
        action_type="tool_call",
        action_name="grep_codebase",
        correlation_id="uuid",
    )
"""

import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure project root is in path for imports
# This file is at: claude/hooks/lib/hook_event_adapter.py
# Project root is 3 levels up: lib -> hooks -> claude -> project_root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ONEX error handling
try:
    from claude.lib.core import EnumCoreErrorCode, OnexError
except ImportError:
    from agents.lib.errors import EnumCoreErrorCode, OnexError


# Use kafka-python for synchronous publishing (simpler for hooks)
# Graceful degradation: if kafka-python is not installed, we skip Kafka operations
# but don't crash the hook. This is defense-in-depth - the hooks venv should have
# the package, but we handle the case where it doesn't gracefully.
KAFKA_AVAILABLE = False
KafkaProducer = None  # type: ignore

try:
    from kafka import KafkaProducer as _KafkaProducer

    KafkaProducer = _KafkaProducer
    KAFKA_AVAILABLE = True
except ImportError:
    # Log warning but don't crash - hooks will continue without Kafka
    import sys

    print(
        "WARNING: kafka-python not installed. Kafka event publishing disabled. "
        "Run: ~/.claude/hooks/setup-venv.sh",
        file=sys.stderr,
    )

logger = logging.getLogger(__name__)


class HookEventAdapter:
    """
    Synchronous event adapter for hook scripts.

    Provides a simple, synchronous interface for publishing observability events
    from hooks to the unified event bus.

    Features:
    - Synchronous API (suitable for hooks)
    - Uses same Kafka infrastructure as IntelligenceEventClient
    - Automatic topic routing based on event type
    - JSON serialization
    - Graceful error handling (non-blocking)
    """

    # Event topics (ONEX event bus architecture)
    TOPIC_ROUTING_DECISIONS = "agent-routing-decisions"
    TOPIC_AGENT_ACTIONS = "agent-actions"
    TOPIC_PERFORMANCE_METRICS = "router-performance-metrics"
    TOPIC_TRANSFORMATIONS = "agent-transformation-events"
    TOPIC_DETECTION_FAILURES = "agent-detection-failures"

    def __init__(
        self,
        bootstrap_servers: str | None = None,
        enable_events: bool = True,
    ):
        """
        Initialize hook event adapter.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - Default: KAFKA_BOOTSTRAP_SERVERS env var or "omninode-bridge-redpanda:9092"
                - Remote broker: "192.168.86.200:9092" (primary)
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_events: Enable event publishing (feature flag)
        """
        self.bootstrap_servers = bootstrap_servers or os.environ.get(
            "KAFKA_BOOTSTRAP_SERVERS", "omninode-bridge-redpanda:9092"
        )
        # Disable events if Kafka is not available
        self.enable_events = enable_events and KAFKA_AVAILABLE

        self._producer: Any | None = None  # KafkaProducer or None
        self._initialized = False
        self._kafka_available = KAFKA_AVAILABLE

        self.logger = logging.getLogger(__name__)

    def _get_producer(self) -> Any:
        """
        Get or create Kafka producer (lazy initialization).

        Returns:
            Kafka producer instance, or None if Kafka is not available

        Raises:
            OnexError: If Kafka is not available (EXTERNAL_SERVICE_ERROR)
            KafkaProducerError: If producer creation fails
        """
        if not self._kafka_available or KafkaProducer is None:
            raise OnexError(
                code=EnumCoreErrorCode.EXTERNAL_SERVICE_ERROR,
                message="Kafka is not available. Run: ~/.claude/hooks/setup-venv.sh",
            )

        if self._producer is None:
            try:
                # Configurable timeouts from environment variables
                request_timeout_ms = int(os.environ.get("KAFKA_REQUEST_TIMEOUT_MS", "1000"))
                connections_max_idle_ms = int(
                    os.environ.get("KAFKA_CONNECTIONS_MAX_IDLE_MS", "5000")
                )
                metadata_max_age_ms = int(os.environ.get("KAFKA_METADATA_MAX_AGE_MS", "5000"))
                max_block_ms = int(os.environ.get("KAFKA_MAX_BLOCK_MS", "2000"))

                self._producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    # Performance settings
                    compression_type="gzip",
                    linger_ms=10,  # Batch messages for 10ms
                    batch_size=16384,  # 16KB batches
                    # Reliability settings
                    acks=1,  # Wait for leader acknowledgment
                    retries=2,  # Reduced from 3 for faster failure
                    max_in_flight_requests_per_connection=5,
                    # Configurable timeout settings to prevent hangs
                    request_timeout_ms=request_timeout_ms,
                    connections_max_idle_ms=connections_max_idle_ms,
                    metadata_max_age_ms=metadata_max_age_ms,
                    max_block_ms=max_block_ms,
                    api_version_auto_timeout_ms=1000,  # 1s for API version detection
                )
                self._initialized = True
                self.logger.debug(f"Initialized Kafka producer (brokers: {self.bootstrap_servers})")
            except Exception as e:
                self.logger.error(f"Failed to create Kafka producer: {e}")
                raise

        return self._producer

    def _publish(self, topic: str, event: dict[str, Any]) -> bool:
        """
        Publish event to Kafka topic.

        Args:
            topic: Kafka topic name
            event: Event dictionary to publish

        Returns:
            True if published successfully, False otherwise
        """
        if not self.enable_events:
            self.logger.debug("Event publishing disabled via feature flag")
            return False

        if not self._kafka_available:
            self.logger.debug("Kafka not available, skipping event publish")
            return False

        try:
            producer = self._get_producer()

            # Use correlation_id for partitioning (maintains ordering per correlation)
            partition_key = event.get("correlation_id", "").encode("utf-8")

            # Publish sync (simpler for hooks)
            future = producer.send(topic, value=event, key=partition_key)

            # Wait up to 1 second for send to complete
            future.get(timeout=1.0)

            self.logger.debug(
                f"Published event to {topic} (correlation_id: {event.get('correlation_id')})"
            )
            return True

        except Exception as e:
            # Log error but don't fail - this is observability, not critical path
            self.logger.error(f"Failed to publish event to {topic}: {e}")
            return False

    def publish_routing_decision(
        self,
        agent_name: str,
        confidence: float,
        strategy: str,
        latency_ms: int,
        correlation_id: str,
        user_request: str | None = None,
        alternatives: list | None = None,
        reasoning: str | None = None,
        context: dict[str, Any] | None = None,
        project_path: str | None = None,
        project_name: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """
        Publish agent routing decision event.

        Args:
            agent_name: Selected agent name
            confidence: Confidence score (0.0-1.0)
            strategy: Routing strategy used
            latency_ms: Routing latency in milliseconds
            correlation_id: Correlation ID for tracking
            user_request: Original user request text
            alternatives: List of alternative agents considered
            reasoning: Reasoning for agent selection
            context: Additional context
            project_path: Absolute path to project directory
            project_name: Project name
            session_id: Claude session ID

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "user_request": user_request or "",
            "selected_agent": agent_name,
            "confidence_score": confidence,
            "alternatives": alternatives or [],
            "reasoning": reasoning,
            "routing_strategy": strategy,
            "context": context or {},
            "routing_time_ms": latency_ms,
            "project_path": project_path,
            "project_name": project_name,
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_ROUTING_DECISIONS, event)

    def publish_agent_action(
        self,
        agent_name: str,
        action_type: str,
        action_name: str,
        correlation_id: str,
        action_details: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        success: bool = True,
        debug_mode: bool = True,
        project_path: str | None = None,
        project_name: str | None = None,
        working_directory: str | None = None,
    ) -> bool:
        """
        Publish agent action event.

        Args:
            agent_name: Agent performing the action
            action_type: Type of action (tool_call, decision, error, success)
            action_name: Specific action name
            correlation_id: Correlation ID for tracking
            action_details: Action-specific details (matches consumer schema)
            duration_ms: Action duration in milliseconds
            success: Whether action succeeded
            debug_mode: Enable debug information in consumer
            project_path: Absolute path to project directory
            project_name: Project name
            working_directory: Current working directory

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_name": action_name,
            "action_details": action_details or {},
            "duration_ms": duration_ms,
            "success": success,
            "debug_mode": debug_mode,
            "project_path": project_path,
            "project_name": project_name,
            "working_directory": working_directory,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_AGENT_ACTIONS, event)

    def publish_performance_metrics(
        self,
        agent_name: str,
        metric_name: str,
        metric_value: float,
        correlation_id: str,
        metric_type: str = "gauge",
        metric_unit: str | None = None,
        tags: dict[str, str] | None = None,
    ) -> bool:
        """
        Publish agent performance metrics event.

        Args:
            agent_name: Agent name
            metric_name: Metric name
            metric_value: Metric value
            correlation_id: Correlation ID for tracking
            metric_type: Metric type (gauge, counter, histogram)
            metric_unit: Metric unit (ms, bytes, count, etc.)
            tags: Metric tags

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "metric_type": metric_type,
            "metric_unit": metric_unit,
            "tags": tags or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_PERFORMANCE_METRICS, event)

    def publish_transformation(
        self,
        agent_name: str,
        transformation_type: str,
        correlation_id: str,
        input_data: dict[str, Any] | None = None,
        output_data: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Publish agent transformation event.

        Args:
            agent_name: Agent performing transformation
            transformation_type: Type of transformation
            correlation_id: Correlation ID for tracking
            input_data: Input data (before transformation)
            output_data: Output data (after transformation)
            metadata: Transformation metadata

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "transformation_type": transformation_type,
            "input_data": input_data or {},
            "output_data": output_data or {},
            "metadata": metadata or {},
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_TRANSFORMATIONS, event)

    def publish_detection_failure(
        self,
        user_request: str,
        failure_reason: str,
        attempted_methods: list | None = None,
        error_details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        project_path: str | None = None,
        project_name: str | None = None,
        session_id: str | None = None,
    ) -> bool:
        """
        Publish agent detection failure event.

        Args:
            user_request: User's original request text
            failure_reason: Why detection failed
            attempted_methods: List of detection methods tried
            error_details: Additional error information
            correlation_id: Correlation ID for tracking
            project_path: Absolute path to project directory
            project_name: Project name
            session_id: Claude session ID

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id or str(uuid.uuid4()),
            "user_request": user_request,
            "failure_reason": failure_reason,
            "attempted_methods": attempted_methods or [],
            "error_details": error_details or {},
            "project_path": project_path,
            "project_name": project_name,
            "session_id": session_id,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_DETECTION_FAILURES, event)

    def close(self) -> None:
        """
        Close Kafka producer connection.

        Should be called when adapter is no longer needed.
        """
        if self._producer is not None:
            try:
                self._producer.flush()
                self._producer.close()
                self.logger.debug("Kafka producer closed")
            except Exception as e:
                self.logger.error(f"Error closing Kafka producer: {e}")
            finally:
                self._producer = None
                self._initialized = False


# Singleton instance for reuse across hooks
_adapter_instance: HookEventAdapter | None = None


def get_hook_event_adapter() -> HookEventAdapter:
    """
    Get singleton hook event adapter instance.

    Returns:
        HookEventAdapter instance
    """
    global _adapter_instance

    if _adapter_instance is None:
        _adapter_instance = HookEventAdapter()

    return _adapter_instance


__all__ = [
    "HookEventAdapter",
    "get_hook_event_adapter",
]

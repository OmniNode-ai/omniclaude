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
from datetime import UTC, datetime
from typing import Any, Dict, Optional

# Use kafka-python for synchronous publishing (simpler for hooks)
try:
    from kafka import KafkaProducer
except ImportError:
    raise ImportError(
        "kafka-python not installed. Install with: pip install kafka-python"
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
    TOPIC_PERFORMANCE_METRICS = "agent-performance-metrics"
    TOPIC_TRANSFORMATIONS = "agent-transformations"

    def __init__(
        self,
        bootstrap_servers: Optional[str] = None,
        enable_events: bool = True,
    ):
        """
        Initialize hook event adapter.

        Args:
            bootstrap_servers: Kafka bootstrap servers
                - Default: KAFKA_BROKERS env var or "localhost:29092"
                - External host: "localhost:29092" (Redpanda port mapping)
                - Docker internal: "omninode-bridge-redpanda:9092"
            enable_events: Enable event publishing (feature flag)
        """
        self.bootstrap_servers = bootstrap_servers or os.environ.get(
            "KAFKA_BROKERS", "localhost:29092"
        )
        self.enable_events = enable_events

        self._producer: Optional[KafkaProducer] = None
        self._initialized = False

        self.logger = logging.getLogger(__name__)

    def _get_producer(self) -> KafkaProducer:
        """
        Get or create Kafka producer (lazy initialization).

        Returns:
            Kafka producer instance

        Raises:
            KafkaProducerError: If producer creation fails
        """
        if self._producer is None:
            try:
                self._producer = KafkaProducer(
                    bootstrap_servers=self.bootstrap_servers.split(","),
                    value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                    # Performance settings
                    compression_type="gzip",
                    linger_ms=10,  # Batch messages for 10ms
                    batch_size=16384,  # 16KB batches
                    # Reliability settings
                    acks=1,  # Wait for leader acknowledgment
                    retries=3,
                    max_in_flight_requests_per_connection=5,
                )
                self._initialized = True
                self.logger.debug(
                    f"Initialized Kafka producer (brokers: {self.bootstrap_servers})"
                )
            except Exception as e:
                self.logger.error(f"Failed to create Kafka producer: {e}")
                raise

        return self._producer

    def _publish(self, topic: str, event: Dict[str, Any]) -> bool:
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
        user_request: Optional[str] = None,
        alternatives: Optional[list] = None,
        reasoning: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
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
            "timestamp": datetime.now(UTC).isoformat(),
        }

        return self._publish(self.TOPIC_ROUTING_DECISIONS, event)

    def publish_agent_action(
        self,
        agent_name: str,
        action_type: str,
        action_name: str,
        correlation_id: str,
        details: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        success: bool = True,
    ) -> bool:
        """
        Publish agent action event.

        Args:
            agent_name: Agent performing the action
            action_type: Type of action (tool_call, decision, error, success)
            action_name: Specific action name
            correlation_id: Correlation ID for tracking
            details: Action-specific details
            duration_ms: Action duration in milliseconds
            success: Whether action succeeded

        Returns:
            True if published successfully, False otherwise
        """
        event = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_name": action_name,
            "details": details or {},
            "duration_ms": duration_ms,
            "success": success,
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
        metric_unit: Optional[str] = None,
        tags: Optional[Dict[str, str]] = None,
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
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
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
_adapter_instance: Optional[HookEventAdapter] = None


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

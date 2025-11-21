"""
Traceability Kafka Events - Real-time Agent Observability

Publishes traceability events to Kafka for real-time monitoring:
1. Prompt events - User prompts submitted
2. File operation events - File reads/writes
3. Intelligence usage events - Pattern/schema usage

Event Topics:
- agent-traceability.prompts.v1
- agent-traceability.file-operations.v1
- agent-traceability.intelligence-usage.v1

Usage:
    publisher = TraceabilityEventPublisher()

    await publisher.publish_prompt_event(
        correlation_id=correlation_id,
        agent_name="agent-researcher",
        user_prompt=user_prompt,
        prompt_id=prompt_id
    )

    await publisher.publish_file_operation_event(
        correlation_id=correlation_id,
        agent_name="agent-researcher",
        operation_type="read",
        file_path="/path/to/file.py",
        file_op_id=file_op_id
    )

    await publisher.publish_intelligence_usage_event(
        correlation_id=correlation_id,
        agent_name="agent-researcher",
        intelligence_type="pattern",
        intelligence_name="Node State Management",
        was_applied=True,
        intel_usage_id=intel_usage_id
    )
"""

import json
import os
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from .structured_logger import StructuredLogger


# Try to import Kafka client
try:
    from confluent_kafka import Producer as ConfluentProducer

    KAFKA_AVAILABLE = True
except ImportError:
    KAFKA_AVAILABLE = False
    ConfluentProducer = None


class TraceabilityEventPublisher:
    """
    Publishes traceability events to Kafka for real-time monitoring.
    """

    def __init__(self, kafka_brokers: Optional[str] = None):
        """
        Initialize Kafka event publisher.

        Args:
            kafka_brokers: Kafka bootstrap servers (default: from environment)
        """
        self.kafka_brokers = kafka_brokers or os.getenv(
            "KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092"
        )
        self.logger = StructuredLogger("traceability_events", component="traceability")

        # Initialize Kafka producer
        self.producer: Optional[ConfluentProducer] = None
        self.kafka_enabled = (
            KAFKA_AVAILABLE
            and os.getenv("KAFKA_ENABLE_TRACEABILITY", "true").lower() == "true"
        )

        if self.kafka_enabled:
            try:
                self.producer = ConfluentProducer(
                    {
                        "bootstrap.servers": self.kafka_brokers,
                        "client.id": "agent-traceability-publisher",
                        "acks": "1",  # Wait for leader acknowledgment
                        "compression.type": "snappy",
                        "linger.ms": 10,  # Batch messages for up to 10ms
                    }
                )
                self.logger.info(
                    "Kafka traceability publisher initialized",
                    metadata={"brokers": self.kafka_brokers},
                )
            except Exception as e:
                self.logger.warning(
                    "Failed to initialize Kafka producer for traceability",
                    metadata={"error": str(e)},
                )
                self.producer = None
                self.kafka_enabled = False

    def _delivery_callback(self, err, msg):
        """Kafka delivery callback."""
        if err:
            self.logger.error(
                "Kafka message delivery failed",
                metadata={"error": str(err), "topic": msg.topic()},
            )
        else:
            self.logger.debug(
                "Kafka message delivered",
                metadata={"topic": msg.topic(), "partition": msg.partition()},
            )

    async def publish_prompt_event(
        self,
        correlation_id: UUID | str,
        agent_name: str,
        user_prompt: str,
        prompt_id: UUID | str,
        user_prompt_length: int,
        agent_instructions_length: Optional[int] = None,
        manifest_injection_id: Optional[UUID | str] = None,
        claude_session_id: Optional[str] = None,
    ):
        """
        Publish prompt event to Kafka.

        Args:
            correlation_id: Correlation ID
            agent_name: Agent name
            user_prompt: User prompt (truncated for event)
            prompt_id: Prompt ID from database
            user_prompt_length: Length of user prompt
            agent_instructions_length: Length of agent instructions
            manifest_injection_id: Link to manifest
            claude_session_id: Claude session ID
        """
        if not self.kafka_enabled or not self.producer:
            return

        event = {
            "event_type": "prompt_captured",
            "event_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(correlation_id),
            "agent_name": agent_name,
            "prompt_id": str(prompt_id),
            "user_prompt_preview": user_prompt[:500],  # First 500 chars
            "user_prompt_length": user_prompt_length,
            "agent_instructions_length": agent_instructions_length,
            "manifest_injection_id": (
                str(manifest_injection_id) if manifest_injection_id else None
            ),
            "claude_session_id": claude_session_id,
        }

        try:
            self.producer.produce(
                topic="agent-traceability.prompts.v1",
                key=str(correlation_id),
                value=json.dumps(event),
                callback=self._delivery_callback,
            )
            self.producer.poll(0)  # Non-blocking poll

        except Exception as e:
            self.logger.error(
                "Failed to publish prompt event",
                metadata={"error": str(e), "correlation_id": str(correlation_id)},
            )

    async def publish_file_operation_event(
        self,
        correlation_id: UUID | str,
        agent_name: str,
        operation_type: str,
        file_path: str,
        file_op_id: UUID | str,
        content_changed: bool = False,
        tool_name: Optional[str] = None,
        matched_pattern_count: int = 0,
        duration_ms: Optional[int] = None,
        success: bool = True,
    ):
        """
        Publish file operation event to Kafka.

        Args:
            correlation_id: Correlation ID
            agent_name: Agent name
            operation_type: Operation type (read, write, edit, etc)
            file_path: File path
            file_op_id: File operation ID from database
            content_changed: Whether content was modified
            tool_name: Tool used
            matched_pattern_count: Number of patterns matched
            duration_ms: Operation duration
            success: Whether operation succeeded
        """
        if not self.kafka_enabled or not self.producer:
            return

        event = {
            "event_type": "file_operation",
            "event_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(correlation_id),
            "agent_name": agent_name,
            "file_op_id": str(file_op_id),
            "operation_type": operation_type,
            "file_path": file_path,
            "content_changed": content_changed,
            "tool_name": tool_name,
            "matched_pattern_count": matched_pattern_count,
            "duration_ms": duration_ms,
            "success": success,
        }

        try:
            self.producer.produce(
                topic="agent-traceability.file-operations.v1",
                key=str(correlation_id),
                value=json.dumps(event),
                callback=self._delivery_callback,
            )
            self.producer.poll(0)  # Non-blocking poll

        except Exception as e:
            self.logger.error(
                "Failed to publish file operation event",
                metadata={"error": str(e), "correlation_id": str(correlation_id)},
            )

    async def publish_intelligence_usage_event(
        self,
        correlation_id: UUID | str,
        agent_name: str,
        intelligence_type: str,
        intelligence_source: str,
        intelligence_name: Optional[str],
        intel_usage_id: UUID | str,
        was_applied: bool = False,
        confidence_score: Optional[float] = None,
        quality_impact: Optional[float] = None,
        usage_context: str = "reference",
    ):
        """
        Publish intelligence usage event to Kafka.

        Args:
            correlation_id: Correlation ID
            agent_name: Agent name
            intelligence_type: Type (pattern, schema, etc)
            intelligence_source: Source (qdrant, memgraph, etc)
            intelligence_name: Intelligence name
            intel_usage_id: Intelligence usage ID from database
            was_applied: Whether intelligence was applied
            confidence_score: Confidence score
            quality_impact: Quality impact
            usage_context: Usage context
        """
        if not self.kafka_enabled or not self.producer:
            return

        event = {
            "event_type": "intelligence_usage",
            "event_version": "1.0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": str(correlation_id),
            "agent_name": agent_name,
            "intel_usage_id": str(intel_usage_id),
            "intelligence_type": intelligence_type,
            "intelligence_source": intelligence_source,
            "intelligence_name": intelligence_name,
            "was_applied": was_applied,
            "confidence_score": confidence_score,
            "quality_impact": quality_impact,
            "usage_context": usage_context,
        }

        try:
            self.producer.produce(
                topic="agent-traceability.intelligence-usage.v1",
                key=str(correlation_id),
                value=json.dumps(event),
                callback=self._delivery_callback,
            )
            self.producer.poll(0)  # Non-blocking poll

        except Exception as e:
            self.logger.error(
                "Failed to publish intelligence usage event",
                metadata={"error": str(e), "correlation_id": str(correlation_id)},
            )

    def flush(self, timeout: float = 5.0):
        """
        Flush pending messages to Kafka.

        Args:
            timeout: Maximum time to wait in seconds
        """
        if self.producer:
            try:
                remaining = self.producer.flush(timeout)
                if remaining > 0:
                    self.logger.warning(
                        f"Failed to flush {remaining} messages within {timeout}s"
                    )
            except Exception as e:
                self.logger.error(
                    "Error flushing Kafka messages", metadata={"error": str(e)}
                )

    def __del__(self):
        """Cleanup: flush remaining messages."""
        if self.producer:
            self.flush(timeout=2.0)


# Global publisher instance
_global_publisher: Optional[TraceabilityEventPublisher] = None


def get_traceability_publisher() -> TraceabilityEventPublisher:
    """
    Get or create global traceability event publisher.

    Returns:
        TraceabilityEventPublisher instance
    """
    global _global_publisher
    if _global_publisher is None:
        _global_publisher = TraceabilityEventPublisher()
    return _global_publisher

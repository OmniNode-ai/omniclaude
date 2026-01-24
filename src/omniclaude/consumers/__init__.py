"""Kafka consumers for Claude Code hook events.

This module provides consumers that subscribe to Claude Code hook event topics
and process incoming events for session aggregation and storage.

Key Components:
    - SessionEventConsumer: Main Kafka consumer with at-least-once delivery
    - ConfigSessionConsumer: Configuration for the consumer
    - ConsumerMetrics: Metrics tracking for observability
    - EnumCircuitState: Circuit breaker state enum

Architecture:
    The consumer subscribes to Claude Code hook event topics and processes
    events through a ProtocolSessionAggregator. It implements at-least-once
    delivery by committing Kafka offsets only after successful processing.

    ```
    Kafka Topics (session/prompt/tool)
           |
           v
    SessionEventConsumer
           |
           v (process_event)
    ProtocolSessionAggregator
           |
           v
    Session Snapshots (storage)
    ```

Example:
    >>> from omniclaude.consumers import SessionEventConsumer, ConfigSessionConsumer
    >>> from my_aggregator import MySessionAggregator
    >>>
    >>> config = ConfigSessionConsumer()
    >>> aggregator = MySessionAggregator()
    >>> consumer = SessionEventConsumer(config=config, aggregator=aggregator)
    >>>
    >>> async with consumer:
    ...     await consumer.run()

Related Tickets:
    - OMN-1401: Session storage in OmniMemory (current)
    - OMN-1400: Hook handlers emit to Kafka
"""

from __future__ import annotations

from omniclaude.consumers.config import ConfigSessionConsumer
from omniclaude.consumers.session_event_consumer import (
    ConsumerMetrics,
    EnumCircuitState,
    SessionEventConsumer,
)

__all__ = [
    # Main consumer
    "SessionEventConsumer",
    # Configuration
    "ConfigSessionConsumer",
    # Metrics and enums
    "ConsumerMetrics",
    "EnumCircuitState",
]

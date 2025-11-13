#!/usr/bin/env python3
"""
Kafka Topics for Agent Routing Events

Defines Kafka topic names for agent routing event flow.
Follows EVENT_BUS_INTEGRATION_GUIDE standard format.

Topic Naming Convention (per EVENT_BUS_INTEGRATION_GUIDE):
    Format: omninode.{domain}.{entity}.{action}.v{major}
    Examples:
        - omninode.agent.routing.requested.v1
        - omninode.agent.routing.completed.v1
        - omninode.agent.routing.failed.v1

Event Flow:
    1. Agent publishes: omninode.agent.routing.requested.v1
    2. agent-router-service consumes request
    3. agent-router-service publishes one of:
        - omninode.agent.routing.completed.v1 (success)
        - omninode.agent.routing.failed.v1 (failure)
    4. Agent consumes response

Partition Key Policy (per EVENT_BUS_INTEGRATION_GUIDE):
    - Uses correlation_id as partition key
    - Cardinality: Medium (per request)
    - Ensures request→response ordering per workflow

Topic Configuration:
    - Partitions: 3 (for parallel processing)
    - Replication Factor: 1 (single broker dev environment)
    - Retention: 7 days (168 hours)
    - Compression: gzip (for efficiency)

Usage:
    ```python
    from routing_adapter.schemas.topics import TOPICS

    # Publish request
    await producer.send(TOPICS.REQUEST, envelope.model_dump())

    # Subscribe to responses
    consumer = AIOKafkaConsumer(
        TOPICS.COMPLETED,
        TOPICS.FAILED,
        bootstrap_servers=kafka_servers
    )
    ```

Created: 2025-10-30
Reference: database_event_client.py (topic naming pattern)
"""

from typing import Final


class RoutingTopics:
    """
    Kafka topic names for agent routing events.
    Follows EVENT_BUS_INTEGRATION_GUIDE standard format.

    Attributes:
        REQUEST: Agent routing request topic
        COMPLETED: Routing completed successfully topic
        FAILED: Routing failed with error topic
    """

    # Request topic (published by agents)
    # Format: omninode.{domain}.{entity}.{action}.v{major}
    REQUEST: Final[str] = "omninode.agent.routing.requested.v1"

    # Response topics (published by agent-router-service)
    COMPLETED: Final[str] = "omninode.agent.routing.completed.v1"
    FAILED: Final[str] = "omninode.agent.routing.failed.v1"

    @classmethod
    def all_topics(cls) -> list[str]:
        """
        Get all routing topics.

        Returns:
            List of all routing topic names

        Example:
            ```python
            topics = RoutingTopics.all_topics()
            # ['omninode.agent.routing.requested.v1', 'omninode.agent.routing.completed.v1', 'omninode.agent.routing.failed.v1']
            ```
        """
        return [cls.REQUEST, cls.COMPLETED, cls.FAILED]

    @classmethod
    def response_topics(cls) -> list[str]:
        """
        Get response topics (completed + failed).

        Returns:
            List of response topic names

        Example:
            ```python
            # Subscribe to all response topics
            consumer = AIOKafkaConsumer(
                *RoutingTopics.response_topics(),
                bootstrap_servers=kafka_servers
            )
            ```
        """
        return [cls.COMPLETED, cls.FAILED]


# Global instance for convenience
TOPICS = RoutingTopics()


# Event type constants (for ModelRoutingEventEnvelope)
# Uses lowercase dot notation per EVENT_BUS_INTEGRATION_GUIDE
class EventTypes:
    """
    Event type constants for routing events.

    These match the event_type field in ModelRoutingEventEnvelope.
    Format: lowercase dot notation per EVENT_BUS_INTEGRATION_GUIDE
    """

    REQUESTED: Final[str] = "omninode.agent.routing.requested.v1"
    COMPLETED: Final[str] = "omninode.agent.routing.completed.v1"
    FAILED: Final[str] = "omninode.agent.routing.failed.v1"


# Topic configuration for creation/management
TOPIC_CONFIGS = {
    TOPICS.REQUEST: {
        "num_partitions": 3,
        "replication_factor": 1,
        "config": {
            "retention.ms": "604800000",  # 7 days
            "compression.type": "gzip",
            "cleanup.policy": "delete",
        },
    },
    TOPICS.COMPLETED: {
        "num_partitions": 3,
        "replication_factor": 1,
        "config": {
            "retention.ms": "604800000",  # 7 days
            "compression.type": "gzip",
            "cleanup.policy": "delete",
        },
    },
    TOPICS.FAILED: {
        "num_partitions": 3,
        "replication_factor": 1,
        "config": {
            "retention.ms": "604800000",  # 7 days
            "compression.type": "gzip",
            "cleanup.policy": "delete",
        },
    },
}


__all__ = [
    "RoutingTopics",
    "TOPICS",
    "EventTypes",
    "TOPIC_CONFIGS",
]

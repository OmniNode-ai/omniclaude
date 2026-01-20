#!/usr/bin/env python3
"""
Partition Key Policy - Usage Examples

Demonstrates how to use the partition key policy module for omniclaude events.

Created: 2025-11-13
"""

from uuid import uuid4

try:
    from partition_key_policy import (
        EventFamily,
        get_event_family,
        get_partition_key_for_event,
        get_partition_policy,
        get_policy_summary,
        validate_partition_key,
    )
except ImportError:
    from agents.lib.partition_key_policy import (
        EventFamily,
        get_event_family,
        get_partition_key_for_event,
        get_partition_policy,
        get_policy_summary,
        validate_partition_key,
    )


def example_routing_event():
    """Example: Agent routing event with partition key extraction."""
    print("\n=== Example: Agent Routing Event ===")

    correlation_id = str(uuid4())
    event_type = "omninode.agent.routing.requested.v1"

    # Create event envelope
    envelope = {
        "event_id": str(uuid4()),
        "event_type": "AGENT_ROUTING_REQUESTED",
        "correlation_id": correlation_id,
        "timestamp": "2025-11-13T14:30:00Z",
        "service": "polymorphic-agent",
        "payload": {
            "user_request": "optimize my database queries",
            "correlation_id": correlation_id,
        },
    }

    # Extract event family
    family = get_event_family(event_type)
    print(f"Event Type: {event_type}")
    print(f"Event Family: {family}")

    # Get partition key
    partition_key = get_partition_key_for_event(event_type, envelope)
    print(f"Partition Key: {partition_key}")

    # Validate partition key
    is_valid = validate_partition_key(event_type, partition_key)
    print(f"Valid: {is_valid}")

    # Get policy
    policy = get_partition_policy(family)
    print(f"Policy: {policy}")


def example_transformation_event():
    """Example: Agent transformation event."""
    print("\n=== Example: Agent Transformation Event ===")

    correlation_id = str(uuid4())
    event_type = "agent-transformation-events"

    # Create transformation event
    event = {
        "source_agent": "polymorphic-agent",
        "target_agent": "agent-api-architect",
        "transformation_reason": "API design task detected",
        "correlation_id": correlation_id,
        "routing_confidence": 0.92,
        "transformation_duration_ms": 45,
        "timestamp": "2025-11-13T14:30:00Z",
    }

    # Extract and validate partition key
    family = get_event_family(event_type)
    partition_key = get_partition_key_for_event(event_type, event)
    is_valid = validate_partition_key(event_type, partition_key)

    print(f"Event Type: {event_type}")
    print(f"Event Family: {family}")
    print(f"Partition Key: {partition_key}")
    print(f"Valid: {is_valid}")


def example_action_event():
    """Example: Agent action event."""
    print("\n=== Example: Agent Action Event ===")

    correlation_id = str(uuid4())
    event_type = "agent-actions"

    # Create action event
    event = {
        "agent_name": "agent-researcher",
        "action_type": "tool_call",
        "action_name": "Read",
        "action_details": {
            "file_path": "/path/to/file.py",
            "line_count": 100,
        },
        "correlation_id": correlation_id,
        "duration_ms": 45,
        "timestamp": "2025-11-13T14:30:00Z",
    }

    # Extract and validate partition key
    family = get_event_family(event_type)
    partition_key = get_partition_key_for_event(event_type, event)
    is_valid = validate_partition_key(event_type, partition_key)

    print(f"Event Type: {event_type}")
    print(f"Event Family: {family}")
    print(f"Partition Key: {partition_key}")
    print(f"Valid: {is_valid}")


def example_intelligence_query():
    """Example: Intelligence query event."""
    print("\n=== Example: Intelligence Query Event ===")

    correlation_id = str(uuid4())
    event_type = "dev.archon-intelligence.intelligence.code-analysis-requested.v1"

    # Create intelligence query event
    event = {
        "correlation_id": correlation_id,
        "operation_type": "PATTERN_EXTRACTION",
        "collection_name": "archon_vectors",
        "options": {
            "limit": 50,
            "include_patterns": True,
        },
        "timeout_ms": 5000,
        "timestamp": "2025-11-13T14:30:00Z",
    }

    # Extract and validate partition key
    family = get_event_family(event_type)
    partition_key = get_partition_key_for_event(event_type, event)
    is_valid = validate_partition_key(event_type, partition_key)

    print(f"Event Type: {event_type}")
    print(f"Event Family: {family}")
    print(f"Partition Key: {partition_key}")
    print(f"Valid: {is_valid}")


def example_policy_summary():
    """Example: Display complete policy summary."""
    print("\n=== Partition Key Policy Summary ===")

    summary = get_policy_summary()

    for family_name, policy in summary.items():
        print(f"\nFamily: {family_name}")
        print(f"  Partition Key: {policy['partition_key']}")
        print(f"  Reason: {policy['reason']}")
        print(f"  Cardinality: {policy['cardinality']}")
        print(f"  Example: {policy['example']}")


def example_kafka_producer_usage():
    """Example: Using partition keys with Kafka producer."""
    print("\n=== Example: Kafka Producer Usage ===")

    correlation_id = str(uuid4())
    event_type = "agent-actions"
    topic = "agent-actions"

    # Create event
    event = {
        "agent_name": "agent-researcher",
        "action_type": "tool_call",
        "correlation_id": correlation_id,
        "timestamp": "2025-11-13T14:30:00Z",
    }

    # Get partition key
    partition_key = get_partition_key_for_event(event_type, event)

    # Validate before publishing
    if not validate_partition_key(event_type, partition_key):
        print("ERROR: Invalid partition key!")
        return

    print(f"Topic: {topic}")
    print(f"Partition Key: {partition_key}")
    print(f"Event: {event}")

    # Publish to Kafka (pseudo-code)
    # await producer.send_and_wait(
    #     topic=topic,
    #     value=event,
    #     key=partition_key.encode('utf-8')  # Kafka needs bytes
    # )

    print("✓ Ready to publish to Kafka with partition key")


def example_cross_event_ordering():
    """Example: Maintaining ordering across event families."""
    print("\n=== Example: Cross-Event Ordering ===")

    # Same correlation_id used across different event families
    correlation_id = str(uuid4())

    events = [
        ("omninode.agent.routing.requested.v1", EventFamily.AGENT_ROUTING),
        ("agent-transformation-events", EventFamily.AGENT_TRANSFORMATION),
        ("agent-actions", EventFamily.AGENT_ACTIONS),
        (
            "dev.archon-intelligence.intelligence.code-analysis-requested.v1",
            EventFamily.INTELLIGENCE_QUERY,
        ),
        ("omninode.quality.gate.evaluation.v1", EventFamily.QUALITY_GATE),
    ]

    print(f"Correlation ID: {correlation_id}")
    print("\nAll events with same correlation_id will land on same partition:")

    for event_type, expected_family in events:
        envelope = {"correlation_id": correlation_id}
        family = get_event_family(event_type)
        partition_key = get_partition_key_for_event(event_type, envelope)

        print(f"  • {event_type}")
        print(f"    Family: {family}")
        print(f"    Partition Key: {partition_key}")
        print("    ✓ Same partition guaranteed")


def main():
    """Run all examples."""
    print("=" * 80)
    print("Partition Key Policy - Usage Examples")
    print("=" * 80)

    example_routing_event()
    example_transformation_event()
    example_action_event()
    example_intelligence_query()
    example_policy_summary()
    example_kafka_producer_usage()
    example_cross_event_ordering()

    print("\n" + "=" * 80)
    print("All examples completed successfully!")
    print("=" * 80)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Partition Key Policy for OmniClaude Events

Enforces partition key policy for all omniclaude events following the EVENT_BUS_INTEGRATION_GUIDE standard.

This module ensures:
- Ordering guarantees for related events
- Proper event co-location in Kafka partitions
- Documented cardinality expectations
- Consistent partition key extraction across event families

Reference: EVENT_BUS_INTEGRATION_GUIDE.md Section "Partition Key Policy"

Event Families:
    - agent.routing: Agent routing requests/responses
    - agent.transformation: Agent transformation lifecycle
    - agent.actions: Agent tool calls, decisions, errors
    - agent.execution: Agent execution lifecycle (started, progress, completed, failed)
    - agent.provider: AI provider and model selection
    - intelligence.query: Intelligence pattern discovery
    - quality.gate: Quality validation and compliance checks

Created: 2025-11-13
Author: OmniClaude Polymorphic Agent
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, Optional, Union


logger = logging.getLogger(__name__)


class EventFamily(str, Enum):
    """
    Event family classifications for partition key policy.

    Each event family represents a logical grouping of related events
    that share ordering and co-location requirements.
    """

    AGENT_ROUTING = "agent.routing"
    AGENT_TRANSFORMATION = "agent.transformation"
    AGENT_ACTIONS = "agent.actions"
    AGENT_EXECUTION = "agent.execution"
    AGENT_PROVIDER = "agent.provider"
    INTELLIGENCE_QUERY = "intelligence.query"
    QUALITY_GATE = "quality.gate"


# Partition key policy table
# Maps event families to their partition key strategies
PARTITION_KEY_POLICY: Dict[EventFamily, Dict[str, str]] = {
    EventFamily.AGENT_ROUTING: {
        "partition_key": "correlation_id",
        "reason": "Preserve request→result ordering for routing decisions and confidence scoring",
        "cardinality": "Medium (per routing request, ~100-1000 unique keys/day)",
        "example": "omninode.agent.routing.requested.v1, omninode.agent.confidence.scored.v1 → correlation_id ensures request, confidence, and response land on same partition",
    },
    EventFamily.AGENT_TRANSFORMATION: {
        "partition_key": "correlation_id",
        "reason": "Workflow coherence - all transformation events in same workflow stay together",
        "cardinality": "Medium (per workflow execution, ~50-500 unique keys/day)",
        "example": "agent-transformation-events → correlation_id groups polymorphic→specialized→base transformations",
    },
    EventFamily.AGENT_ACTIONS: {
        "partition_key": "correlation_id",
        "reason": "Execution lifecycle ordering - tool calls, decisions, errors maintain temporal order",
        "cardinality": "Medium (per agent execution, ~200-2000 unique keys/day)",
        "example": "agent-actions → correlation_id keeps Read→Edit→Bash sequence ordered",
    },
    EventFamily.AGENT_EXECUTION: {
        "partition_key": "correlation_id",
        "reason": "Execution lifecycle ordering - started→progress→completed events maintain temporal sequence",
        "cardinality": "Medium (per agent execution, ~100-1000 unique keys/day)",
        "example": "omninode.agent.execution.started.v1 → correlation_id groups all execution lifecycle events together",
    },
    EventFamily.AGENT_PROVIDER: {
        "partition_key": "correlation_id",
        "reason": "Provider selection ordering - track provider/model choices per request",
        "cardinality": "Medium (per agent execution, ~100-1000 unique keys/day)",
        "example": "omninode.agent.provider.selected.v1 → correlation_id tracks provider choice for each request",
    },
    EventFamily.INTELLIGENCE_QUERY: {
        "partition_key": "correlation_id",
        "reason": "Query request→response ordering for pattern discovery and manifest injection",
        "cardinality": "Medium (per intelligence query, ~50-500 unique keys/day)",
        "example": "dev.archon-intelligence.intelligence.code-analysis-requested.v1 → correlation_id pairs requests with results",
    },
    EventFamily.QUALITY_GATE: {
        "partition_key": "correlation_id",
        "reason": "Gate evaluation ordering - sequential quality checks maintain evaluation order",
        "cardinality": "Low (per quality evaluation, ~10-100 unique keys/day)",
        "example": "quality.gate.evaluation.v1 → correlation_id groups all gates in same validation session",
    },
}


def get_event_family(event_type: str) -> Optional[EventFamily]:
    """
    Extract event family from event type string.

    Event type formats:
    - Full qualified: "omninode.agent.routing.requested.v1"
    - Short form: "agent.routing.requested.v1"
    - Topic name: "agent-transformation-events"

    Args:
        event_type: Full event type or topic name

    Returns:
        EventFamily enum or None if not recognized

    Examples:
        >>> get_event_family("omninode.agent.routing.requested.v1")
        EventFamily.AGENT_ROUTING

        >>> get_event_family("agent-transformation-events")
        EventFamily.AGENT_TRANSFORMATION

        >>> get_event_family("dev.archon-intelligence.intelligence.code-analysis-requested.v1")
        EventFamily.INTELLIGENCE_QUERY
    """
    if not event_type:
        return None

    # Normalize event type
    event_type_lower = event_type.lower()

    # Map topic names to event families
    topic_mapping = {
        "agent-transformation-events": EventFamily.AGENT_TRANSFORMATION,
        "agent-actions": EventFamily.AGENT_ACTIONS,
    }

    # Check direct topic match
    if event_type_lower in topic_mapping:
        return topic_mapping[event_type_lower]

    # Parse hierarchical event type (e.g., "omninode.agent.routing.requested.v1")
    parts = event_type.split(".")

    # Extract family from hierarchical format
    if len(parts) >= 3:
        # Handle formats like "omninode.agent.routing.requested.v1"
        if parts[1] == "agent" and parts[2] == "routing":
            return EventFamily.AGENT_ROUTING
        elif parts[1] == "agent" and parts[2] == "confidence":
            return (
                EventFamily.AGENT_ROUTING
            )  # Confidence events are part of routing domain
        elif parts[1] == "agent" and parts[2] == "transformation":
            return EventFamily.AGENT_TRANSFORMATION
        elif parts[1] == "agent" and parts[2] == "actions":
            return EventFamily.AGENT_ACTIONS
        elif parts[1] == "agent" and parts[2] == "execution":
            return EventFamily.AGENT_EXECUTION
        elif parts[1] == "agent" and parts[2] == "provider":
            return EventFamily.AGENT_PROVIDER

        # Handle intelligence query formats
        if "intelligence" in event_type_lower:
            return EventFamily.INTELLIGENCE_QUERY

        # Handle quality gate formats
        if "quality" in event_type_lower and "gate" in event_type_lower:
            return EventFamily.QUALITY_GATE

    # Fallback: check if any family keyword appears in event type
    if "routing" in event_type_lower:
        return EventFamily.AGENT_ROUTING
    elif "transformation" in event_type_lower:
        return EventFamily.AGENT_TRANSFORMATION
    elif "action" in event_type_lower:
        return EventFamily.AGENT_ACTIONS
    elif "execution" in event_type_lower:
        return EventFamily.AGENT_EXECUTION
    elif "provider" in event_type_lower:
        return EventFamily.AGENT_PROVIDER
    elif "intelligence" in event_type_lower or "code-analysis" in event_type_lower:
        return EventFamily.INTELLIGENCE_QUERY
    elif "quality" in event_type_lower:
        return EventFamily.QUALITY_GATE

    logger.warning(f"Unrecognized event type for family extraction: {event_type}")
    return None


def get_partition_key_for_event(
    event_type: str,
    envelope: Union[Dict[str, Any], Any],
) -> Optional[str]:
    """
    Get partition key for event based on policy.

    Extracts the appropriate partition key from event envelope according
    to the partition key policy for the event's family.

    Args:
        event_type: Full event type or topic name (e.g., "omninode.agent.routing.requested.v1")
        envelope: Event envelope (dict or Pydantic model) with payload and metadata

    Returns:
        Partition key value (correlation_id as string) or None if policy not found

    Examples:
        >>> envelope = {"correlation_id": "abc-123", "payload": {...}}
        >>> get_partition_key_for_event("agent-actions", envelope)
        "abc-123"

        >>> envelope = ModelRoutingEventEnvelope(correlation_id="def-456", ...)
        >>> get_partition_key_for_event("omninode.agent.routing.requested.v1", envelope)
        "def-456"
    """
    # Extract event family from event_type
    family = get_event_family(event_type)

    if family is None:
        logger.warning(f"Could not determine event family for: {event_type}")
        return None

    # Get partition key policy
    policy = PARTITION_KEY_POLICY.get(family)
    if not policy:
        logger.warning(f"No partition key policy found for family: {family}")
        return None

    partition_field = policy["partition_key"]

    # Extract partition key from envelope
    # Support both dict and object access patterns
    partition_key = None

    if isinstance(envelope, dict):
        # Dict access
        partition_key = envelope.get(partition_field)

        # Fallback: check in payload if not at top level
        if partition_key is None and "payload" in envelope:
            payload = envelope["payload"]
            if isinstance(payload, dict):
                partition_key = payload.get(partition_field)
    else:
        # Object access (Pydantic model or similar)
        partition_key = getattr(envelope, partition_field, None)

        # Fallback: check in payload if not at top level
        if partition_key is None and hasattr(envelope, "payload"):
            payload = envelope.payload
            if isinstance(payload, dict):
                partition_key = payload.get(partition_field)
            else:
                partition_key = getattr(payload, partition_field, None)

    # Convert to string if found
    if partition_key is not None:
        return str(partition_key)

    logger.warning(
        f"Could not extract partition key '{partition_field}' from envelope for event type: {event_type}"
    )
    return None


def get_partition_policy(event_family: EventFamily) -> Dict[str, str]:
    """
    Get partition policy details for an event family.

    Args:
        event_family: EventFamily enum value

    Returns:
        Dict with partition_key, reason, cardinality, example

    Example:
        >>> policy = get_partition_policy(EventFamily.AGENT_ROUTING)
        >>> print(policy["reason"])
        "Preserve request→result ordering for routing decisions"
    """
    return PARTITION_KEY_POLICY.get(event_family, {})


def validate_partition_key(
    event_type: str,
    partition_key: Optional[str],
) -> bool:
    """
    Validate that partition key is valid and follows policy.

    Checks:
    - Partition key is not None or empty
    - Event type has a recognized family
    - Partition key appears to be a valid UUID or correlation ID

    Args:
        event_type: Event type or topic name
        partition_key: Extracted partition key value

    Returns:
        True if valid, False otherwise

    Examples:
        >>> validate_partition_key("agent-actions", "abc-123-def-456")
        True

        >>> validate_partition_key("agent-actions", None)
        False

        >>> validate_partition_key("unknown-event-type", "abc-123")
        False
    """
    # Check partition key is not empty
    if not partition_key:
        logger.warning(f"Partition key is None or empty for event type: {event_type}")
        return False

    # Check event type has a recognized family
    family = get_event_family(event_type)
    if family is None:
        logger.warning(
            f"Cannot validate partition key for unrecognized event type: {event_type}"
        )
        return False

    # Check policy exists for family
    policy = PARTITION_KEY_POLICY.get(family)
    if not policy:
        logger.warning(f"No partition key policy for family: {family}")
        return False

    # Basic validation: partition key should be a non-empty string
    # Note: At this point partition_key is already known to be truthy from check above

    if len(partition_key.strip()) == 0:
        logger.warning(f"Partition key is empty string for event type: {event_type}")
        return False

    # Validation passed
    return True


def get_all_event_families() -> list[EventFamily]:
    """
    Get all defined event families.

    Returns:
        List of all EventFamily enum values
    """
    return list(EventFamily)


def get_policy_summary() -> Dict[str, Dict[str, str]]:
    """
    Get complete partition key policy summary.

    Returns:
        Dict mapping event family names to their policies

    Example:
        >>> summary = get_policy_summary()
        >>> for family, policy in summary.items():
        ...     print(f"{family}: {policy['partition_key']} - {policy['reason']}")
    """
    return {family.value: policy for family, policy in PARTITION_KEY_POLICY.items()}


# Module-level constants for convenience
DEFAULT_PARTITION_KEY_FIELD = "correlation_id"
VALID_EVENT_FAMILIES = [family.value for family in EventFamily]


__all__ = [
    "DEFAULT_PARTITION_KEY_FIELD",
    "PARTITION_KEY_POLICY",
    "VALID_EVENT_FAMILIES",
    "EventFamily",
    "get_all_event_families",
    "get_event_family",
    "get_partition_key_for_event",
    "get_partition_policy",
    "get_policy_summary",
    "validate_partition_key",
]

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Shared Kafka Producer Utilities

Shared utility functions used by transformation_event_publisher.py and
manifest_injection_event_publisher.py. Eliminates duplication of Kafka
configuration and envelope creation.

DESIGN RULE: Non-Blocking Event Emission
-----------------------------------------
Event emission is BEST-EFFORT, NEVER blocks execution.
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from omniclaude.hooks.topics import build_topic

logger = logging.getLogger(__name__)

# Kafka publish timeout (10 seconds)
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0


def get_kafka_bootstrap_servers() -> str | None:
    """
    Get Kafka bootstrap servers from environment.

    Per CLAUDE.md: No localhost defaults - explicit configuration required.

    Returns:
        Bootstrap servers string, or None if not configured.
    """
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        logger.warning(
            "KAFKA_BOOTSTRAP_SERVERS not set. Kafka publishing disabled. "
            "Set KAFKA_BOOTSTRAP_SERVERS environment variable to enable event publishing."
        )
        return None
    return servers


def create_event_envelope(
    event_type_value: str,
    event_type_name: str,
    payload: dict[str, Any],
    correlation_id: str,
    schema_domain: str,
    source: str = "omniclaude",
    tenant_id: str = "default",
    namespace: str = "onex",
    causation_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """
    Create OnexEnvelopeV1 standard event envelope.

    Args:
        event_type_value: Event type string value (e.g., from enum.value for Kafka topic)
        event_type_name: Event type name for schema_ref (e.g., "started", "completed", "failed")
        payload: Event payload data
        correlation_id: Correlation ID for distributed tracing
        schema_domain: Domain for schema_ref (e.g., "transformation", "manifest-injection")
        source: Source service name (default: omniclaude)
        tenant_id: Tenant identifier (default: default)
        namespace: Event namespace (default: onex)
        causation_id: Optional causation ID for event chains
        timestamp: Explicit timestamp (ISO 8601). If None, uses datetime.now(UTC).

    Returns:
        Dict containing OnexEnvelopeV1 wrapped event
    """
    return {
        "event_type": event_type_value,
        "event_id": str(uuid4()),
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "tenant_id": tenant_id,
        "namespace": namespace,
        "source": source,
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "schema_ref": f"registry://{namespace}/{schema_domain}/{event_type_name}/v1",
        "payload": payload,
    }


def build_kafka_topic(topic_base_value: str) -> str:
    """Build Kafka topic name from TopicBase value.

    Topics are realm-agnostic per OMN-1972: TopicBase values ARE the wire
    topic names. No environment prefix is applied.

    Args:
        topic_base_value: Base topic name from TopicBase enum

    Returns:
        Validated canonical topic name
    """
    return build_topic(topic_base_value)

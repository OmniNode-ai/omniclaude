# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""EventBus factory for lib/core clients.

Authorised bootstrap factory for EventBusKafka construction in lib/core.
Callers receive a pre-constructed instance; construction is isolated here
so the AST validator (OMN-10725) has a single auditable surface.
"""

from __future__ import annotations

from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka
from omnibase_infra.event_bus.models.config import ModelKafkaEventBusConfig


def create_kafka_event_bus(config: ModelKafkaEventBusConfig) -> EventBusKafka:
    """Construct an EventBusKafka from the given config."""
    return EventBusKafka(config)


__all__: list[str] = ["create_kafka_event_bus"]

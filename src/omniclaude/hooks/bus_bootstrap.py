# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""EventBus factory for hooks emit path.

Authorised bootstrap factory for EventBusKafka construction used by
hook emitter functions. Construction is isolated here so the AST
validator (OMN-10725) has a single auditable surface.
"""

from omnibase_infra.event_bus.event_bus_kafka import EventBusKafka  # noqa: TC002
from omnibase_infra.event_bus.models.config import (
    ModelKafkaEventBusConfig,  # noqa: TC002
)


def create_kafka_event_bus(config: ModelKafkaEventBusConfig) -> EventBusKafka:
    """Construct an EventBusKafka from the given config."""
    return EventBusKafka(config)


__all__: list[str] = ["create_kafka_event_bus"]

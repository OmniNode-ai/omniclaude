# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for routing decision emission backends.

Operation Mapping (from node contract io_operations):
    - emit_routing_decision operation -> ProtocolRoutingEmitter.emit_routing_decision()

Implementors must:
    1. Provide handler_key property identifying the backend (e.g., 'kafka')
    2. Implement emit_routing_decision for emitting routing decision events

Emission Semantics:
    - Events are emitted to configured Kafka topics (dual-emission pattern)
    - Preview-safe data goes to onex.evt.* topics (broad access)
    - Full routing data goes to onex.cmd.omniintelligence.* topics (restricted)
    - Emission is NOT idempotent: each call produces a new event
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionRequest,
    ModelEmissionResult,
)


@runtime_checkable
class ProtocolRoutingEmitter(Protocol):
    """Protocol for routing decision emission backends.

    This protocol defines the interface for emission backends that publish
    routing decision events. Implementations are responsible for:

    - Emitting routing decisions to configured event topics
    - Following the dual-emission pattern (preview + full data)
    - Returning emission status with topic confirmation

    Attributes:
        handler_key: Backend identifier used for routing (e.g., 'kafka')

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolRoutingEmitter)
        result = await handler.emit_routing_decision(request, correlation_id=cid)
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'kafka', 'memory', 'noop').

        This key is used for handler routing when multiple backends are
        registered. The node contract's handler_routing.backends configuration
        maps backend keys to handler implementations.
        """
        ...

    async def emit_routing_decision(
        self,
        request: ModelEmissionRequest,
        correlation_id: UUID | None = None,
    ) -> ModelEmissionResult:
        """Emit a routing decision event to configured topics.

        This operation emits routing decision data to one or more event topics.
        The implementation should follow the dual-emission pattern:
            1. Emit preview-safe data to onex.evt.* topics (broad access)
            2. Emit full routing data to onex.cmd.omniintelligence.* topics (restricted)

        Args:
            request: The emission request containing routing decision data
                     including selected agent, confidence, routing policy,
                     and sanitized prompt preview.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelEmissionResult with:
                - success: True if emission executed successfully
                - correlation_id: The correlation ID used for this request
                - topics_emitted: Tuple of topic names that received events
                - error: Error message if success is False
                - duration_ms: Emission execution time
        """
        ...

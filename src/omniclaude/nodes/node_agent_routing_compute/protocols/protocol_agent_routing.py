# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for agent routing compute backends.

Operation Mapping (from node contract io_operations):
    - compute_routing operation -> ProtocolAgentRouting.compute_routing()

Implementors must:
    1. Evaluate the user prompt against all agents in the registry
    2. Score each agent with a confidence breakdown
    3. Return the best-matching agent with full candidate list

Routing Policy:
    The result must indicate how the agent was selected:
    - trigger_match: Matched via activation patterns
    - explicit_request: User explicitly requested an agent
    - fallback_default: No match found, using fallback agent
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelRoutingRequest,
    ModelRoutingResult,
)


@runtime_checkable
class ProtocolAgentRouting(Protocol):
    """Protocol for agent routing compute backends.

    This protocol defines the interface for compute backends that evaluate
    user prompts against agent registries to produce routing decisions.
    Implementations are responsible for:

    - Scoring agents against the user prompt
    - Producing confidence breakdowns for each candidate
    - Selecting the best-matching agent or falling back to default
    - Respecting the confidence threshold from the request

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolAgentRouting)
        result = await handler.compute_routing(request, correlation_id=cid)
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'default', 'weighted', 'llm').

        This key is used for handler routing when multiple backends are
        registered. The node contract's handler_routing.backends configuration
        maps backend keys to handler implementations.
        """
        ...

    async def compute_routing(
        self,
        request: ModelRoutingRequest,
        correlation_id: UUID | None = None,
    ) -> ModelRoutingResult:
        """Compute a routing decision for a user prompt.

        Evaluates the prompt from the request against all agents in the
        agent_registry, scoring each candidate and selecting the best match.

        Args:
            request: Routing request containing the user prompt, agent
                     registry, optional historical stats, and confidence
                     threshold.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelRoutingResult with:
                - selected_agent: Name of the selected agent
                - confidence: Overall confidence of the selection (0.0-1.0)
                - confidence_breakdown: Detailed score breakdown
                - routing_policy: How the agent was selected
                - routing_path: Infrastructure path used for routing
                - candidates: All evaluated candidates, sorted by confidence
                - fallback_reason: Reason if fallback agent was selected
        """
        ...

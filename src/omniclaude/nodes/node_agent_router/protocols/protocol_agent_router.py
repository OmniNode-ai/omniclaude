# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Protocol for agent router compute backends.

Operation Mapping (from node contract io_operations):
    - route operation -> ProtocolAgentRouter.route()

Implementors must:
    1. Accept a user request string and optional context
    2. Return a ranked list of agent recommendations
    3. Degrade gracefully — return empty result, never raise

Design note:
    This protocol wraps the AgentRouter.route() interface, making it
    pluggable for testing and future backend replacement.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from omniclaude.nodes.node_agent_router.models import (
    ModelAgentRouterRequest,
    ModelAgentRouterResult,
)


@runtime_checkable
class ProtocolAgentRouter(Protocol):
    """Protocol for agent router compute backends.

    Implementors evaluate user prompts against agent registries and
    return ranked recommendations with confidence scores.

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolAgentRouter)
        result = await handler.route(request, correlation_id=cid)
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'default').

        Used for handler routing when multiple backends are registered.
        The node contract's handler_routing.backends configuration maps
        backend keys to handler implementations.
        """
        raise NotImplementedError

    async def route(
        self,
        request: ModelAgentRouterRequest,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRouterResult:
        """Route a user prompt to the best-matching agent(s).

        Args:
            request: Routing request with user text, context, and limits.
            correlation_id: Optional correlation ID for request tracing.

        Returns:
            ModelAgentRouterResult with ranked recommendations and routed flag.
            Returns empty result (routed=False) on failure — never raises.
        """
        raise NotImplementedError

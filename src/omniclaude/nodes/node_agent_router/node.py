# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeAgentRouter - 100% contract-driven.

The NodeAgentRouter class, a minimal shell that inherits from NodeCompute.
All compute logic is driven by the contract.yaml.

Capability: agent.router

The node exposes one operation:
- route: Route a user prompt to best-matching agent(s) via AgentRouter

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolAgentRouter). The actual routing backend wraps AgentRouter from
lib/core/agent_router.py.

Ticket: OMN-11599
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any  # any-ok: contract-driven node shell

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeAgentRouter(
    NodeCompute[Any, Any]
):  # Why: transitional wrapper — migrating to omnimarket
    """Compute node for agent routing decisions.

    Capability: agent.router

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    Wraps AgentRouter from lib/core/agent_router.py for contract-compliant
    access during the omniclaude restructuring program.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the agent router compute node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeAgentRouter"]

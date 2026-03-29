# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillAgentHealthcheckOrchestrator — thin orchestrator shell for the agent_healthcheck skill.

Capability: skill.agent_healthcheck
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillAgentHealthcheckOrchestrator(NodeOrchestrator):
    """Orchestrator node for the agent_healthcheck skill.

    Capability: skill.agent_healthcheck

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillAgentHealthcheckOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillAgentHealthcheckOrchestrator"]

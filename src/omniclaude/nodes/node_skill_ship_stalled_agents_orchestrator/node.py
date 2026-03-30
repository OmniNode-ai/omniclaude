# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillShipStalledAgentsOrchestrator — thin orchestrator shell for the ship_stalled_agents skill.

Capability: skill.ship_stalled_agents
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillShipStalledAgentsOrchestrator(NodeOrchestrator):
    """Orchestrator node for the ship_stalled_agents skill.

    Capability: skill.ship_stalled_agents

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillShipStalledAgentsOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillShipStalledAgentsOrchestrator"]

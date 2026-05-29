# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillShipDirtyCanonicalOrchestrator — thin orchestrator shell for the ship_dirty_canonical skill.

Capability: skill.ship_dirty_canonical
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillShipDirtyCanonicalOrchestrator(NodeOrchestrator):
    """Orchestrator node for the ship_dirty_canonical skill.

    Capability: skill.ship_dirty_canonical

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillShipDirtyCanonicalOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillShipDirtyCanonicalOrchestrator"]

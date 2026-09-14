# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillPlansBoardRefreshOrchestrator — thin orchestrator shell for the plans_board_refresh skill.

Capability: skill.plans_board_refresh
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillPlansBoardRefreshOrchestrator(NodeOrchestrator):
    """Orchestrator node for the plans_board_refresh skill.

    Capability: skill.plans_board_refresh

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillPlansBoardRefreshOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillPlansBoardRefreshOrchestrator"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillSelfHealingDispatchOrchestrator — thin orchestrator shell for the self_healing_dispatch skill.

Capability: skill.self_healing_dispatch
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillSelfHealingDispatchOrchestrator(NodeOrchestrator):
    """Orchestrator node for the self_healing_dispatch skill.

    Capability: skill.self_healing_dispatch

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillSelfHealingDispatchOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillSelfHealingDispatchOrchestrator"]

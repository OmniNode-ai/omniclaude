# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillDelegateOrchestrator — thin orchestrator shell for the delegate skill.

Capability: skill.delegate
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillDelegateOrchestrator(NodeOrchestrator):
    """Orchestrator node for the delegate skill.

    Capability: skill.delegate

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillDelegateOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillDelegateOrchestrator"]

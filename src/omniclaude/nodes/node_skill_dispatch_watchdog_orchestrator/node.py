# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillDispatchWatchdogOrchestrator — thin orchestrator shell for the dispatch_watchdog skill.

Capability: skill.dispatch_watchdog
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillDispatchWatchdogOrchestrator(NodeOrchestrator):
    """Orchestrator node for the dispatch_watchdog skill.

    Capability: skill.dispatch_watchdog

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillDispatchWatchdogOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillDispatchWatchdogOrchestrator"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillDemoReadinessTeamOrchestrator — thin orchestrator shell for the demo_readiness_team skill.

Capability: skill.demo_readiness_team
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillDemoReadinessTeamOrchestrator(NodeOrchestrator):
    """Orchestrator node for the demo_readiness_team skill.

    Capability: skill.demo_readiness_team

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillDemoReadinessTeamOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillDemoReadinessTeamOrchestrator"]

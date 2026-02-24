# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeSkillSubagentDrivenDevelopmentOrchestrator — thin orchestrator shell for the subagent-driven-development skill.

Capability: skill.subagent_driven_development
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillSubagentDrivenDevelopmentOrchestrator(NodeOrchestrator):
    """Orchestrator node for the subagent-driven-development skill.

    Capability: skill.subagent_driven_development

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillSubagentDrivenDevelopmentOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillSubagentDrivenDevelopmentOrchestrator"]

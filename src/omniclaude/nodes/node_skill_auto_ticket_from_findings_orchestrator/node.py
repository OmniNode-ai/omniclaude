# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillAutoTicketFromFindingsOrchestrator — thin orchestrator shell for the auto_ticket_from_findings skill.

Capability: skill.auto_ticket_from_findings
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillAutoTicketFromFindingsOrchestrator(NodeOrchestrator):
    """Orchestrator node for the auto_ticket_from_findings skill.

    Capability: skill.auto_ticket_from_findings

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillAutoTicketFromFindingsOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillAutoTicketFromFindingsOrchestrator"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillSessionOrchestrator — thin orchestrator shell for the session skill.

Capability: skill.session
All dispatch logic lives in the shared handle_skill_requested handler.

NOTE: This is a pre-commit hook generated stub. The full backing node
(node_session_orchestrator) lives in omnimarket/ and is implemented in OMN-8340
per docs/plans/2026-04-11-unified-session-orchestrator-plan.md Wave 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillSessionOrchestrator(NodeOrchestrator):
    """Orchestrator node for the session skill.

    Capability: skill.session

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillSessionOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillSessionOrchestrator"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillWorktreeOrchestrator — thin orchestrator shell for the worktree skill.

Capability: skill.worktree
All dispatch logic lives in the shared handle_skill_requested handler.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillWorktreeOrchestrator(NodeOrchestrator):
    """Orchestrator node for the unified worktree skill.

    Capability: skill.worktree

    Consolidates worktree_sweep, worktree_triage, and worktree_lifecycle into
    a single skill with --audit, --triage, --prune, and --cron mode arguments.
    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillWorktreeOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillWorktreeOrchestrator"]

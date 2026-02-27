# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeSkillEpicTeamOrchestrator — thin orchestrator shell for the epic-team skill.

Capability: skill.epic_team
All dispatch logic lives in the shared handle_skill_requested handler.

Wave 2 Observability (OMN-2922):
    Callers of this node (polymorphic agent running the epic-team skill) are
    responsible for emitting epic.run.updated events at each phase transition
    and at terminal outcomes (completed, failed, partial, cancelled) by calling:

        from plugins.onex.hooks.lib.pipeline_event_emitters import emit_epic_run_updated

        emit_epic_run_updated(
            run_id=run_id,
            epic_id=epic_id,
            status="completed",          # or "failed" / "partial" / "cancelled"
            tickets_total=total,
            tickets_completed=done,
            tickets_failed=failed,
            phase=current_phase,         # optional
            correlation_id=correlation_id,
            session_id=session_id,
        )

    Topic: onex.evt.omniclaude.epic-run-updated.v1
    Consumed by: omnidash /epic-pipeline view (state table, upsert by run_id).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillEpicTeamOrchestrator(NodeOrchestrator):
    """Orchestrator node for the epic-team skill.

    Capability: skill.epic_team

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.

    Emits epic.run.updated (EPIC_RUN_UPDATED) at terminal outcomes via
    plugins.onex.hooks.lib.pipeline_event_emitters.emit_epic_run_updated
    (OMN-2922). See module docstring for emit contract.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillEpicTeamOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillEpicTeamOrchestrator"]

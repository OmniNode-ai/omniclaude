# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeSkillPrWatchOrchestrator — thin orchestrator shell for the pr-watch skill.

Capability: skill.pr_watch
All dispatch logic lives in the shared handle_skill_requested handler.

Wave 2 Observability (OMN-2922):
    Callers of this node (polymorphic agent running the pr-watch skill) are
    responsible for emitting pr.watch.updated events at each terminal outcome
    (approved, capped, timeout, failed) by calling:

        from plugins.onex.hooks.lib.pipeline_event_emitters import emit_pr_watch_updated

        emit_pr_watch_updated(
            run_id=run_id,
            pr_number=pr_number,
            repo=repo,                   # e.g. "OmniNode-ai/omniclaude"
            ticket_id=ticket_id,         # e.g. "OMN-2922"
            status="approved",           # or "capped" / "timeout" / "failed"
            review_cycles_used=cycles,
            watch_duration_hours=hours,
            correlation_id=correlation_id,
            session_id=session_id,
        )

    Topic: onex.evt.omniclaude.pr-watch-updated.v1
    Consumed by: omnidash /pr-watch view (state table, upsert by run_id).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillPrWatchOrchestrator(NodeOrchestrator):
    """Orchestrator node for the pr-watch skill.

    Capability: skill.pr_watch

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.

    Emits pr.watch.updated (PR_WATCH_UPDATED) at terminal outcomes via
    plugins.onex.hooks.lib.pipeline_event_emitters.emit_pr_watch_updated
    (OMN-2922). See module docstring for emit contract.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillPrWatchOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeSkillPrWatchOrchestrator"]

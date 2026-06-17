# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeSkillTicketingTriageOrchestrator — thin orchestrator shell for the ticketing-triage skill.

Capabilities:
    * ``skill.ticketing_triage`` — dispatch logic lives in the shared
      ``handle_skill_requested`` handler.
    * ``epic.autostart_ratchet`` (OMN-13039) — monotone epic auto-start
      reconciliation. The pure compute lives in :mod:`epic_reconcile`; this node
      exposes it so each triage tick promotes unstarted epics with started/
      completed children to In Progress (never auto-Done).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

from omniclaude.nodes.node_skill_ticketing_triage_orchestrator.epic_reconcile import (
    ModelEpicReconciliation,
    ModelEpicSnapshot,
    reconcile_epic_states,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeSkillTicketingTriageOrchestrator(NodeOrchestrator):
    """Orchestrator node for the ticketing-triage skill.

    Capabilities: ``skill.ticketing_triage``, ``epic.autostart_ratchet``.

    All behavior defined in contract.yaml.
    Dispatches to the shared handle_skill_requested handler via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the NodeSkillTicketingTriageOrchestrator.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)

    @staticmethod
    def reconcile_epic_states(
        snapshots: Iterable[ModelEpicSnapshot],
    ) -> ModelEpicReconciliation:
        """Compute the monotone epic auto-start transitions for this triage tick.

        Capability ``epic.autostart_ratchet`` (OMN-13039, retro B-10). Delegates to
        the pure :func:`epic_reconcile.reconcile_epic_states` compute — no I/O. The
        orchestrator applies the returned transitions via the project tracker.

        Args:
            snapshots: Per-epic snapshots (epic status + child status types).

        Returns:
            The In-Progress transitions to apply; empty when no epic is eligible.
        """
        return reconcile_epic_states(snapshots)


__all__ = ["NodeSkillTicketingTriageOrchestrator"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the runtime's handlers (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.handlers.handler_contract_endpoint_resolver import (
        HandlerContractEndpointResolver,
    )
    from omniclaude.nodes.node_skill_comment_sweep_orchestrator.handler_comment_sweep_skill import (
        EventEmitter,
        HandlerCommentSweepSkill,
        TaskDispatcher,
    )


def build_contract_endpoint_resolver() -> HandlerContractEndpointResolver:
    """Build the endpoint resolver with its constructor defaults.

    The handler is imported on use, so a caller that guards the build sees an
    import or construction failure at the build, as it did before.
    """
    from omniclaude.handlers.handler_contract_endpoint_resolver import (
        HandlerContractEndpointResolver,
    )

    return HandlerContractEndpointResolver()


def build_comment_sweep_skill(
    *,
    task_dispatcher: TaskDispatcher | None,
    event_emitter: EventEmitter | None,
) -> HandlerCommentSweepSkill:
    """Build the comment-sweep skill handler over the caller's dispatcher and emitter."""
    from omniclaude.nodes.node_skill_comment_sweep_orchestrator.handler_comment_sweep_skill import (
        HandlerCommentSweepSkill,
    )

    return HandlerCommentSweepSkill(
        task_dispatcher=task_dispatcher, event_emitter=event_emitter
    )

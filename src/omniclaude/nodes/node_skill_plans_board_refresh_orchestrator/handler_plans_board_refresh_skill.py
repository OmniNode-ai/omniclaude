# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Canonical handler for the plans_board_refresh skill orchestrator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from omniclaude.shared.handler_skill_requested import handle_skill_requested
from omniclaude.shared.models import ModelSkillRequest, ModelSkillResult

TaskDispatcher = Callable[[str], Awaitable[str]]
EventEmitter = Callable[[str, dict[str, object]], bool]


class HandlerPlansBoardRefreshSkill:
    """Adapter that keeps plans_board_refresh on the shared skill dispatch path."""

    handler_key: str = "default"

    def __init__(
        self,
        task_dispatcher: TaskDispatcher | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self._task_dispatcher = task_dispatcher
        self._event_emitter = event_emitter

    async def handle(self, request: ModelSkillRequest) -> ModelSkillResult:
        """Dispatch the skill request through the shared skill handler."""
        if self._task_dispatcher is None:
            raise RuntimeError("task_dispatcher is required for plans_board_refresh")
        return await handle_skill_requested(
            request,
            task_dispatcher=self._task_dispatcher,
            event_emitter=self._event_emitter,
        )


__all__ = ["HandlerPlansBoardRefreshSkill"]

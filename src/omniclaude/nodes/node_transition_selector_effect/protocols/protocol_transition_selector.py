# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for transition selector backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_request import (
    ModelTransitionSelectorRequest,
)
from omniclaude.nodes.node_transition_selector_effect.models.model_transition_selector_result import (
    ModelTransitionSelectorResult,
)


@runtime_checkable
class ProtocolTransitionSelector(Protocol):
    """Runtime-checkable protocol for transition selector backends.

    Implementors call the local model to classify over a bounded action set.
    All methods must be async. The default implementation uses Qwen3-14B
    at LLM_CODER_FAST_URL (192.168.86.201:8001).

    Operation mapping (from node contract io_operations):
        - select operation -> select()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'qwen3_fast')."""
        ...

    async def select(
        self,
        request: ModelTransitionSelectorRequest,
    ) -> ModelTransitionSelectorResult:
        """Select a typed action from the bounded action set.

        Args:
            request: Full selection request including current_state, goal,
                action_set, and navigation context.

        Returns:
            ModelTransitionSelectorResult with selected_action populated on
            success, or error_kind populated on failure. Never raises.
        """
        ...


__all__ = ["ProtocolTransitionSelector"]

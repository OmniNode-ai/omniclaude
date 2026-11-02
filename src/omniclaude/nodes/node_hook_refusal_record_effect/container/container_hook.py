# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds this node's handlers (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnimarket.nodes.node_hook_refusal_row_compute.handlers.handler_hook_refusal_row import (
        HandlerHookRefusalRowCompute,
    )

    from omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record import (
        HandlerHookRefusalRecord,
    )


def build_row_compute() -> HandlerHookRefusalRowCompute:
    """Build the refusal-row compute handler with its constructor defaults."""
    from omnimarket.nodes.node_hook_refusal_row_compute.handlers.handler_hook_refusal_row import (
        HandlerHookRefusalRowCompute,
    )

    return HandlerHookRefusalRowCompute()


def build_record() -> HandlerHookRefusalRecord:
    """Build the refusal record handler with its constructor defaults."""
    # The handler module imports this one, so it is imported on use.
    from omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record import (
        HandlerHookRefusalRecord,
    )

    return HandlerHookRefusalRecord()

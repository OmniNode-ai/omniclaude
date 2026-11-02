# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the event emit handler (OMN-21779)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
        HandlerEventEmitEffect,
    )


__all__ = ["build_event_emit"]


def build_event_emit() -> HandlerEventEmitEffect:
    """Build the emit handler with its constructor defaults.

    The handler is imported on use, so a caller that guards the build with
    ``except ImportError`` sees an absent omnimarket as it did before.
    """
    from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
        HandlerEventEmitEffect,
    )

    return HandlerEventEmitEffect()

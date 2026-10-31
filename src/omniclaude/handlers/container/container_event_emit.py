# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one place that builds the event emit handler (OMN-21779)."""

from omnimarket.nodes.node_event_emit_effect.handlers.handler_event_emit_effect import (
    HandlerEventEmitEffect,
)


def build_event_emit() -> HandlerEventEmitEffect:
    """Build the emit handler with its constructor defaults."""
    return HandlerEventEmitEffect()

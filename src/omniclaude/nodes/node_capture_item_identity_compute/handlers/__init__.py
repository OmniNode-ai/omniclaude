# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Handlers for node_capture_item_identity_compute.

The hooks load ``handler_item_identity`` by file path, not through this package
(whose import would run the whole omniclaude package); see its docstring.
"""

from omniclaude.nodes.node_capture_item_identity_compute.handlers.handler_item_identity import (
    HandlerCaptureItemIdentity,
)

__all__ = ["HandlerCaptureItemIdentity"]

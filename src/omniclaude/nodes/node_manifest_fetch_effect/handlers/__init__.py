# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Handlers for the NodeManifestFetchEffect node.

This package contains the HTTP handler implementation that satisfies
ProtocolManifestFetch.

Exported:
    HandlerManifestFetch: HTTP-based manifest fetch handler.
"""

from .handler_manifest_fetch import HandlerManifestFetch

__all__ = [
    "HandlerManifestFetch",
]

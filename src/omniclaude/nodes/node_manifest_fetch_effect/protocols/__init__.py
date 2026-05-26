# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Protocols for the NodeManifestFetchEffect node.

This package defines the protocol interface for manifest fetch backends.

Exported:
    ProtocolManifestFetch: Runtime-checkable protocol for fetch backends

Operation Mapping (from node contract io_operations):
    - fetch operation -> ProtocolManifestFetch.fetch()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Return ModelManifestFetchResult envelopes for all operations
"""

from .protocol_manifest_fetch import ProtocolManifestFetch

__all__ = [
    "ProtocolManifestFetch",
]

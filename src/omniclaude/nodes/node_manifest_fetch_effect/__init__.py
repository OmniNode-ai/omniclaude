# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeManifestFetchEffect - Contract-driven effect node for ONEX runtime manifest fetching.

This package provides the NodeManifestFetchEffect node for fetching the
structured system manifest from the ONEX runtime /v1/introspection/manifest
endpoint.

Capability: manifest.fetch

Exported Components:
    Node:
        NodeManifestFetchEffect - The effect node class (minimal shell)

    Models:
        ModelManifestFetchRequest - Input model for fetch requests
        ModelManifestFetchResult - Output model for fetch results
        EnumManifestFetchStatus - Status enum for fetch outcomes

    Protocols:
        ProtocolManifestFetch - Interface for fetch backends

    Handlers:
        HandlerManifestFetch - HTTP-based fetch handler

Example Usage:
    ```python
    from omniclaude.nodes.node_manifest_fetch_effect import (
        HandlerManifestFetch,
        ModelManifestFetchRequest,
        EnumManifestFetchStatus,
    )

    handler = HandlerManifestFetch()
    request = ModelManifestFetchRequest(runtime_url="http://192.168.86.201:18085")  # onex-allow-internal-ip
    result = await handler.fetch(request)
    if result.status == EnumManifestFetchStatus.SUCCESS:
        manifest = result.manifest
    ```
"""

from .handlers import HandlerManifestFetch
from .models import (
    EnumManifestFetchStatus,
    ModelManifestFetchRequest,
    ModelManifestFetchResult,
)
from .node import NodeManifestFetchEffect
from .protocols import ProtocolManifestFetch

__all__ = [
    # Node
    "NodeManifestFetchEffect",
    # Models
    "EnumManifestFetchStatus",
    "ModelManifestFetchRequest",
    "ModelManifestFetchResult",
    # Protocols
    "ProtocolManifestFetch",
    # Handlers
    "HandlerManifestFetch",
]

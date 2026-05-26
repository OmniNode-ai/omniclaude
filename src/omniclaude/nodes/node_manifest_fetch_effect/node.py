# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeManifestFetchEffect - 100% contract-driven.

The NodeManifestFetchEffect class, a minimal shell that inherits from
NodeEffect. All effect logic is driven by the contract.yaml.

Capability: manifest.fetch

The node exposes one operation:
- fetch: Retrieve the ONEX runtime manifest via HTTP

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolManifestFetch). The actual fetch backend (e.g., HTTP) implements
this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeManifestFetchEffect(NodeEffect):
    """Effect node for fetching the ONEX runtime manifest.

    Capability: manifest.fetch

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the manifest fetch effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodeManifestFetchEffect"]

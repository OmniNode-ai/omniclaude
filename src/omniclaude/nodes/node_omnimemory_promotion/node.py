# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeOmniMemoryPromotionCompute — thin coordination shell.

Stage 6 of the NL Intent-Plan-Ticket Compiler.

Capability: nl.omnimemory.promote.compute
All compute logic lives in HandlerPatternPromotionDefault; this node is a
pure delegation shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeOmniMemoryPromotionCompute(NodeCompute[Any, Any]):
    """Compute node for OmniMemory pattern promotion.

    Capability: nl.omnimemory.promote.compute

    All behavior defined in handler.  Handler resolved via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialise the OmniMemory Promotion compute node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeOmniMemoryPromotionCompute"]

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeNlIntentPipelineCompute — thin coordination shell.

Stage 1→2 of the NL Intent-Plan-Ticket Compiler.

Capability: nl.intent.pipeline.compute
All compute logic lives in HandlerNlIntentDefault; this node is a pure
delegation shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeNlIntentPipelineCompute(NodeCompute):
    """Compute node for NL → Intent Object parsing.

    Capability: nl.intent.pipeline.compute

    All behavior defined in handler.  Handler resolved via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialise the NL Intent Pipeline compute node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeNlIntentPipelineCompute"]

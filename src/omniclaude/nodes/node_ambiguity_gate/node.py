# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeAmbiguityGateCompute — thin coordination shell.

Stage 3.5 of the NL Intent-Plan-Ticket Compiler (gate between
Stage 3 Plan DAG Generation and Stage 4 Ticket Compilation).

Capability: nl.ambiguity.gate.compute
All compute logic lives in HandlerAmbiguityGateDefault; this node is a
pure delegation shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeAmbiguityGateCompute(NodeCompute[Any, Any]):
    """Compute node for the Plan→Ticket ambiguity gate.

    Capability: nl.ambiguity.gate.compute

    All behavior defined in handler.  Handler resolved via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialise the Ambiguity Gate compute node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeAmbiguityGateCompute"]

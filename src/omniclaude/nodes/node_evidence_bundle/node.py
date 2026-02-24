# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""NodeEvidenceBundleCompute — thin coordination shell.

Stage 5 of the NL Intent-Plan-Ticket Compiler.

Capability: nl.evidence.bundle.compute
All compute logic lives in HandlerEvidenceBundleDefault; this node is a
pure delegation shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeEvidenceBundleCompute(NodeCompute[Any, Any]):
    """Compute node for evidence bundle generation.

    Capability: nl.evidence.bundle.compute

    All behavior defined in handler.  Handler resolved via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialise the Evidence Bundle compute node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodeEvidenceBundleCompute"]

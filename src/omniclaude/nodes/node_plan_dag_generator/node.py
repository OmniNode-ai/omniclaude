# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodePlanDagGeneratorCompute — thin coordination shell.

Stage 3 of the NL Intent-Plan-Ticket Compiler.

Capability: nl.plan.dag.compute
All compute logic lives in HandlerPlanDagDefault; this node is a pure
delegation shell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodePlanDagGeneratorCompute(NodeCompute[Any, Any]):
    """Compute node for Intent → Plan DAG generation.

    Capability: nl.plan.dag.compute

    All behavior defined in handler.  Handler resolved via ServiceRegistry.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialise the Plan DAG Generator compute node.

        Args:
            container: ONEX container for dependency injection.
        """
        super().__init__(container)


__all__ = ["NodePlanDagGeneratorCompute"]

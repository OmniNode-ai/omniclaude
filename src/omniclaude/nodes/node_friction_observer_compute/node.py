# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""FrictionObserverNode — contract-driven friction signal classifier.

Declarative compute node. The classification rules and the topic wiring live in
contract.yaml; the work is ``HandlerFrictionObserver``.

The hooks call the portable classifier under ``plugins/onex/skills/_shared``
directly; this node serves the same contract rules to the runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeFrictionObserverCompute(NodeCompute):
    """Classify failure signals using contract-driven rules."""

    def __init__(self, container: ModelONEXContainer) -> None:
        super().__init__(container)


__all__ = ["NodeFrictionObserverCompute"]

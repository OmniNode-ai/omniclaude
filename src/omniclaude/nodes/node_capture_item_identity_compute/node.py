# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""NodeCaptureItemIdentityCompute - contract-driven; the work is in the handler."""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_compute import NodeCompute

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodeCaptureItemIdentityCompute(NodeCompute):
    """Shared item identity, producer sequence and barrier for the capture hooks."""

    def __init__(self, container: ModelONEXContainer) -> None:
        super().__init__(container)


__all__ = ["NodeCaptureItemIdentityCompute"]

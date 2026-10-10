# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Declarative effect node for the scheduled dev-head monitor."""

from omnibase_core.nodes.node_effect import NodeEffect


class NodeDevHeadMonitorEffect(NodeEffect):
    """Behavior and bus routing are declared in contract.yaml."""


__all__ = ["NodeDevHeadMonitorEffect"]

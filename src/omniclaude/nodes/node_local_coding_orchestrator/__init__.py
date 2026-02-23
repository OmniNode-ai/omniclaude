# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeLocalCodingOrchestrator - Contract-driven orchestrator for local coding workflow.

This package provides the NodeLocalCodingOrchestrator node for coordinating
the local coding workflow across downstream effect nodes.

Capability: local_coding.orchestration

INVARIANT: This node has zero subprocess calls and zero API client imports.
All external I/O is delegated to effect nodes.

Exported Components:
    Node:
        NodeLocalCodingOrchestrator - The orchestrator node class (minimal shell)
"""

from .node import NodeLocalCodingOrchestrator

__all__ = [
    # Node
    "NodeLocalCodingOrchestrator",
]

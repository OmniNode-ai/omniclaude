# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodeGitEffect - Contract-driven effect node for git operations.

This package provides the NodeGitEffect node for all git and GitHub CLI
operations with pluggable backends.

Capability: git.operations

INVARIANT: This node is the only place subprocess git/gh calls are permitted.
All PRs created via this node include a mandatory ticket stamp block.

Exported Components:
    Node:
        NodeGitEffect - The effect node class (minimal shell)

    Models:
        ModelGitRequest - Input model for git operations
        ModelGitResult - Output model for git operations

    Protocols:
        ProtocolGitOperations - Interface for git backends
"""

from .models import ModelGitRequest, ModelGitResult
from .node import NodeGitEffect
from .protocols import ProtocolGitOperations

__all__ = [
    # Node
    "NodeGitEffect",
    # Models
    "ModelGitRequest",
    "ModelGitResult",
    # Protocols
    "ProtocolGitOperations",
]

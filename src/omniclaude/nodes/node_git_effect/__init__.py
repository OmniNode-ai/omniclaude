# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
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
        ModelPRListFilters - Typed filter model for pr_list

    Protocols:
        ProtocolGitOperations - Interface for git backends

    Handlers:
        HandlerGitSubprocess - Subprocess-based backend implementation
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .handlers import HandlerGitSubprocess
    from .models import ModelGitRequest, ModelGitResult, ModelPRListFilters
    from .node import NodeGitEffect
    from .protocols import ProtocolGitOperations

_EXPORTS = {
    "NodeGitEffect": "node",
    "ModelGitRequest": "models.model_git_request",
    "ModelGitResult": "models.model_git_result",
    "ModelPRListFilters": "models.model_git_request",
    "ProtocolGitOperations": "protocols.protocol_git_operations",
    "HandlerGitSubprocess": "handlers.handler_git_subprocess",
}

__all__ = [
    # Node
    "NodeGitEffect",
    # Models
    "ModelGitRequest",
    "ModelGitResult",
    "ModelPRListFilters",
    # Protocols
    "ProtocolGitOperations",
    # Handlers
    "HandlerGitSubprocess",
]


def __getattr__(name: str) -> object:
    if name in _EXPORTS:
        submodule = _EXPORTS[name]
        module = importlib.import_module(f"{__name__}.{submodule}")
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

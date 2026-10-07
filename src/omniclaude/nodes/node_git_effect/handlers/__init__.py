# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Handlers for the NodeGitEffect node.

This package provides concrete backend implementations for git operations.

Exported:
    HandlerGitSubprocess - Subprocess-based backend for git/gh CLI operations
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .handler_git_subprocess import HandlerGitSubprocess

_EXPORTS = {
    "HandlerGitSubprocess": "handler_git_subprocess",
}

__all__ = [
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

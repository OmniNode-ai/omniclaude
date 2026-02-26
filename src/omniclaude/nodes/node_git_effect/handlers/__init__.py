# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Handlers for the NodeGitEffect node.

This package provides concrete backend implementations for git operations.

Exported:
    HandlerGitSubprocess - Subprocess-based backend for git/gh CLI operations
"""

from .handler_git_subprocess import HandlerGitSubprocess

__all__ = [
    "HandlerGitSubprocess",
]

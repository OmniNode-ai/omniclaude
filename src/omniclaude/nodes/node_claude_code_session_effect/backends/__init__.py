# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Backends for the NodeClaudeCodeSessionEffect node.

This package contains pluggable backend implementations for Claude Code
session management.

Exported:
    SubprocessClaudeCodeSessionBackend: Subprocess-based backend using the
        ``claude`` CLI binary.
"""

from .backend_subprocess import SubprocessClaudeCodeSessionBackend

__all__ = [
    "SubprocessClaudeCodeSessionBackend",
]

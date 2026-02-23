# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocols for the NodeGitEffect node.

This package defines the protocol interface for git operation backends.

Exported:
    ProtocolGitOperations: Runtime-checkable protocol for git backends

Operation Mapping (from node contract io_operations):
    - branch_create operation -> ProtocolGitOperations.branch_create()
    - commit operation -> ProtocolGitOperations.commit()
    - push operation -> ProtocolGitOperations.push()
    - pr_create operation -> ProtocolGitOperations.pr_create()
    - pr_update operation -> ProtocolGitOperations.pr_update()
    - pr_close operation -> ProtocolGitOperations.pr_close()

Backend implementations must:
    1. Provide handler_key property identifying the backend type
    2. Inject ticket stamp block in PR body for pr_create
    3. Use subprocess for git/gh calls (no other node may do this)
"""

from .protocol_git_operations import ProtocolGitOperations

__all__ = [
    "ProtocolGitOperations",
]

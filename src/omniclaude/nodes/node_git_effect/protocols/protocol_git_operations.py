# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for git operations backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_git_effect.models import ModelGitRequest, ModelGitResult


@runtime_checkable
class ProtocolGitOperations(Protocol):
    """Runtime-checkable protocol for git operation backends.

    All git backend implementations must implement this protocol.
    The handler_key property identifies the backend type for routing.

    Operation mapping (from node contract io_operations):
        - branch_create operation -> branch_create()
        - commit operation -> commit()
        - push operation -> push()
        - pr_create operation -> pr_create()
        - pr_update operation -> pr_update()
        - pr_close operation -> pr_close()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'subprocess')."""
        ...

    async def branch_create(self, request: ModelGitRequest) -> ModelGitResult:
        """Create a new git branch.

        Args:
            request: Git request with branch_name and base_ref populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...

    async def commit(self, request: ModelGitRequest) -> ModelGitResult:
        """Stage all changes and create a commit.

        Args:
            request: Git request with commit_message populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...

    async def push(self, request: ModelGitRequest) -> ModelGitResult:
        """Push branch to remote.

        Args:
            request: Git request with branch_name and force_push populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...

    async def pr_create(self, request: ModelGitRequest) -> ModelGitResult:
        """Create a pull request with mandatory ticket stamp block.

        The PR body must contain a ticket stamp block referencing request.ticket_id.
        Implementations must inject this block if not already present in pr_body.

        Args:
            request: Git request with pr_title, pr_body, ticket_id, base_branch populated.

        Returns:
            ModelGitResult with pr_url and pr_number populated on success.
        """
        ...

    async def pr_update(self, request: ModelGitRequest) -> ModelGitResult:
        """Update an existing pull request.

        Args:
            request: Git request with pr_number and optional pr_title/pr_body populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...

    async def pr_close(self, request: ModelGitRequest) -> ModelGitResult:
        """Close a pull request without merging.

        Args:
            request: Git request with pr_number populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...


__all__ = ["ProtocolGitOperations"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
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
        - pr_merge operation -> pr_merge()
        - pr_list operation -> pr_list()
        - pr_view operation -> pr_view()
        - tag_create operation -> tag_create()
        - label_add operation -> label_add()
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

    async def pr_merge(self, request: ModelGitRequest) -> ModelGitResult:
        """Merge a PR. If request.use_merge_queue=True, adds to MQ instead.

        Args:
            request: Git request with pr_number populated.

        Returns:
            ModelGitResult with merge_state populated on success.
        """
        ...

    async def pr_list(self, request: ModelGitRequest) -> ModelGitResult:
        """List PRs. Returns structured JSON in result.pr_list.

        Args:
            request: Git request with json_fields populated.

        Returns:
            ModelGitResult with pr_list populated on success.
        """
        ...

    async def pr_view(self, request: ModelGitRequest) -> ModelGitResult:
        """View single PR. Returns structured JSON in result.pr_data.

        Args:
            request: Git request with pr_number and json_fields populated.

        Returns:
            ModelGitResult with pr_data populated on success.
        """
        ...

    async def tag_create(self, request: ModelGitRequest) -> ModelGitResult:
        """Create and push a git tag.

        Args:
            request: Git request with tag_name and optional tag_message populated.

        Returns:
            ModelGitResult with tag_name populated on success.
        """
        ...

    async def label_add(self, request: ModelGitRequest) -> ModelGitResult:
        """Add labels to a PR.

        Args:
            request: Git request with pr_number and labels populated.

        Returns:
            ModelGitResult with operation outcome.
        """
        ...


__all__ = ["ProtocolGitOperations"]

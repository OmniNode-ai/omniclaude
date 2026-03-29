# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for pr_create ticket linkage guard [OMN-6919]."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_git_effect.models.model_git_request import ModelGitRequest


class TestPrCreateTicketGuard:
    """Test that pr_create correctly validates ticket linkage via ModelGitRequest."""

    @pytest.mark.unit
    def test_pr_create_rejects_unlinked_title(self) -> None:
        """validate_pr_title_ticket_ref rejects titles without OMN-XXXX."""
        assert ModelGitRequest.validate_pr_title_ticket_ref("feat: no ticket") is False

    @pytest.mark.unit
    def test_pr_create_accepts_linked_title(self) -> None:
        """validate_pr_title_ticket_ref accepts titles with OMN-XXXX."""
        assert (
            ModelGitRequest.validate_pr_title_ticket_ref("feat: with ticket [OMN-1234]")
            is True
        )

    @pytest.mark.unit
    def test_pr_create_accepts_exempt_title(self) -> None:
        """validate_pr_title_ticket_ref accepts exempt titles."""
        assert (
            ModelGitRequest.validate_pr_title_ticket_ref(
                "chore(deps): bump foo from 1.0 to 2.0"
            )
            is True
        )

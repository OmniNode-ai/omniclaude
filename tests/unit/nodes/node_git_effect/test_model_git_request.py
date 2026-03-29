# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for ModelGitRequest.validate_pr_title_ticket_ref [OMN-6918]."""

from __future__ import annotations

import pytest

from omniclaude.nodes.node_git_effect.models.model_git_request import ModelGitRequest

EXEMPT_TITLES = [
    "chore(deps): bump requests from 2.31.0 to 2.32.0",
    "chore(deps-dev): bump pytest from 8.0 to 8.1",
    "build(deps): bump actions/checkout from 4 to 6",
    "Bump hashicorp/aws from 6.36.0 to 6.37.0",
    "chore: release omnibase_core v0.34.0",
    "chore(release): v0.12.0",
    "release: omnibase_infra v0.29.0",
]

VALID_TITLES = [
    "feat: add session registry [OMN-6853]",
    "fix(ci): resolve flaky test [OMN-6878]",
    "OMN-6912: enforce ticket linkage",
]

INVALID_TITLES = [
    "feat: add some feature without ticket",
    "fix: random fix",
    "refactor: migrate state paths",
]


class TestPrTitleTicketValidation:
    """Test that ModelGitRequest.validate_pr_title_ticket_ref works."""

    @pytest.mark.unit
    @pytest.mark.parametrize("title", VALID_TITLES)
    def test_valid_titles_pass(self, title: str) -> None:
        assert ModelGitRequest.validate_pr_title_ticket_ref(title) is True

    @pytest.mark.unit
    @pytest.mark.parametrize("title", EXEMPT_TITLES)
    def test_exempt_titles_pass(self, title: str) -> None:
        assert ModelGitRequest.validate_pr_title_ticket_ref(title) is True

    @pytest.mark.unit
    @pytest.mark.parametrize("title", INVALID_TITLES)
    def test_invalid_titles_fail(self, title: str) -> None:
        assert ModelGitRequest.validate_pr_title_ticket_ref(title) is False

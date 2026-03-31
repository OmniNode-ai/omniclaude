# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for epic-team stacked branch execution (OMN-6270).

Verifies:
- SKILL.md documents stacked branch execution
- prompt.md contains base_branch parameter in dispatch_ticket
- prompt.md contains resolve_base_branch logic
- prompt.md chain_targets integration with wave dispatch
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = Path("plugins/onex/skills/epic_team")


class TestStackedBranchDocumentation:
    """Verify SKILL.md documents stacked branch execution."""

    def test_skill_md_documents_stacked_branches(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "Stacked Branch Execution" in content, (
            "SKILL.md must document stacked branch execution"
        )

    def test_skill_md_references_ticket(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "OMN-6270" in content, "SKILL.md must reference OMN-6270"

    def test_skill_md_documents_chain_depth_limit(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "chain depth" in content.lower() or "Chain depth" in content, (
            "SKILL.md must document chain depth limit"
        )

    def test_skill_md_documents_fallback(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "fall back" in content.lower() or "Fallback" in content, (
            "SKILL.md must document fallback to main when upstream fails"
        )


class TestStackedBranchDispatch:
    """Verify prompt.md implements stacked branch dispatch."""

    def test_dispatch_ticket_accepts_base_branch(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "base_branch" in content, (
            "prompt.md dispatch_ticket must accept base_branch parameter"
        )

    def test_resolve_base_branch_function_exists(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "resolve_base_branch" in content, (
            "prompt.md must define resolve_base_branch function"
        )

    def test_chain_targets_used_in_wave_dispatch(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "chain_targets" in content, (
            "prompt.md must use chain_targets in wave dispatch"
        )

    def test_stacked_branch_instruction_in_dispatch(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "STACKED BRANCH" in content, (
            "prompt.md must include STACKED BRANCH instruction in dispatch prompt"
        )

    def test_pr_targets_base_branch(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "--base" in content, (
            "prompt.md must instruct gh pr create --base for stacked PRs"
        )

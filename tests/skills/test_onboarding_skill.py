# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the onboarding skill definition (OMN-8270 scaffolding)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.mark.unit
class TestOnboardingSkill:
    """Verify the /onex:onboarding skill scaffolding is properly defined."""

    SKILL_DIR = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "onex"
        / "skills"
        / "onboarding"
    )

    EXPECTED_POLICIES = {
        "new_employee",
        "standalone_quickstart",
        "contributor_local",
        "full_platform",
    }

    EXPECTED_ARGS = {"--policy", "--skip", "--continue-on-failure", "--dry-run"}

    def test_skill_md_exists(self) -> None:
        assert (self.SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_frontmatter(self) -> None:
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "SKILL.md must have YAML frontmatter delimited by ---"
        yaml.safe_load(parts[1])

    def test_frontmatter_required_fields(self) -> None:
        frontmatter = self._load_frontmatter()
        for key in ("description", "mode", "version", "category", "tags", "args"):
            assert key in frontmatter, f"frontmatter missing required key: {key}"
        assert frontmatter["category"] == "onboarding"
        assert "onboarding" in frontmatter["tags"]

    def test_frontmatter_declares_all_expected_args(self) -> None:
        frontmatter = self._load_frontmatter()
        declared = {arg["name"] for arg in frontmatter["args"]}
        missing = self.EXPECTED_ARGS - declared
        assert not missing, f"SKILL.md args missing: {missing}"

    def test_body_documents_all_policies(self) -> None:
        body = self._load_body()
        for policy in self.EXPECTED_POLICIES:
            assert policy in body, f"policy not documented in SKILL.md body: {policy}"

    def test_body_has_usage_section(self) -> None:
        body = self._load_body()
        assert "## Usage" in body
        assert "/onex:onboarding" in body

    def test_body_references_engine_location(self) -> None:
        body = self._load_body()
        assert "omnibase_infra" in body, (
            "SKILL.md must reference the omnibase_infra onboarding engine it wraps"
        )

    def _load_frontmatter(self) -> dict:
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        parts = content.split("---", 2)
        return yaml.safe_load(parts[1])

    def _load_body(self) -> str:
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        return content.split("---", 2)[2]

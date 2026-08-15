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

    # All 9 policies shipped in omnibase_infra/onboarding/policies/.
    EXPECTED_POLICIES = {
        "setup",
        "standalone_quickstart",
        "new_employee",
        "contributor_local",
        "contributor_cloud",
        "contributor_hybrid",
        "omnimarket_quickstart",
        "full_platform",
        "interactive_onboarding",
    }

    EXPECTED_ARGS = {
        "--policy",
        "--skip",
        "--continue-on-failure",
        "--dry-run",
        "--env-output-path",
        "--overlay-output-path",
    }

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
        unexpected = declared - self.EXPECTED_ARGS
        assert not missing, f"SKILL.md args missing: {missing}"
        assert not unexpected, f"SKILL.md has unexpected args: {unexpected}"

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

    def test_invocation_snippet_is_executable_as_written(self) -> None:
        """The documented snippet must be runnable, not pseudocode (OMN-16040).

        Each assertion pins a defect that made the previous snippet fail at
        runtime: a literal placeholder used as a dict key, a hard dependency on
        a source checkout, and direct handler invocation instead of dispatch.
        """
        body = self._load_body()
        assert "onex" in body and "node node_onboarding" in body, (
            "the skill must dispatch node_onboarding, not import its handler"
        )
        assert "HandlerOnboarding" not in body, (
            "direct handler invocation is rejected by the OMN-12237 gate"
        )
        assert "<markdown-output-field>" not in body, (
            "placeholder left in an executable snippet"
        )
        assert "rendered_output" in body, "the skill must name the real output key"
        assert "cd $OMNI" not in body, (
            "the snippet must run from the plugin venv, not a source checkout"
        )
        assert "CLAUDE_PLUGIN_DATA" in body, (
            "the snippet must resolve the plugin venv interpreter"
        )

    def test_body_states_the_real_canonical_graph_size(self) -> None:
        """canonical.yaml has 17 steps; the doc claimed 10 (OMN-16040)."""
        body = self._load_body()
        assert "17-step DAG" in body
        assert "10-step DAG" not in body

    def _load_frontmatter(self) -> dict:
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        parts = content.split("---", 2)
        return yaml.safe_load(parts[1])

    def _load_body(self) -> str:
        content = (self.SKILL_DIR / "SKILL.md").read_text()
        return content.split("---", 2)[2]

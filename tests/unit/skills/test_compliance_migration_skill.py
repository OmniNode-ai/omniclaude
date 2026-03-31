# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Compliance migration skill structural tests (OMN-6846).

Verifies the compliance_migration skill has the required files and structure:
- SKILL.md with correct frontmatter
- prompt.md with invocation instructions
- Correct args and workflow sections
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SKILL_DIR = Path("plugins/onex/skills/compliance_migration")


class TestComplianceMigrationSkillStructure:
    """Verify skill directory structure and required files."""

    def test_skill_directory_exists(self) -> None:
        assert SKILL_DIR.is_dir(), f"Skill directory not found: {SKILL_DIR}"

    def test_skill_md_exists(self) -> None:
        skill_md = SKILL_DIR / "SKILL.md"
        assert skill_md.is_file(), f"SKILL.md not found: {skill_md}"

    def test_prompt_md_exists(self) -> None:
        prompt_md = SKILL_DIR / "prompt.md"
        assert prompt_md.is_file(), f"prompt.md not found: {prompt_md}"


class TestComplianceMigrationSkillContent:
    """Verify SKILL.md and prompt.md content requirements."""

    def test_skill_md_has_frontmatter(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---"), "SKILL.md must start with YAML frontmatter"
        assert content.count("---") >= 2, "SKILL.md must have opening and closing ---"

    def test_skill_md_has_description(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "description:" in content, (
            "SKILL.md frontmatter must include description"
        )

    def test_skill_md_has_handler_arg(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--handler" in content, "SKILL.md must declare --handler arg"

    def test_skill_md_has_apply_arg(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--apply" in content, "SKILL.md must declare --apply arg"

    def test_skill_md_has_validate_arg(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "--validate" in content, "SKILL.md must declare --validate arg"

    def test_skill_md_has_violation_types(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "HARDCODED_TOPIC" in content, (
            "SKILL.md must document HARDCODED_TOPIC violation type"
        )

    def test_prompt_md_has_invocation(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "compliance" in content.lower(), (
            "prompt.md must reference the skill name"
        )

    def test_prompt_md_has_handler_arg(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "--handler" in content, "prompt.md must accept --handler argument"

    def test_prompt_md_has_apply_option(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "--apply" in content, "prompt.md must support --apply option"

    def test_prompt_md_has_contract_generation(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "contract.yaml" in content, (
            "prompt.md must describe contract YAML generation"
        )

    def test_skill_md_references_dependencies(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "onex_change_control" in content, (
            "SKILL.md must reference onex_change_control dependency"
        )

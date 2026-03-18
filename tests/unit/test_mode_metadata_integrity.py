# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI guard: every agent config and skill must have a mode field.

Prevents drift where new configs/skills are added without mode annotations,
and ensures both-mode agents don't contain ONEX-specific content in their
base prompts.
"""

import re
from pathlib import Path

import pytest
import yaml

AGENTS_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "agents" / "configs"
SKILLS_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "skills"

ONEX_TERMS = {
    "ONEX",
    "ModelContract",
    "omnibase",
    "Kafka",
    "poly enforcer",
    "4-node",
    "four-node",
}
INTERNAL_PACKAGES = {"omnibase_core", "omnibase_infra", "omniclaude.", "onex.evt."}


@pytest.mark.unit
def test_every_agent_config_has_mode_field():
    """Every agent YAML must declare mode: full | both."""
    missing = []
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if data and "mode" not in data:
            missing.append(yaml_file.name)
    assert not missing, (
        f"Agent configs missing 'mode' field: {missing}. "
        f"Add 'mode: full' (default) or 'mode: both' (lite-compatible)."
    )


@pytest.mark.unit
def test_both_mode_agents_have_no_onex_in_base_prompt():
    """Both-mode agent base prompts must not contain ONEX-specific terms."""
    violations = []
    for yaml_file in sorted(AGENTS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
        if not data or data.get("mode") != "both":
            continue
        # Check system_prompt_base if it exists, otherwise check the main prompt fields
        base_prompt = data.get("system_prompt_base", "")
        if not base_prompt:
            # Fall back to checking the primary system prompt
            base_prompt = data.get("system_prompt", "")
        for term in ONEX_TERMS:
            if term.lower() in base_prompt.lower():
                violations.append(f"{yaml_file.name}: '{term}' found in prompt")
    assert not violations, (
        "Both-mode agent prompts contain ONEX-specific terms:\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_every_skill_has_mode_field():
    """Every skill SKILL.md must have a mode field in frontmatter."""
    missing = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text()
        if "mode:" not in content[:1500]:
            missing.append(skill_dir.name)
    assert not missing, (
        f"Skills missing 'mode' field in frontmatter: {missing}. "
        f"Add 'mode: full' or 'mode: both' to SKILL.md YAML frontmatter."
    )


@pytest.mark.unit
def test_both_mode_skills_no_internal_package_refs():
    """Skills marked mode: both should not reference internal OmniNode packages."""
    violations = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text()
        # Check if mode: both
        match = re.search(r"^mode:\s*both", content, re.MULTILINE)
        if not match:
            continue
        for term in INTERNAL_PACKAGES:
            if term in content:
                violations.append(
                    f"{skill_dir.name}: references '{term}' but is mode: both"
                )
    assert not violations, (
        "Skills marked mode:both contain OmniNode-specific references:\n"
        + "\n".join(violations)
    )

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-9690: Verify dispatch_worker skill injects Operating Rules into worker prompts."""

from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).parents[2] / "plugins" / "onex" / "skills"
DISPATCH_WORKER_DIR = SKILLS_ROOT / "dispatch_worker"

REQUIRED_RULES = [
    "No pre-existing excuse",
    "PR closing keyword",
    "Worktree-only development",
    "Full test suite before push",
    "Never bypass pre-commit hooks",
]

WORKER_TEMPLATE_VERSION = "v1"


@pytest.mark.unit
def test_skill_md_has_worker_template_version() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    assert skill_md.exists(), f"SKILL.md not found at {skill_md}"
    content = skill_md.read_text()
    assert f"worker_template_version: {WORKER_TEMPLATE_VERSION}" in content, (
        f"SKILL.md missing 'worker_template_version: {WORKER_TEMPLATE_VERSION}'"
    )


@pytest.mark.unit
def test_skill_md_documents_all_operating_rules() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    content = skill_md.read_text()
    missing = [rule for rule in REQUIRED_RULES if rule not in content]
    assert not missing, f"SKILL.md missing Operating Rules documentation: {missing}"


@pytest.mark.unit
def test_prompt_md_injects_operating_rules_header() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    assert prompt_md.exists(), f"prompt.md not found at {prompt_md}"
    content = prompt_md.read_text()
    assert "## Inject Operating Rules" in content, (
        "prompt.md missing '## Inject Operating Rules' section"
    )


@pytest.mark.unit
def test_prompt_md_contains_all_operating_rules() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    missing = [rule for rule in REQUIRED_RULES if rule not in content]
    assert not missing, f"prompt.md missing Operating Rules text: {missing}"


@pytest.mark.unit
def test_prompt_md_uses_final_prompt_in_agent_spawn() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    assert "prompt=final_prompt" in content, (
        "prompt.md Agent() spawn must use 'prompt=final_prompt', "
        "not 'prompt=result.validated_prompt_template'"
    )


@pytest.mark.unit
def test_prompt_md_does_not_pass_raw_validated_template_to_agent() -> None:
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    content = prompt_md.read_text()
    # The raw template reference should only appear in the node invocation section,
    # not as the agent spawn argument.
    spawn_section_start = content.find("## Spawn Agent")
    assert spawn_section_start != -1, "prompt.md missing '## Spawn Agent' section"
    spawn_section = content[spawn_section_start:]
    assert "prompt=result.validated_prompt_template" not in spawn_section, (
        "Spawn Agent section must not pass raw validated_prompt_template; "
        "use final_prompt (Operating Rules prepended)"
    )


@pytest.mark.unit
def test_operating_rules_version_consistent_across_files() -> None:
    skill_md = DISPATCH_WORKER_DIR / "SKILL.md"
    prompt_md = DISPATCH_WORKER_DIR / "prompt.md"
    version_tag = f"worker_template_version: {WORKER_TEMPLATE_VERSION}"
    for path in (skill_md, prompt_md):
        content = path.read_text()
        assert version_tag in content, (
            f"{path.name} missing version tag '{version_tag}'"
        )

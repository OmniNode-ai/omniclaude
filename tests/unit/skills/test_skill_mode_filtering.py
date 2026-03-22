# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for skill mode filtering [OMN-5400].

Validates that:
1. Every SKILL.md has a mode field in its YAML frontmatter.
2. Mode values are restricted to 'full' or 'both'.
3. The _filter_helpers.sh mode filter excludes full-mode skills in lite mode.
"""

import re
import subprocess
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parents[3] / "plugins" / "onex" / "skills"
FILTER_HELPERS = SKILLS_DIR / "deploy_local_plugin" / "_filter_helpers.sh"


@pytest.mark.unit
def test_every_skill_has_mode_field() -> None:
    """Every skill SKILL.md must have a mode field in frontmatter."""
    missing: list[str] = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        # Skip internal support dirs
        if skill_dir.name.startswith("_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text()
        # Check YAML frontmatter for a top-level mode field (not nested in args)
        # Must appear between the opening --- and closing --- at column 0
        frontmatter_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if frontmatter_match:
            frontmatter = frontmatter_match.group(1)
            if not re.search(r"^mode:\s*\S+", frontmatter, re.MULTILINE):
                missing.append(skill_dir.name)
        else:
            missing.append(skill_dir.name)
    assert not missing, f"Skills missing 'mode' field in frontmatter: {missing}"


@pytest.mark.unit
def test_mode_values_are_valid() -> None:
    """Mode must be 'full' or 'both'."""
    invalid: list[str] = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith("_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text()
        frontmatter_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            continue
        frontmatter = frontmatter_match.group(1)
        match = re.search(r"^mode:\s*(\S+)", frontmatter, re.MULTILINE)
        if match and match.group(1) not in ("full", "both"):
            invalid.append(f"{skill_dir.name}: mode={match.group(1)}")
    assert not invalid, f"Invalid mode values: {invalid}"


@pytest.mark.unit
def test_both_mode_skills_are_generic() -> None:
    """Skills with mode: both should be generic (codebase-independent)."""
    expected_both = {
        "condition_based_waiting",
        "defense_in_depth",
        "executing_plans",
        "finishing_a_development_branch",
        "hostile_reviewer",
        "systematic_debugging",
        "test_discipline",
        "writing_skills",
    }
    actual_both: set[str] = set()
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        content = skill_md.read_text()
        frontmatter_match = re.search(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not frontmatter_match:
            continue
        frontmatter = frontmatter_match.group(1)
        match = re.search(r"^mode:\s*(\S+)", frontmatter, re.MULTILINE)
        if match and match.group(1) == "both":
            actual_both.add(skill_dir.name)
    assert actual_both == expected_both, (
        f"Unexpected mode:both set.\n"
        f"  Missing from both: {expected_both - actual_both}\n"
        f"  Unexpected both: {actual_both - expected_both}"
    )


@pytest.mark.unit
def test_filter_helpers_mode_filter_lite() -> None:
    """In lite mode, _skill_passes_mode_filter excludes mode:full skills."""
    # This test invokes the bash filter helpers directly
    if not FILTER_HELPERS.exists():
        pytest.skip("_filter_helpers.sh not found")

    # Find a skill with mode: full and one with mode: both
    full_skill = SKILLS_DIR / "epic_team"
    both_skill = SKILLS_DIR / "systematic_debugging"

    if not full_skill.exists() or not both_skill.exists():
        pytest.skip("Test skills not found")

    # Test that mode:full skill is EXCLUDED in lite mode
    result_full = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{FILTER_HELPERS}" && '
            f'OMNICLAUDE_MODE=lite _skill_passes_mode_filter "{full_skill}"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_full.returncode == 1, (
        f"mode:full skill should be excluded in lite mode, "
        f"got rc={result_full.returncode}"
    )

    # Test that mode:both skill is INCLUDED in lite mode
    result_both = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{FILTER_HELPERS}" && '
            f'OMNICLAUDE_MODE=lite _skill_passes_mode_filter "{both_skill}"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result_both.returncode == 0, (
        f"mode:both skill should be included in lite mode, "
        f"got rc={result_both.returncode}"
    )


@pytest.mark.unit
def test_filter_helpers_mode_filter_full() -> None:
    """In full mode (default), all skills pass mode filtering."""
    if not FILTER_HELPERS.exists():
        pytest.skip("_filter_helpers.sh not found")

    full_skill = SKILLS_DIR / "epic_team"
    if not full_skill.exists():
        pytest.skip("Test skill not found")

    # Default (no OMNICLAUDE_MODE set) should include all
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{FILTER_HELPERS}" && _skill_passes_mode_filter "{full_skill}"',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"mode:full skill should pass in default/full mode, got rc={result.returncode}"
    )

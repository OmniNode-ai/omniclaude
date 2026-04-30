# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Focused retired skill surface checks for OMN-9428."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILLS_ROOT = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills"

RETIRED_SKILLS = {
    "autopilot": "/onex:session",
    "begin_day": "/onex:session --mode interactive",
    "overnight": "/onex:session --mode autonomous",
}


def _frontmatter(skill_name: str) -> dict[str, object]:
    content = (SKILLS_ROOT / skill_name / "SKILL.md").read_text()
    return yaml.safe_load(content.split("---", 2)[1])


@pytest.mark.unit
@pytest.mark.parametrize("skill_name", sorted(RETIRED_SKILLS))
def test_retired_skills_are_not_user_invocable(skill_name: str) -> None:
    fm = _frontmatter(skill_name)
    assert fm["user_invocable"] is False
    assert fm["retired"] is True
    assert fm["replacement_skill"] == "session"
    assert "retired" in fm["tags"]
    assert "foreground_orchestrator" not in fm


@pytest.mark.unit
@pytest.mark.parametrize(("skill_name", "replacement"), sorted(RETIRED_SKILLS.items()))
def test_retired_prompts_are_stubs(skill_name: str, replacement: str) -> None:
    prompt = (SKILLS_ROOT / skill_name / "prompt.md").read_text()
    assert "retired" in prompt.lower()
    assert "not user-invocable" in prompt
    assert replacement in prompt
    assert "DEPRECATED" not in prompt
    assert "Agent(" not in prompt
    assert "TeamCreate" not in prompt
    assert "CronCreate" not in prompt


@pytest.mark.unit
def test_autopilot_prompt_no_longer_contains_inline_pipeline() -> None:
    prompt = (SKILLS_ROOT / "autopilot" / "prompt.md").read_text()
    assert "Phase A" not in prompt
    assert "Phase B" not in prompt
    assert "Phase C" not in prompt
    assert "Phase D" not in prompt

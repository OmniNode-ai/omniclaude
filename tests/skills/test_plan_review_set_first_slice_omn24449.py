# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-24449: the plan review set skill reviews the first slice, not whole-plan rounds forever."""

from __future__ import annotations

from pathlib import Path

import pytest

SKILL = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "plan_review_set"
    / "SKILL.md"
)


@pytest.mark.unit
def test_skill_names_first_slice_check_and_verdict() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "node_plan_first_slice_compute" in text
    assert "no_first_slice_section" in text


@pytest.mark.unit
def test_skill_drops_unbounded_repeat_rounds_sentence() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "until a round returns no finding you agree with" not in text

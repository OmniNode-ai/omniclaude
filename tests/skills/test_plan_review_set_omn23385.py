# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23385: the plan_review_set skill ends every plan review with a diff-only final round.

The skill is prose. Its final reviewer must be told, word for word, to return a
unified diff and nothing else, and the author must check the diff with
``git apply --check`` before applying or refusing hunks. The distribution
manifest classifies the skill beta.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILL_PATH = Path("plugins/onex/skills/plan_review_set/SKILL.md")
MANIFEST_PATH = Path("plugins/distribution_manifest.yaml")

DIFF_ONLY_INSTRUCTION = (
    "Do not write a review, a summary or any explanation. "
    "Return only a unified diff against the file at the given path"
)
PROSE_ALLOWING_PHRASES: tuple[str, ...] = (
    "with a short summary",
    "and a summary",
    "explain each change",
    "along with your reasoning",
)


def _text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _final_round(text: str) -> str:
    start = text.index("## Final round")
    end = text.index("\n## ", start + 1)
    return text[start:end]


@pytest.mark.unit
def test_skill_declares_rounds_final_round_and_apply_step() -> None:
    text = _text()
    assert text.startswith("---\n")
    for heading in (
        "## Round 1",
        "## Round 2",
        "## Final round",
        "## Apply",
        "## Report",
    ):
        assert heading in text, f"{heading!r} is missing"


@pytest.mark.unit
def test_final_round_names_fable_and_allows_only_a_diff() -> None:
    final = _final_round(_text())
    assert "Fable 5.2" in final
    assert DIFF_ONLY_INSTRUCTION in final
    assert "Nothing outside the diff." in final
    lowered = final.lower()
    for phrase in PROSE_ALLOWING_PHRASES:
        assert phrase not in lowered, f"final round allows prose: {phrase!r}"


@pytest.mark.unit
def test_detector_flags_a_final_round_that_allows_prose() -> None:
    """The control: a final round that asks for a summary fails the check."""
    mutated = _final_round(_text()).replace(
        "Do not write a review, a summary or any explanation.",
        "Write a short summary, then the diff.",
    )
    assert DIFF_ONLY_INSTRUCTION not in mutated


@pytest.mark.unit
def test_apply_step_checks_the_diff_before_applying() -> None:
    text = _text()
    apply_start = text.index("## Apply")
    apply_body = text[apply_start : text.index("\n## ", apply_start + 1)]
    assert "git apply --check" in apply_body
    assert "refuse" in apply_body.lower()


@pytest.mark.unit
def test_manifest_classifies_plan_review_set_beta() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = [c for c in manifest["components"] if c.get("id") == "plan_review_set"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "skill"
    assert entry["exposure"] == "beta"
    assert entry["path"] == str(SKILL_PATH)
    assert entry["backing_nodes"] == []

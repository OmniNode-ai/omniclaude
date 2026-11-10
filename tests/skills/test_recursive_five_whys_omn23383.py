# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The recursive five whys prose skill ships in the onex plugin as a bootstrap skill.

It moved from the internal omni plugin: the procedure names no private
repository, host or record, so it belongs with the public plugin. The skill is
the hand-run form of the practice; no node exists here, so it declares
``bootstrap: true`` and its manifest entry names the ticket under which it moved.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path("plugins/onex/skills/recursive_five_whys")
MANIFEST = Path("plugins/distribution_manifest.yaml")

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## Inputs",
    "## One step",
    "## The tree",
    "## Fixes",
    "## Rules",
    "## Output",
)


def _split(text: str) -> tuple[dict[str, object], str]:
    assert text.startswith("---\n"), "no frontmatter"
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert isinstance(front, dict)
    return front, text[end + 4 :]


def _missing_sections(body: str) -> list[str]:
    return [s for s in REQUIRED_SECTIONS if s not in body]


@pytest.mark.unit
def test_skill_is_a_bootstrap_with_every_section() -> None:
    front, body = _split((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
    assert front["bootstrap"] is True
    assert front["skill_kind"] == "methodology"
    assert str(front["description"]).startswith("Bootstrap skill")
    assert _missing_sections(body) == []
    assert "depth of five" in str(front["description"])
    assert "Stop a branch at depth 5" in body


@pytest.mark.unit
def test_missing_section_is_detected() -> None:
    """Positive control: a body without a section is reported."""
    _, body = _split((SKILL_DIR / "SKILL.md").read_text(encoding="utf-8"))
    assert _missing_sections(body.replace("## Fixes", "## Remedies")) == ["## Fixes"]


@pytest.mark.unit
def test_manifest_entry_names_the_skill_and_a_ticket() -> None:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    entries = [c for c in manifest["components"] if c["id"] == "recursive_five_whys"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "skill"
    assert entry["surface_class"] == "pure_skill"
    assert entry["path"] == "plugins/onex/skills/recursive_five_whys/SKILL.md"
    assert entry["backing_nodes"] == []
    assert "OMN-23383" in entry["rationale"]

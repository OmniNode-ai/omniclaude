# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21461: the eight lean practice skills ship as bootstrap skills.

Each skill is the hand-run form of a lean practice, kept so lanes can test and
iterate on the process while the node-backed skill is built. Each one says it is
a bootstrap, names the node that replaces it (or says none exists yet), and has
the four sections the ticket names. These skills carry no node in this
repository: the node-home ratchet (OMN-20702) refuses one, and the replacing
node is built in omnimarket.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path("plugins/onex/skills")

LEAN_BOOTSTRAP_SKILLS: tuple[str, ...] = (
    "lean_andon_stop",
    "lean_wip_pull",
    "lean_poka_yoke",
    "lean_five_whys",
    "lean_go_and_see",
    "lean_experiment_first",
    "lean_seam_read",
    "lean_session_recovery",
)

# The one bootstrap skill whose practice has no planned node yet.
NO_NODE_YET: frozenset[str] = frozenset({"lean_session_recovery"})

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## The practice",
    "## When to use",
    "## Steps by hand today",
    "## Factory task per step",
)


def _read(skill: str) -> tuple[dict[str, object], str]:
    text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{skill}: no frontmatter"
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert isinstance(front, dict), f"{skill}: frontmatter is not a mapping"
    return front, text[end + 4 :]


@pytest.mark.unit
def test_all_eight_lean_skills_exist_with_the_four_sections() -> None:
    assert len(set(LEAN_BOOTSTRAP_SKILLS)) == 8
    problems: list[str] = []
    for skill in LEAN_BOOTSTRAP_SKILLS:
        if not (SKILLS_DIR / skill / "SKILL.md").is_file():
            problems.append(f"{skill}: SKILL.md is missing")
            continue
        _, body = _read(skill)
        problems.extend(
            f"{skill}: section {section!r} is missing"
            for section in REQUIRED_SECTIONS
            if section not in body
        )
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_each_lean_skill_declares_itself_a_bootstrap_and_names_its_replacement() -> (
    None
):
    problems: list[str] = []
    for skill in LEAN_BOOTSTRAP_SKILLS:
        front, body = _read(skill)
        if front.get("bootstrap") is not True:
            problems.append(f"{skill}: frontmatter must declare bootstrap: true")
        description = str(front.get("description", ""))
        if not description.startswith("Bootstrap skill"):
            problems.append(f"{skill}: description must start with 'Bootstrap skill'")
        if "This skill is a bootstrap skill." not in body:
            problems.append(f"{skill}: body must say it is a bootstrap skill")
        nodes = set(re.findall(r"`(node_[a-z0-9_]+)`", body))
        if skill in NO_NODE_YET:
            if "no node-backed skill yet" not in body:
                problems.append(f"{skill}: must say no node-backed skill exists yet")
        elif not nodes:
            problems.append(f"{skill}: body must name the node that replaces it")
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_lean_skills_have_no_node_of_their_own_here() -> None:
    """A node here would be refused by the node-home ratchet and would end the bootstrap."""
    nodes_dir = Path("src/omniclaude/nodes")
    found = sorted(p.name for p in nodes_dir.glob("node_skill_lean_*"))
    assert found == []


@pytest.mark.unit
def test_lean_bootstrap_skills_are_assigned_in_the_distribution_manifest() -> None:
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    by_id = {c["id"]: c for c in manifest["components"]}
    for skill in LEAN_BOOTSTRAP_SKILLS:
        entry = by_id.get(skill)
        assert entry is not None, f"{skill} is not in the distribution manifest"
        assert entry["surface_class"] == "pure_skill"
        assert entry["backing_nodes"] == []

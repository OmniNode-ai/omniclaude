# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21627: lean_contract_seams ships as a bootstrap skill.

The operator ruled (about 2026-10-31T02:25Z) that a design starts with its
contracts and seams, and that everything connects before any handler logic.
This skill is the hand-run form of that practice. These tests hold its shape:
it says it is a bootstrap and names the node that replaces it, it carries the
six steps in the ruled order, it names the existing command for each proof in
step 5, and it stays prose (no script beside it, no remote shell lines).

The planted example below is a skill text with step 5 removed; the same checks
must refuse it, so the shape test is not vacuous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path("plugins/onex/skills/lean_contract_seams")
SKILL_MD = SKILL_DIR / "SKILL.md"

STEP_TITLES: tuple[str, ...] = (
    "1. **List the graph from the design.**",
    "2. **Write every model and every contract before any logic.**",
    "3. **Scaffold every node from its contract.**",
    "4. **Wire the chain and boot it on both overlays.**",
    "5. **Prove that it connects.**",
    "6. **Only then fill the handlers.**",
)

# Each proof in step 5 names an existing command or skill.
PROOF_COMMANDS: tuple[str, ...] = (
    "omnibase_core.validation.validator_event_chain_walker:ValidatorEventChainWalker",
    "omnibase_core.nodes.node_contract_walker_check_compute.runtime_contract_walker_check",
    "onex:golden_chain_sweep",
    "onex:lean_seam_read",
)

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## The practice",
    "## When to use",
    "## Steps by hand today",
    "## Factory task per step",
)

# The two shapes omniclaude's hooks refuse in a skill: a remote shell line and
# a raw HTTP call. Prose skills call existing commands only.
FORBIDDEN_LINE = re.compile(r"(^|\s)ssh [^#]|(^|[^a-zA-Z])(curl |wget )")


def _split(text: str) -> tuple[dict[str, object], str]:
    assert text.startswith("---\n"), "no frontmatter"
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert isinstance(front, dict), "frontmatter is not a mapping"
    return front, text[end + 4 :]


def _problems(text: str) -> list[str]:
    front, body = _split(text)
    problems: list[str] = []
    if front.get("bootstrap") is not True:
        problems.append("frontmatter must declare bootstrap: true")
    if not str(front.get("description", "")).startswith("Bootstrap skill"):
        problems.append("description must start with 'Bootstrap skill'")
    if "This skill is a bootstrap skill." not in body:
        problems.append("body must say it is a bootstrap skill")
    if (
        "**Replaced by**" not in body
        or "`node_contract_seams_orchestrator`" not in body
    ):
        problems.append(
            "body must name node_contract_seams_orchestrator as its replacement"
        )
    problems.extend(
        f"section {section!r} is missing"
        for section in REQUIRED_SECTIONS
        if section not in body
    )
    positions = [body.find(title) for title in STEP_TITLES]
    problems.extend(
        f"step {title!r} is missing"
        for title, at in zip(STEP_TITLES, positions, strict=True)
        if at < 0
    )
    found = [at for at in positions if at >= 0]
    if found != sorted(found):
        problems.append("the six steps are out of order")
    problems.extend(
        f"step 5 does not name {command!r}"
        for command in PROOF_COMMANDS
        if command not in body
    )
    problems.extend(
        f"imperative line: {line.strip()!r}"
        for line in body.splitlines()
        if FORBIDDEN_LINE.search(line)
    )
    return problems


@pytest.mark.unit
def test_the_skill_has_the_six_steps_in_order_and_names_every_proof() -> None:
    problems = _problems(SKILL_MD.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_a_planted_skill_without_the_proof_step_is_refused() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.index(STEP_TITLES[4])
    end = text.index(STEP_TITLES[5])
    planted = text[:start] + text[end:]
    problems = _problems(planted)
    assert "step '5. **Prove that it connects.**' is missing" in problems
    assert any("ValidatorEventChainWalker" in p for p in problems)


@pytest.mark.unit
def test_the_skill_is_prose_only() -> None:
    assert sorted(p.name for p in SKILL_DIR.iterdir()) == ["SKILL.md"]


@pytest.mark.unit
def test_the_skill_is_assigned_in_the_distribution_manifest() -> None:
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    entry = {c["id"]: c for c in manifest["components"]}.get("lean_contract_seams")
    assert entry is not None
    assert entry["surface_class"] == "pure_skill"
    assert entry["backing_nodes"] == []
    assert "OMN-21627" in entry["rationale"]

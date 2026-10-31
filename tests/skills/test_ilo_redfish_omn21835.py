# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21835: ilo_redfish ships as a bootstrap skill over the iLO Redfish effect CLI.

The skill is read-only by default, requires a recorded approval naming the action and the host before
a write, says a repeat is never run blind, keeps Smart Array out of scope, and holds no credential,
address or ticket id. The planted example below is the skill text with the approval section removed;
the same checks must refuse it, so the shape test is not vacuous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path("plugins/onex/skills/ilo_redfish")
SKILL_MD = SKILL_DIR / "SKILL.md"

REQUIRED_SECTIONS: tuple[str, ...] = (
    "## What it does and does not do",
    "## Setup (the operator, once per host)",
    "## The command",
    "## Writes: approval first, then one run",
    "## Retries",
    "## Refusals you will see",
)
READ_VERBS = ("discover", "identity", "inventory", "health", "logs", "power-status")
WRITE_VERBS = ("power", "virtual-media", "boot-once")
FORBIDDEN_LINE = re.compile(r"(^|\s)ssh [^#]|(^|[^a-zA-Z])(curl |wget )")
IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
TICKET = re.compile(r"\bOMN-\d+\b")


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
    if "**Replaced by**" not in body or "`node_ilo_redfish_effect`" not in body:
        problems.append(
            "body must name node_ilo_redfish_effect as its replacement basis"
        )
    problems.extend(
        f"section {s!r} is missing" for s in REQUIRED_SECTIONS if s not in body
    )
    problems.extend(
        f"read verb {v!r} is not named" for v in READ_VERBS if f"`{v}`" not in body
    )
    problems.extend(
        f"write verb {v!r} is not named" for v in WRITE_VERBS if f"`{v}`" not in body
    )
    for needle, why in (
        ("`ssacli`", "Smart Array exclusion"),
        ("Smart Storage Administrator", "Smart Array exclusion"),
        ("OPERATOR-CONSENT", "approval record"),
        ("`ilo-redfish`", "approval scope words"),
        ("do not run it again", "retry rule"),
        ("Verification is never turned off", "TLS rule"),
        ("Login", "least-privilege read account"),
    ):
        if needle not in body:
            problems.append(f"missing {why}: {needle!r}")
    if IPV4.search(body):
        problems.append("an IP address is written in the skill")
    if TICKET.search(body):
        problems.append("a ticket id is written in the skill")
    problems.extend(
        f"imperative line: {line.strip()!r}"
        for line in body.splitlines()
        if FORBIDDEN_LINE.search(line)
    )
    return problems


@pytest.mark.unit
def test_the_skill_has_its_sections_verbs_and_safety_statements() -> None:
    problems = _problems(SKILL_MD.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_a_planted_skill_without_the_approval_section_is_refused() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    start = text.index("## Writes: approval first, then one run")
    end = text.index("## Retries")
    problems = _problems(text[:start] + text[end:])
    assert "section '## Writes: approval first, then one run' is missing" in problems


@pytest.mark.unit
def test_a_planted_skill_with_an_address_is_refused() -> None:
    text = SKILL_MD.read_text(encoding="utf-8") + "\nThe iLO is at 192.0.2.50.\n"
    assert "an IP address is written in the skill" in _problems(text)


@pytest.mark.unit
def test_the_skill_is_prose_only() -> None:
    assert sorted(p.name for p in SKILL_DIR.iterdir()) == ["SKILL.md"]


@pytest.mark.unit
def test_the_skill_is_assigned_in_the_distribution_manifest() -> None:
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    entry = {c["id"]: c for c in manifest["components"]}.get("ilo_redfish")
    assert entry is not None
    assert entry["surface_class"] == "pure_skill"
    assert entry["backing_nodes"] == []
    assert "OMN-21835" in entry["rationale"]

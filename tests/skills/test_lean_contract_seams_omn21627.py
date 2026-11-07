# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21627: lean_contract_seams is the dispatch shim of node_contract_seams_orchestrator.

The operator ruled (about 2026-10-31T02:25Z) that a design starts with its
contracts and seams, and that everything connects before any handler logic.
The bootstrap prose form of this skill is replaced by the node: these tests hold
the shim's shape. It names the backing node and its reducer, starts the node
through `onex run-node` only, names the request fields and the three end states,
holds no orchestration of its own (no script beside it, no remote shell line, no
direct import or `python -m` of an omnimarket node), and is assigned as a
dispatch skill backed by the node in the distribution manifest.

The planted example below is the skill text with the run-node line removed; the
same checks must refuse it, so the shape test is not vacuous.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path("plugins/onex/skills/lean_contract_seams")
SKILL_MD = SKILL_DIR / "SKILL.md"
NODE = "node_contract_seams_orchestrator"
RUN_NODE = f"onex run-node {NODE}"

REQUIRED_NAMES: tuple[str, ...] = (
    f"`{NODE}`",
    "`node_contract_seams_reducer`",
    '"correlation_id"',
    '"output_root"',
    '"design"',
    "`connected`",
    "`refused`",
    "`failed`",
    "`refused_by`",
    "mismatching_field_path",
)

# A shim dispatches and nothing else: no remote shell, no raw HTTP, no direct
# import or module run of an omnimarket node, no bootstrap marker left behind.
FORBIDDEN_LINE = re.compile(
    r"(^|\s)ssh [^#]|(^|[^a-zA-Z])(curl |wget )|python(3)? -m omnimarket\.nodes\."
    r"|from omnimarket\.nodes"
)


def _split(text: str) -> tuple[dict[str, object], str]:
    assert text.startswith("---\n"), "no frontmatter"
    end = text.find("\n---", 4)
    front = yaml.safe_load(text[4:end])
    assert isinstance(front, dict), "frontmatter is not a mapping"
    return front, text[end + 4 :]


def _problems(text: str) -> list[str]:
    front, body = _split(text)
    problems: list[str] = []
    if "bootstrap" in front:
        problems.append("a dispatch shim declares no bootstrap key")
    if not str(front.get("description", "")).startswith("Thin dispatch shim"):
        problems.append("description must start with 'Thin dispatch shim'")
    if RUN_NODE not in body:
        problems.append(f"body must start the node with {RUN_NODE!r}")
    problems.extend(
        f"body does not name {name}" for name in REQUIRED_NAMES if name not in body
    )
    problems.extend(
        f"forbidden line: {line.strip()!r}"
        for line in body.splitlines()
        if FORBIDDEN_LINE.search(line)
    )
    return problems


@pytest.mark.unit
def test_the_shim_starts_the_node_and_names_its_request_and_end_states() -> None:
    problems = _problems(SKILL_MD.read_text(encoding="utf-8"))
    assert not problems, "\n".join(problems)


@pytest.mark.unit
def test_a_planted_shim_without_the_run_node_line_is_refused() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    planted = text.replace(RUN_NODE, "onex run-node node_something_else")
    assert f"body must start the node with {RUN_NODE!r}" in _problems(planted)


@pytest.mark.unit
def test_a_planted_shim_that_runs_the_node_module_directly_is_refused() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    planted = text + f"\npython -m omnimarket.nodes.{NODE} --design d.yaml\n"
    assert any(p.startswith("forbidden line:") for p in _problems(planted))


@pytest.mark.unit
def test_the_shim_is_one_file() -> None:
    assert sorted(p.name for p in SKILL_DIR.iterdir()) == ["SKILL.md"]


@pytest.mark.unit
def test_the_shim_is_a_dispatch_skill_backed_by_the_node() -> None:
    manifest = yaml.safe_load(Path("plugins/distribution_manifest.yaml").read_text())
    entry = {c["id"]: c for c in manifest["components"]}.get("lean_contract_seams")
    assert entry is not None
    assert entry["surface_class"] == "dispatch"
    assert entry["backing_nodes"] == [NODE]
    assert "OMN-21627" in entry["rationale"]

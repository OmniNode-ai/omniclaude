# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18368 — the node scaffolder skips prose skills, and only prose skills.

A ``skill_kind: methodology`` skill describes a method over a workflow that
already exists. Nothing dispatches a start command to it, so scaffolding a shell
orchestrator produces a node with no ``handle()`` that nothing calls — the
green-by-parts, dead-in-fact shape — and the canonical handler-shape ratchet
rejects it because a new node must be born canonical.

The skip must read the FRONTMATTER, not the file. A skill body that discusses
methodology skills must still get its node.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = REPO_ROOT / "scripts" / "auto_generate_skill_nodes.py"

_spec = importlib.util.spec_from_file_location(
    "_auto_generate_skill_nodes", _MODULE_PATH
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)


def _write(tmp_path: Path, frontmatter: str, body: str = "") -> Path:
    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(f"---\n{frontmatter}\n---\n\n{body}", encoding="utf-8")
    return skill_md


@pytest.mark.unit
def test_methodology_in_frontmatter_is_skipped(tmp_path: Path) -> None:
    assert _mod._is_methodology(
        _write(tmp_path, "description: x\nskill_kind: methodology")
    )


@pytest.mark.unit
def test_dispatch_in_frontmatter_is_not_skipped(tmp_path: Path) -> None:
    assert not _mod._is_methodology(
        _write(tmp_path, "description: x\nskill_kind: dispatch")
    )


@pytest.mark.unit
def test_absent_skill_kind_is_not_skipped(tmp_path: Path) -> None:
    assert not _mod._is_methodology(_write(tmp_path, "description: x"))


@pytest.mark.unit
def test_body_prose_cannot_suppress_generation(tmp_path: Path) -> None:
    """The negative control: the phrase in the body is not a classification."""
    assert not _mod._is_methodology(
        _write(
            tmp_path,
            "description: x\nskill_kind: dispatch",
            body="A sibling skill declares\nskill_kind: methodology\nand is skipped.\n",
        )
    )


@pytest.mark.unit
def test_live_tree_agrees_with_the_classification() -> None:
    """Positive control over the real skill tree, both directions."""
    skills_root = REPO_ROOT / "plugins" / "onex" / "skills"
    methodology = {
        d.name
        for d in skills_root.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "SKILL.md").is_file()
        and _mod._is_methodology(d / "SKILL.md")
    }
    assert methodology, "no methodology skill resolved; the reader is broken"
    assert "merge_sweep" not in methodology, "a dispatch skill classified as prose"

    # No methodology skill introduced by this change carries a scaffolded shell.
    nodes_root = REPO_ROOT / "src" / "omniclaude" / "nodes"
    introduced = {
        "board_readback",
        "comment_sweep",
        "lane_dispatch",
        "overseer_verify_tick",
        "plans_board_refresh",
    }
    assert introduced <= methodology
    for name in sorted(introduced):
        node_dir = nodes_root / f"node_skill_{name}_orchestrator"
        assert not node_dir.exists(), (
            f"{node_dir.name} exists; a prose skill acquired a shell orchestrator"
        )

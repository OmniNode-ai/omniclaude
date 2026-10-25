# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The closeout instruction audit must distinguish clean, stale and unreadable."""

from pathlib import Path

import pytest

from omniclaude.nodes.node_linear_effect.handlers.handler_done_closeout_instructions import (
    findings,
)

pytestmark = pytest.mark.unit


def test_retired_closeout_instruction_is_refused(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text("Flip Done on ticked boxes plus a dod_evidence comment.\n")
    assert findings([tmp_path]) == [
        f"{skill}:1: retired closeout instruction; require a fresh bound PASS receipt"
    ]


def test_fresh_bound_receipt_instruction_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "SKILL.md").write_text(
        "Only a fresh PASS receipt bound to every criterion permits Done.\n"
    )
    assert findings([tmp_path]) == []


def test_absent_instruction_root_is_not_a_clean_audit(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    assert findings([root]) == [
        f"{root}: instruction root is missing or not a directory"
    ]


def test_shipped_skill_instructions_have_no_retired_closeout_path() -> None:
    assert findings([Path(__file__).resolve().parents[2] / "plugins/onex/skills"]) == []

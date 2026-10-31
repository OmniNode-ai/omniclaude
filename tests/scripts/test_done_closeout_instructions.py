# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The closeout instruction audit must distinguish clean, stale and unreadable."""

from pathlib import Path

import pytest

from omniclaude.nodes.node_linear_effect.handlers.handler_done_closeout_instructions import (
    HandlerDoneCloseoutInstructions,
)
from omniclaude.nodes.node_linear_effect.models import (
    ModelCloseoutInstructionAuditRequest,
)
from omniclaude.nodes.node_linear_effect.runtime_done_closeout_instructions import (
    main,
)

pytestmark = pytest.mark.unit


def findings(roots: list[Path]) -> list[str]:
    result = HandlerDoneCloseoutInstructions().handle(
        ModelCloseoutInstructionAuditRequest(roots=tuple(roots))
    )
    return list(result.findings)


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


def test_runtime_entry_exits_1_on_a_stale_root_and_0_on_a_clean_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "SKILL.md").write_text("Only a fresh PASS receipt permits Done.\n")
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / "SKILL.md").write_text("Flip Done on a dod_evidence comment.\n")

    monkeypatch.setattr("sys.argv", ["runtime", str(clean)])
    assert main() == 0
    assert "PASS" in capsys.readouterr().out

    monkeypatch.setattr("sys.argv", ["runtime", str(stale)])
    assert main() == 1
    assert "retired closeout instruction" in capsys.readouterr().out


def test_module_function_audit_is_a_handler_class() -> None:
    import omniclaude.nodes.node_linear_effect.handlers.handler_done_closeout_instructions as module

    assert not hasattr(module, "findings")
    assert not hasattr(module, "main")

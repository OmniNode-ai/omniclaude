# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for OMN-9075 skill aspiration validation."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from plugins.onex.skills._lib.validate_skill_aspiration import (
    EnumSkillClaimKind,
    extract_claims_from_skill,
    scan,
)

if TYPE_CHECKING:
    import pytest


def _write_skill(repo: Path, name: str, body: str) -> Path:
    skill_dir = repo / "plugins" / "onex" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(textwrap.dedent(body), encoding="utf-8")
    return skill_md


def _write_node(
    omnimarket_root: Path,
    node_name: str,
    *,
    contract: str = "name: node\nterminal_event: onex.evt.test.done.v1\n",
    handler: str,
) -> Path:
    node_dir = omnimarket_root / "src" / "omnimarket" / "nodes" / node_name
    handlers_dir = node_dir / "handlers"
    handlers_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "contract.yaml").write_text(contract, encoding="utf-8")
    (handlers_dir / f"handler_{node_name}.py").write_text(
        textwrap.dedent(handler), encoding="utf-8"
    )
    return node_dir


def test_extracts_receipt_claim_from_behavior_section(tmp_path: Path) -> None:
    skill_md = _write_skill(
        tmp_path,
        "dod_verify",
        """\
        # dod-verify

        ## Behavior

        Thin skill dispatches to `node_dod_verify`.
        - Writes the evidence receipt to `.evidence/{ticket_id}/dod_report.json`
        """,
    )

    claims = extract_claims_from_skill(skill_md)

    assert len(claims) == 1
    assert claims[0].skill_name == "dod_verify"
    assert claims[0].node_name == "node_dod_verify"
    assert claims[0].kind is EnumSkillClaimKind.RECEIPT
    assert claims[0].side_effect == ".evidence/{ticket_id}/dod_report.json"


def test_scan_accepts_claim_when_node_writes_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    omnimarket_root = tmp_path / "omnimarket"
    _write_skill(
        tmp_path,
        "dod_verify",
        """\
        # dod-verify

        ## Behavior

        Dispatches to `node_dod_verify`.
        - Writes the evidence receipt to `.evidence/{ticket_id}/dod_report.json`
        """,
    )
    _write_node(
        omnimarket_root,
        "node_dod_verify",
        handler="""\
        from pathlib import Path

        def handle(ticket_id: str) -> None:
            receipt = Path(".evidence") / ticket_id / "dod_report.json"
            receipt.parent.mkdir(parents=True, exist_ok=True)
            receipt.write_text("{}", encoding="utf-8")
        """,
    )
    monkeypatch.setenv("OMNIMARKET_ROOT", str(omnimarket_root))

    assert scan(tmp_path) == []


def test_scan_rejects_receipt_claim_without_write_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    omnimarket_root = tmp_path / "omnimarket"
    _write_skill(
        tmp_path,
        "dod_verify",
        """\
        # dod-verify

        ## Behavior

        Dispatches to `node_dod_verify`.
        - Writes the evidence receipt to `.evidence/{ticket_id}/dod_report.json`
        """,
    )
    _write_node(
        omnimarket_root,
        "node_dod_verify",
        handler="""\
        def handle(ticket_id: str) -> dict[str, object]:
            return {"ticket_id": ticket_id, "success": True}
        """,
    )
    monkeypatch.setenv("OMNIMARKET_ROOT", str(omnimarket_root))

    violations = scan(tmp_path)

    assert len(violations) == 1
    assert "claimed receipt/artifact side effect" in violations[0]
    assert "dod_report.json" in violations[0]


def test_scan_accepts_terminal_event_claim_when_contract_declares_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    omnimarket_root = tmp_path / "omnimarket"
    _write_skill(
        tmp_path,
        "session",
        """\
        # session

        ## Outputs

        Dispatches to `node_session_orchestrator`.
        - Emits terminal event `onex.evt.omnimarket.session-orchestrator-completed.v1`
        """,
    )
    _write_node(
        omnimarket_root,
        "node_session_orchestrator",
        contract="name: session\nterminal_event: onex.evt.omnimarket.session-orchestrator-completed.v1\n",
        handler="""\
        def handle() -> dict[str, str]:
            return {"status": "complete"}
        """,
    )
    monkeypatch.setenv("OMNIMARKET_ROOT", str(omnimarket_root))

    assert scan(tmp_path) == []

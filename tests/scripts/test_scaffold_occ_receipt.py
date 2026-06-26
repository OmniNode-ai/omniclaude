# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the tool-generated OCC receipt scaffold (OMN-13050, retro D-4).

OCC PR #2530 wedged four ways with hand-authored receipts. This tool makes the
receipt-creation path tool-generated so each of those four wedges is either
*structurally unrepresentable* (the tool always emits the field) or
*self-reporting* (the tool flags it). The four wedges, mapped to the proofs
below:

  W1 - missing ``contract_sha256``  -> structurally unrepresentable: every
       generated receipt records the prefixed contract hash, validated against
       ``ModelDodReceipt`` and re-checked against the contract bytes.
  W2 - base == ``main`` (dev-only promotion violation) -> the tool defaults
       ``--base dev`` mechanically and self-reports a wedge if ``main`` is
       requested without the promotion-branch override.
  W3 - bracketed ``[skip-*: ...]`` bypass token with self-written justification
       -> the tool scans every text input and self-reports a wedge; it never
       emits the token.
  W4 - armed blind (no ``gh pr checks`` watch) -> the tool emits the gated arm
       command paired with its failure-mode + alternative and self-reports a
       wedge until watch evidence is supplied.

The receipt model + ``compute_contract_sha256`` are provided by the installed
``omnibase_core``. When the pinned release predates those exports (local dev
venv), the import-dependent assertions are skipped; CI clones
``omnibase_core@dev`` which carries them.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

_TOOL_MODULE = "scripts.scaffold_occ_receipt"

_core_available = (
    importlib.util.find_spec("omnibase_core.validation.validator_receipt_gate")
    is not None
)
_requires_core = pytest.mark.skipif(
    not _core_available,
    reason="omnibase_core receipt-gate validator not installed (pinned release predates OMN-10421)",
)


def _import_tool():
    import importlib

    return importlib.import_module(_TOOL_MODULE)


def _write_contract(tmp_path: Path, ticket_id: str = "OMN-9999") -> Path:
    contract_dir = tmp_path / "contracts"
    contract_dir.mkdir(parents=True, exist_ok=True)
    contract_path = contract_dir / f"{ticket_id}.yaml"
    contract_path.write_text(
        "schema_version: '1.0.0'\n"
        f"ticket_id: '{ticket_id}'\n"
        "title: 'demo'\n"
        "summary: 'demo'\n"
        "is_seam_ticket: false\n"
        "interface_change: false\n"
        "dod_evidence:\n"
        "  - id: dod-001\n"
        "    description: 'tests pass'\n"
        "    checks:\n"
        "      - check_type: command\n"
        "        check_value: 'uv run pytest tests/ -v'\n",
        encoding="utf-8",
    )
    return contract_path


# ----------------------------------------------------------------------- #
# Tool exists and is importable                                           #
# ----------------------------------------------------------------------- #


def test_tool_module_importable() -> None:
    """The scaffold tool module exists and exposes build_receipt + main."""
    tool = _import_tool()
    assert hasattr(tool, "build_receipt"), "tool must expose build_receipt()"
    assert hasattr(tool, "detect_wedges"), "tool must expose detect_wedges()"
    assert hasattr(tool, "main"), "tool must expose a CLI main()"


def test_default_base_is_dev() -> None:
    """W2 mechanical default: --base defaults to dev (never main)."""
    tool = _import_tool()
    parser = tool.build_arg_parser()
    args = parser.parse_args(["OMN-9999", "--pr-number", "1", "--commit-sha", "a" * 40])
    assert args.base == "dev", "base must mechanically default to dev"


# ----------------------------------------------------------------------- #
# W1 - contract_sha256 structurally unrepresentable as missing            #
# ----------------------------------------------------------------------- #


@_requires_core
def test_receipt_always_emits_contract_sha256(tmp_path: Path) -> None:
    """W1: every generated receipt records the prefixed contract hash."""
    tool = _import_tool()
    from omnibase_core.validation.validator_receipt_gate import (
        _prefixed_contract_sha256,
    )

    contract_path = _write_contract(tmp_path)
    receipt = tool.build_receipt(
        ticket_id="OMN-9999",
        evidence_item_id="dod-occ-pr-1",
        contract_path=contract_path,
        pr_number=1,
        commit_sha="a" * 40,
        base="dev",
        runner="codex",
        verifier="codex-receipt-review-omn-9999",
        probe_command="gh pr view 1 --json number,state",
        probe_stdout='{"number": 1, "state": "OPEN"}',
        actual_output="PASS: receipt scaffolded.",
        branch="jonah/omn-9999-x",
    )
    assert receipt["contract_sha256"] == _prefixed_contract_sha256(contract_path)
    assert receipt["contract_sha256"].startswith("sha256:")


@_requires_core
def test_receipt_validates_against_model(tmp_path: Path) -> None:
    """W1: the emitted dict is a structurally valid ModelDodReceipt."""
    tool = _import_tool()
    from omnibase_core.models.contracts.ticket.model_dod_receipt import (
        ModelDodReceipt,
    )

    contract_path = _write_contract(tmp_path)
    receipt = tool.build_receipt(
        ticket_id="OMN-9999",
        evidence_item_id="dod-occ-pr-1",
        contract_path=contract_path,
        pr_number=1,
        commit_sha="a" * 40,
        base="dev",
        runner="codex",
        verifier="codex-receipt-review-omn-9999",
        probe_command="gh pr view 1 --json number,state",
        probe_stdout='{"number": 1, "state": "OPEN"}',
        actual_output="PASS: receipt scaffolded.",
        branch="jonah/omn-9999-x",
    )
    model = ModelDodReceipt.model_validate(receipt)
    assert model.contract_sha256 is not None
    assert model.contract_sha256.startswith("sha256:")


@_requires_core
def test_receipt_sha_matches_receipt_gate_recompute(tmp_path: Path) -> None:
    """W1: the recorded hash equals what the receipt-gate validator recomputes."""
    tool = _import_tool()
    from omnibase_core.validation.validator_receipt_gate import (
        _prefixed_contract_sha256,
    )

    contract_path = _write_contract(tmp_path)
    receipt = tool.build_receipt(
        ticket_id="OMN-9999",
        evidence_item_id="dod-occ-pr-1",
        contract_path=contract_path,
        pr_number=1,
        commit_sha="b" * 40,
        base="dev",
        runner="codex",
        verifier="codex-receipt-review-omn-9999",
        probe_command="gh pr view 1 --json number,state",
        probe_stdout='{"number": 1, "state": "OPEN"}',
        actual_output="PASS: receipt scaffolded.",
        branch="jonah/omn-9999-x",
    )
    assert receipt["contract_sha256"] == _prefixed_contract_sha256(contract_path)


def test_build_receipt_requires_contract_path(tmp_path: Path) -> None:
    """W1: a missing contract file is a hard error - no sha-less receipt."""
    tool = _import_tool()
    missing = tmp_path / "contracts" / "OMN-9999.yaml"
    with pytest.raises((FileNotFoundError, SystemExit, ValueError)):
        tool.build_receipt(
            ticket_id="OMN-9999",
            evidence_item_id="dod-occ-pr-1",
            contract_path=missing,
            pr_number=1,
            commit_sha="a" * 40,
            base="dev",
            runner="codex",
            verifier="v-omn-9999",
            probe_command="gh pr view 1",
            probe_stdout="{}",
            actual_output="PASS",
            branch="b",
        )


# ----------------------------------------------------------------------- #
# W2 - base == main self-reported                                         #
# ----------------------------------------------------------------------- #


def test_base_main_is_flagged_wedge() -> None:
    """W2: base=main without promotion override self-reports a wedge."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="main",
        is_promotion=False,
        texts=["benign body with no bypass token"],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "base_not_dev" in codes


def test_base_dev_no_wedge() -> None:
    """W2: the mechanical default (dev) does not self-report a base wedge."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=["benign body with no bypass token"],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "base_not_dev" not in codes


def test_base_main_promotion_allowed() -> None:
    """W2: base=main IS allowed when the head is the promotion branch."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="main",
        is_promotion=True,
        texts=["promotion body"],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "base_not_dev" not in codes


# ----------------------------------------------------------------------- #
# W3 - bracketed skip-token self-reported, never emitted                  #
# ----------------------------------------------------------------------- #


def test_skip_token_in_body_is_flagged_wedge() -> None:
    """W3: a real bracketed skip token in any input self-reports a wedge."""
    tool = _import_tool()
    body = "Implements OMN-9999. [skip-receipt-gate: my change is non-deployable]"
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=[body],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "skip_token_present" in codes


def test_skip_deploy_gate_token_is_flagged() -> None:
    """W3: the [skip-deploy-gate: ...] family is also caught."""
    tool = _import_tool()
    body = "[skip-deploy-gate: non-runtime]"
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=[body],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "skip_token_present" in codes


def test_angle_bracket_placeholder_not_flagged() -> None:
    """W3: a docs placeholder [skip-receipt-gate: <token>] is not a real token."""
    tool = _import_tool()
    body = "Use [skip-receipt-gate: <user-approval-receipt-id>] only for ticketless changes."
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=[body],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "skip_token_present" not in codes


# ----------------------------------------------------------------------- #
# W4 - armed-blind self-reported                                          #
# ----------------------------------------------------------------------- #


def test_unconfirmed_ci_watch_is_flagged_wedge() -> None:
    """W4: arming before confirming gh pr checks self-reports a wedge."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=["clean body"],
        ci_watch_confirmed=False,
    )
    codes = {w.code for w in wedges}
    assert "ci_watch_unconfirmed" in codes


def test_confirmed_ci_watch_no_wedge() -> None:
    """W4: confirmed watch evidence clears the armed-blind wedge."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=["clean body"],
        ci_watch_confirmed=True,
    )
    codes = {w.code for w in wedges}
    assert "ci_watch_unconfirmed" not in codes


# ----------------------------------------------------------------------- #
# Every wedge carries a failure-mode + alternative (negative-directive)   #
# ----------------------------------------------------------------------- #


def test_each_wedge_pairs_failure_mode_and_alternative() -> None:
    """Every self-reported wedge states what breaks AND what to do instead."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="main",
        is_promotion=False,
        texts=["[skip-receipt-gate: nope]"],
        ci_watch_confirmed=False,
    )
    assert wedges, "expected wedges for a fully-broken invocation"
    for w in wedges:
        assert w.failure_mode and w.failure_mode.strip(), (
            f"{w.code} missing failure_mode"
        )
        assert w.alternative and w.alternative.strip(), f"{w.code} missing alternative"


def test_clean_invocation_reports_no_wedges() -> None:
    """A clean dev-targeted, token-free, watch-confirmed call self-reports clean."""
    tool = _import_tool()
    wedges = tool.detect_wedges(
        base="dev",
        is_promotion=False,
        texts=[
            "Implements OMN-9999. Evidence-Source: OCC#1. Evidence-Ticket: OMN-9999"
        ],
        ci_watch_confirmed=True,
    )
    assert wedges == []

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20132 - the Receipt Gate caller pin must resolve a validator that knows tree_sha.

``call-receipt-gate.yml`` pins omnibase_core's ``receipt-gate.yml`` at a sha.
That file carries a second, inner ref that supplies the validator source.
ModelDodReceipt forbids extra fields, so an inner ref that predates
``tree_sha`` (omnibase_core#1748) fails every current receipt with
``extra_forbidden``. This test follows the chain: caller pin, then the inner
validator ref at that pin, then ModelDodReceipt at the inner ref.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-receipt-gate.yml"
CORE = "OmniNode-ai/omnibase_core"
GATE_PATH = ".github/workflows/receipt-gate.yml"
MODEL_PATH = "src/omnibase_core/models/contracts/ticket/model_dod_receipt.py"
CHECKOUT_PATH = ".receipt-gate-deps/omnibase_core"
REQUIRED_RECEIPT_FIELDS = frozenset({"tree_sha"})

# Pins whose inner validator ref predates tree_sha (omnibase_core#1814 moved it).
STALE_CALLER_PINS = frozenset(
    {
        "e12c36249d550204354f1d99428841ee99a89868",  # pragma: allowlist secret
        "9cc9f035465266442df542d345cde621c9c3b0d5",  # pragma: allowlist secret
    }
)
OLD_INNER_REF = "a03b10720db364575b0477003da95b46de765950"  # pragma: allowlist secret


def _caller_pin() -> str:
    data = yaml.safe_load(CALLER_PATH.read_text())
    refs = [
        str(job["uses"]).split("@", 1)[1]
        for job in data["jobs"].values()
        if str(job.get("uses", "")).startswith(f"{CORE}/{GATE_PATH}@")
    ]
    assert len(refs) == 1, f"expected exactly one receipt-gate caller, got {refs}"
    return refs[0]


def _fetch_core_file(ref: str, path: str) -> str:
    url = f"https://api.github.com/repos/{CORE}/contents/{path}?ref={ref}"
    try:
        done = subprocess.run(
            ["gh", "api", url, "-H", "Accept: application/vnd.github.raw"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        done = None
    if done is None or done.returncode != 0:
        pytest.skip(f"omnibase_core {path}@{ref} is not readable from this environment")
    return done.stdout


def _inner_validator_ref(gate_yaml: str) -> str:
    data = yaml.safe_load(gate_yaml)
    refs: list[str] = []
    for job in data["jobs"].values():
        for step in job.get("steps", []):
            with_block = step.get("with") or {}
            if with_block.get("path") == CHECKOUT_PATH:
                refs.append(str(with_block["ref"]))
    assert len(refs) == 1, f"expected exactly one validator checkout, got {refs}"
    return refs[0]


def _model_fields(source: str) -> set[str]:
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == "ModelDodReceipt":
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    raise AssertionError("ModelDodReceipt not found at the validator ref")


def test_caller_pin_is_an_immutable_full_sha() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", _caller_pin())


def test_caller_pin_is_not_a_known_stale_pin() -> None:
    assert _caller_pin() not in STALE_CALLER_PINS


def test_pinned_workflow_inner_validator_accepts_tree_sha() -> None:
    pin = _caller_pin()
    inner = _inner_validator_ref(_fetch_core_file(pin, GATE_PATH))
    assert inner != OLD_INNER_REF
    missing = REQUIRED_RECEIPT_FIELDS - _model_fields(
        _fetch_core_file(inner, MODEL_PATH)
    )
    assert not missing, (
        f"call-receipt-gate.yml pins receipt-gate.yml at {pin}, whose inner validator "
        f"ref {inner} has a ModelDodReceipt lacking {sorted(missing)}; a receipt "
        "carrying them fails verify with extra_forbidden. Advance this pin."
    )


def test_floor_rejects_the_pre_tree_sha_inner_ref() -> None:
    """Positive control: the old inner ref is below the floor."""
    fields = _model_fields(_fetch_core_file(OLD_INNER_REF, MODEL_PATH))
    assert REQUIRED_RECEIPT_FIELDS - fields

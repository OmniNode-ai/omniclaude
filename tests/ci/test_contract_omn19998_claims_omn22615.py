# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The shared OMN-19998 contract claims no criterion its live ticket lacks (OMN-22615).

The live ticket carries AC1 to AC3. The criteria-drift check reads every other label a
dod_evidence item binds as a deleted criterion unless a supersedes_ac_binding entry retires
that (item, label) pair, and the landing controller defers pull requests touching the contract
while one is left.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

LIVE_LABELS = frozenset({"AC1", "AC2", "AC3"})
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "OMN-19998.yaml"


def unretired_foreign_claims(contract: Mapping[str, Any]) -> list[tuple[str, str]]:
    """(item id, label) pairs bound to a label the live ticket lacks and no entry retires."""
    items: Sequence[Mapping[str, Any]] = contract.get("dod_evidence") or []
    retired = {
        (str(entry["item"]), str(entry["label"]))
        for item in items
        for entry in item.get("supersedes_ac_binding") or []
    }
    return [
        (str(item["id"]), str(label))
        for item in items
        for label in item.get("binds_ac") or []
        if str(label) not in LIVE_LABELS
        and (str(item["id"]), str(label)) not in retired
    ]


def test_the_shared_contract_claims_no_label_the_live_ticket_lacks() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert unretired_foreign_claims(contract) == []


def test_a_contract_with_an_ac16_claim_is_read_as_holding_one() -> None:
    contract = {
        "dod_evidence": [
            {"id": "item-a", "binds_ac": ["AC1"]},
            {"id": "item-b", "binds_ac": ["AC16"]},
            {
                "id": "retirer",
                "supersedes_ac_binding": [{"item": "item-c", "label": "AC19"}],
            },
            {"id": "item-c", "binds_ac": ["AC19"]},
        ]
    }
    assert unretired_foreign_claims(contract) == [("item-b", "AC16")]


OWN_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "OMN-22615.yaml"
MOVED_IDS = {
    "dod-omn19998-worktree-guard-bare-interpreter",
    "dod-omn19998-worktree-guard-source-readback",
}


def _ids(path: Path) -> set[str]:
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {str(item["id"]) for item in contract.get("dod_evidence") or []}


def test_the_moved_worktree_guard_items_live_only_in_the_own_contract() -> None:
    assert _ids(OWN_CONTRACT) >= MOVED_IDS
    assert not MOVED_IDS & _ids(CONTRACT)

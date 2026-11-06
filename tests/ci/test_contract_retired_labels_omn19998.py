# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: no acceptance criterion is declared under a label the contract retired.

``contracts/OMN-19998.yaml`` declared AC4 to AC20 that the live ticket never carried, so
``node_dod_criteria_check_effect`` held every pull request citing the ticket with
CRITERIA_DRIFT. The contract retires those labels through typed ``supersedes_ac_binding``
entries and keeps their checks running under one carrier item. This pins that state: a retired
label that comes back as an acceptance criterion, or a new criterion the ticket does not carry,
fails here instead of at the drift check on the next pull request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "OMN-19998.yaml"
KEPT = {"AC1", "AC2", "AC3"}
RETIRED = {
    "AC4",
    "AC5",
    "AC6",
    "AC7",
    "AC8",
    "AC9",
    "AC10",
    "AC11",
    "AC12",
    "AC13",
    "AC14",
    "AC15",
    "AC18",
    "AC19",
    "AC20",
}


def retired_labels(contract: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    for item in contract.get("dod_evidence", []):
        for entry in item.get("supersedes_ac_binding", []):
            if entry.get("reason_kind") == "no_longer_applicable":
                labels.add(str(entry["label"]).upper())
    return labels


def declared_labels(contract: dict[str, Any]) -> set[str]:
    return {
        str(criterion["id"]).upper()
        for requirement in contract.get("requirements", [])
        for criterion in requirement.get("acceptance", [])
    }


def test_the_contract_retires_the_contract_only_labels_and_still_declares_ac1_to_ac3() -> (
    None
):
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert retired_labels(contract) >= RETIRED
    declared = declared_labels(contract)
    assert declared == KEPT
    assert not declared & retired_labels(contract)


def test_every_retired_label_names_the_item_that_bound_it() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    items = {item["id"]: item for item in contract["dod_evidence"]}
    for item in contract["dod_evidence"]:
        for entry in item.get("supersedes_ac_binding", []):
            assert entry["item"] in items, entry["item"]
            assert entry["label"] in (items[entry["item"]].get("binds_ac") or []), entry


def test_control_a_contract_declaring_a_retired_label_is_caught() -> None:
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    contract["requirements"][0]["acceptance"].append(
        {"id": "AC4", "statement": "AC4: back again -- falsifier: none"}
    )
    assert declared_labels(contract) & retired_labels(contract) == {"AC4"}

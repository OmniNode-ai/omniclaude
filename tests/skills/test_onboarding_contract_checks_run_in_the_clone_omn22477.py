# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22477: the ticket's evidence checks run their tests from the omniclaude clone.

The evidence sweep runs a contract check from its own directory, not from the
repository, so a check whose cwd is "." finds no test file (OMN-22477's four
pytest checks failed with "file or directory not found") or is refused outright
("cwd escapes OMNI_HOME containment: '.' resolved to ...", seen on OMN-21627).
Every check in contracts/OMN-22477.yaml that runs pytest must name the clone,
${OMNI_HOME}/omniclaude, as its cwd.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "OMN-22477.yaml"
CLONE_CWD = "${OMNI_HOME}/omniclaude"


def _pytest_checks() -> list[tuple[str, dict[str, str]]]:
    with CONTRACT.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return [
        (item["id"], check)
        for item in data["dod_evidence"]
        for check in item["checks"]
        if "pytest" in str(check.get("check_value", ""))
    ]


def test_the_contract_has_pytest_checks() -> None:
    """The contract contains at least four pytest checks."""
    assert len(_pytest_checks()) >= 4


def test_every_pytest_check_runs_in_the_clone() -> None:
    """Every pytest check names the omniclaude clone as its cwd."""
    wrong = [
        evidence_id
        for evidence_id, check in _pytest_checks()
        if check.get("cwd") != CLONE_CWD
    ]
    assert wrong == [], wrong

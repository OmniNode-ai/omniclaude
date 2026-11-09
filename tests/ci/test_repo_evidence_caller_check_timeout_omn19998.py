# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The repo-evidence caller raises the per-check ceiling above the verifier's 30 s (OMN-19998).

The receipt-gate reusable keeps the verifier's own 30 s per-check ceiling unless the
caller passes ``check-timeout-seconds``. A bound ``uv run pytest`` check that runs
past it is skipped ``CHECK_BUDGET_EXCEEDED`` and repo-evidence / dod-verify reads
red with no failing test (omniclaude#3229: 32 to 36 s against 30 s). The caller is
read from the base branch, so the value has to be on ``dev`` before a pull request
can use it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CALLER_PATH = REPO_ROOT / ".github" / "workflows" / "call-repo-evidence-gate.yml"

# The verifier's own ceiling when the caller passes nothing.
VERIFIER_DEFAULT_CEILING_S = 30
# The lowest ceiling a fleet caller passes (omnibase_infra); omnimarket passes 300.
FLEET_FLOOR_CEILING_S = 180
# The reusable refuses a value outside 1 to 900.
REUSABLE_MAX_CEILING_S = 900
_REUSABLE_VALUE = re.compile(r"[1-9][0-9]{0,2}")


def _passed_ceiling() -> str:
    data = yaml.safe_load(CALLER_PATH.read_text(encoding="utf-8"))
    value = data["jobs"]["repo-evidence"]["with"].get("check-timeout-seconds", "")
    assert isinstance(value, str), "the reusable's input is a string; quote the value"
    return value


def test_caller_passes_a_check_timeout() -> None:
    assert _passed_ceiling() != "", (
        "check-timeout-seconds is empty: the verifier keeps 30 s"
    )


def test_ceiling_is_a_value_the_reusable_accepts() -> None:
    value = _passed_ceiling()
    assert _REUSABLE_VALUE.fullmatch(value), value
    assert 1 <= int(value) <= REUSABLE_MAX_CEILING_S


def test_ceiling_clears_the_fleet_floor() -> None:
    assert int(_passed_ceiling()) >= FLEET_FLOOR_CEILING_S


def test_floor_control_rejects_the_verifier_default() -> None:
    # Positive control: the verifier's own ceiling sits below the floor, so the
    # check above can fail.
    assert VERIFIER_DEFAULT_CEILING_S < FLEET_FLOOR_CEILING_S

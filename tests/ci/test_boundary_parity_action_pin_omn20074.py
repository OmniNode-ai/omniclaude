# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074: Cross-Repo Boundary Parity runs a manifest with no OCC boundary.

omnibase_core#1972 (c1f8e8fe0c) dropped the one boundary whose producer is
onex_change_control from the packaged kafka manifest. Every earlier sha of the
validate-boundaries action still carries it, so once onex_change_control leaves
the cloned peer set the parity handler exits 1 with "producer file missing".
The ci.yml pin must not be one of those earlier shas.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

_PIN = re.compile(
    r"OmniNode-ai/omnibase_core/\.github/actions/validate-boundaries@([0-9a-f]{40})"
)

# validate-boundaries pins this repo has carried that predate omnibase_core#1972.
_PRE_1972_PINS = frozenset(
    {
        "de3398d1fcf7a6f48451f680b74b1a6c6c383b8a",
        "b05c7d6f6336659d4965123bbc78a5d5b8822d70",
    }
)


def test_boundary_parity_action_pin_carries_the_manifest_without_occ() -> None:
    pins = _PIN.findall(CI_YML.read_text(encoding="utf-8"))
    assert pins, "ci.yml no longer runs the validate-boundaries action"
    stale = sorted(set(pins) & _PRE_1972_PINS)
    assert not stale, (
        f"validate-boundaries pinned at {stale}, which predates omnibase_core#1972 "
        "and still lists the onex_change_control boundary"
    )

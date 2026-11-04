# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22183: the onboarding guide states the rule the drift guard enforces.

The guard (omnibase_infra ``omnimarket_drift_guard``) accepts a canonical clone
detached at the commit the floor marker names and refuses one detached anywhere
else. Its tests pin the rule in ``rule`` of the recorded fixture; this module
pins the same fixture against the guide, so neither side can change the rule
alone. The fixture is spelled in this repository, so the check runs everywhere.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "plugins" / "onex" / "ONBOARDING.md"
FIXTURE = (
    ROOT
    / "tests"
    / "fixtures"
    / "onboarding_walk_2026_11_02"
    / "detached_head_refusal.json"
)

pytestmark = pytest.mark.unit


def _guide() -> str:
    return " ".join(GUIDE.read_text(encoding="utf-8").split())


def test_walk_2026_11_02_guide_does_not_call_every_detached_head_expected() -> None:
    """The recorded refusal is for a detached clone; the guide used to say any
    detached clone is expected, the opposite of what the guard enforces."""
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "DETACHED HEAD" in recorded["refusal"]
    assert not re.search(r"left at a detached `HEAD`, which is expected\.", _guide()), (
        "the guide calls any detached clone expected; the guard refuses one off the floor commit"
    )


def test_walk_2026_11_02_guide_states_the_rule_the_guard_enforces() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    guide = _guide()
    assert "detached at the commit the floor marker" in guide
    assert ".onex-workspace-floor.json" in guide
    # The refusal the guide warns about is the one the guard prints, with its repair.
    assert recorded["repair_tail"].split(" omnimarket")[0] in guide
    assert "refuses" in guide[guide.index("detached at the commit the floor marker") :]


def test_walk_2026_11_02_fixture_rule_is_the_guides_rule() -> None:
    recorded = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert (
        "detached at the commit the floor marker names is accepted" in recorded["rule"]
    )
    assert (
        "detached anywhere else is refused with the repair command" in recorded["rule"]
    )

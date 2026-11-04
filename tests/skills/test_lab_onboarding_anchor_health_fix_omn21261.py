# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21261: the onboarding anchor is not one that predates the local stack health fix.

omnibase_infra dcd3b55a3 (OMN-22291, omnibase_infra#5660) made the local stack's
health grader quiet. An anchor older than it makes phase 4 rebuild the old grader and
fail on a healthy stack. The script names one anchor; it must not be one recorded here
as predating that fix.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "skills"
    / "_bin"
    / "lab-onboarding.sh"
)

# Anchors that predate omnibase_infra dcd3b55a3 (OMN-22291). Append a superseded
# anchor here when a later one is chosen for the same reason.
ANCHORS_BEFORE_THE_HEALTH_FIX = (
    "aa81312c2c405424d4c947d61c7763d38e67b3a1",  # 2026-10-22
)

pytestmark = pytest.mark.unit


def _anchor() -> str:
    anchors = re.findall(
        r'^INFRA_ANCHOR="\$\{ONBOARD_TEST_INFRA_ANCHOR:-([0-9a-f]{40})\}"$',
        SCRIPT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert len(anchors) == 1, anchors
    return anchors[0]


def test_anchor_is_not_one_that_predates_the_health_fix() -> None:
    assert _anchor() not in ANCHORS_BEFORE_THE_HEALTH_FIX


def test_the_recorded_pre_fix_anchors_are_full_shas() -> None:
    for sha in ANCHORS_BEFORE_THE_HEALTH_FIX:
        assert re.fullmatch(r"[0-9a-f]{40}", sha)

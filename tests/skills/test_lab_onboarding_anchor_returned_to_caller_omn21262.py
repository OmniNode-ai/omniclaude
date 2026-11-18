# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21262: the onboarding anchor carries the returned_to_caller end of the model ladder.

omnimarket 8333e5c1 (OMN-21264, omnimarket#4319) ends an exhausted model ladder as
returned_to_caller, which is what the notice printed before the model questions promises.
An anchor whose omnibase_infra commit pins an omnimarket without it would make the notice
describe behaviour the participant does not have. The script names one anchor; it must not
be one recorded here as pinning an omnimarket without 8333e5c1.
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

# Anchors whose omnibase_infra commit pins an omnimarket without 8333e5c1. Append a superseded
# anchor here when a later one is chosen for the same reason.
ANCHORS_WITHOUT_RETURNED_TO_CALLER = (
    "bf256f9660f2520dddb56328d2983f00bafdc910",  # 2026-11-04, pins omnimarket c7cd6a481acf
    "aa81312c2c405424d4c947d61c7763d38e67b3a1",  # 2026-10-22, pins omnimarket 370f4055
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


def test_anchor_carries_returned_to_caller() -> None:
    assert _anchor() not in ANCHORS_WITHOUT_RETURNED_TO_CALLER


def test_the_recorded_anchors_without_it_are_full_shas() -> None:
    for sha in ANCHORS_WITHOUT_RETURNED_TO_CALLER:
        assert re.fullmatch(r"[0-9a-f]{40}", sha)

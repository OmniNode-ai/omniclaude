# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The repo-evidence caller pins a receipt-gate that counts a pin-train hook rev swap as pin-only.

The sibling-pin train moves the omnibase_core hook revs of ``.pre-commit-config.yaml``
together with the source pin. The receipt-gate reusable only treats that as a
pin-only change from the omnibase_core dev-merge tag that carries the hook rev
swap exemption. ``pull_request_target`` reads the caller from the base branch, so
until the caller on ``dev`` pins that tag or a later one, every train pull
request falls to the evidence steps and fails repo-evidence / dod-verify.
"""

from __future__ import annotations

import re

import pytest

from tests.ci.receipt_gate_pin import RECEIPT_GATE_PIN_TAG

pytestmark = pytest.mark.unit

# First omnibase_core dev-merge tag that holds the hook rev swap exemption.
HOOK_REV_EXEMPTION_FLOOR_TAG = "dev-20261108023315-fe0d8082717e"

_TAG = re.compile(r"dev-(\d{14})-[0-9a-f]{12}")


def _stamp(tag: str) -> int:
    match = _TAG.fullmatch(tag)
    assert match is not None, f"not a dev-merge tag: {tag}"
    return int(match.group(1))


def test_pin_is_at_or_after_the_hook_rev_exemption_tag() -> None:
    assert _stamp(RECEIPT_GATE_PIN_TAG) >= _stamp(HOOK_REV_EXEMPTION_FLOOR_TAG)


def test_floor_control_rejects_the_previous_pin() -> None:
    # Positive control: the pin this repository held before the exemption existed
    # sits below the floor, so the check above can fail.
    assert _stamp("dev-20261101005012-ac2f26e3e5bf") < _stamp(
        HOOK_REV_EXEMPTION_FLOOR_TAG
    )

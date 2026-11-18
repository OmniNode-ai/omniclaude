# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The two dispatch-claim disabled rows carry the reviewed date (OMN-19998)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
INVENTORY = REPO / "plugins/onex/hooks/contracts/hook_inventory.yaml"
SCRIPTS = (
    "hook_dispatch_claim_pretool.sh",
    "hook_dispatch_claim_posttool.sh",
)


def test_dispatch_claim_rows_review_by_2026_12_15() -> None:
    rows = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))["disabled_hooks"]
    by_script = {row["script"]: row for row in rows}
    for script in SCRIPTS:
        assert str(by_script[script]["review_by"]) == "2026-12-15", script

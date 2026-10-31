# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21351 removed the Dependabot version-update schedules.

Dependabot therefore proposes no bump of the hand-pinned omnibase_core refs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HAND_PINNED = (
    "OmniNode-ai/omnibase_core/.github/workflows/receipt-gate.yml",
    "OmniNode-ai/omnibase_core/.github/workflows/imperative-contract-guard.yml",
    "OmniNode-ai/omnibase_core/.github/actions/validate-boundaries",
)


def test_no_github_actions_version_update_entry_exists() -> None:
    config = ROOT / ".github/dependabot.yml"
    if not config.exists():
        return
    data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
    assert not any(
        entry["package-ecosystem"] == "github-actions"
        for entry in data.get("updates", [])
    ), "Dependabot must have no github-actions version-update entry"


@pytest.mark.parametrize("name", HAND_PINNED)
def test_each_hand_pinned_ref_is_still_pinned_and_test_asserted(name: str) -> None:
    # A hand-pinned ref is a full sha or an omnibase_core dev-merge tag (OMN-20134).
    pattern = re.compile(
        rf"uses:\s*{re.escape(name)}@([0-9a-f]{{40}}|dev-\d{{14}}-[0-9a-f]{{12}})"
    )
    shas = {
        sha
        for path in (ROOT / ".github/workflows").glob("*.yml")
        for sha in pattern.findall(path.read_text(encoding="utf-8"))
    }
    assert len(shas) == 1, f"Expected exactly one distinct pin for {name}: {shas}"
    sha = shas.pop()
    assert any(
        sha in path.read_text(encoding="utf-8")
        for path in (ROOT / "tests/ci").rglob("*.py")
        if path.resolve() != Path(__file__).resolve()
    ), f"The pin for {name} must be asserted by another tests/ci file"

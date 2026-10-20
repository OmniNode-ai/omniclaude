# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: Dependabot leaves test-asserted omnibase_core pins to manual repins."""

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


def _github_actions_ignores() -> list[dict[str, str]]:
    data = yaml.safe_load((ROOT / ".github/dependabot.yml").read_text(encoding="utf-8"))
    update = next(
        item
        for item in data["updates"]
        if item["package-ecosystem"] == "github-actions"
    )
    return update.get("ignore", [])


def test_github_actions_update_ignores_each_hand_pinned_ref() -> None:
    ignored = {entry["dependency-name"] for entry in _github_actions_ignores()}
    for name in HAND_PINNED:
        assert name in ignored, f"Dependabot must ignore hand-pinned ref {name}"


def test_ignore_list_names_only_hand_pinned_refs() -> None:
    entries = _github_actions_ignores()
    assert {entry["dependency-name"] for entry in entries} == set(HAND_PINNED)
    for entry in entries:
        assert "versions" not in entry
        assert "update-types" not in entry


@pytest.mark.parametrize("name", HAND_PINNED)
def test_each_ignored_ref_is_still_pinned_and_test_asserted(name: str) -> None:
    pattern = re.compile(rf"uses:\s*{re.escape(name)}@([0-9a-f]{{40}})")
    shas = {
        sha
        for path in (ROOT / ".github/workflows").glob("*.yml")
        for sha in pattern.findall(path.read_text(encoding="utf-8"))
    }
    assert len(shas) == 1, f"Expected exactly one distinct SHA for {name}: {shas}"
    sha = shas.pop()
    assert any(
        sha in path.read_text(encoding="utf-8")
        for path in (ROOT / "tests/ci").rglob("*.py")
        if path.resolve() != Path(__file__).resolve()
    ), f"Drop {name} from Dependabot ignores when its pin is no longer test-asserted"

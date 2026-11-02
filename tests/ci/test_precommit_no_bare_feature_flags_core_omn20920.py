# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-20920 S8: the bare-feature-flag hook is consumed from omnibase_core.

``no-bare-feature-flags`` moved from onex_change_control into omnibase_core
(omnibase_core#1936, merge commit 9218fe703b08d329f76eecd37fabbbc7b0c2baad)
under the same hook id. This repository's ``.pre-commit-config.yaml`` must take
it from an omnibase_core repo block pinned to a dev-merge tag that contains that
commit (OMN-21900: a first-party ref is a dev-merge tag, never a sha), keep its
``stages``, and name no onex_change_control repository at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"
CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
OCC_REPO = "https://github.com/OmniNode-ai/onex_change_control"
# The first dev-merge tag of omnibase_core that contains the exporting merge commit.
EXPORTING_TAG = "dev-20261018024445-b6ee996befa1"
TOPICS_AND_TODOS_PIN = "dev-20261018024445-b6ee996befa1"


def _owners(hook_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Return ``(repo url, rev, hook entry)`` for every block that lists *hook_id*."""
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return [
        (block["repo"], str(block.get("rev", "")), hook)
        for block in config["repos"]
        for hook in block.get("hooks", [])
        if hook.get("id") == hook_id
    ]


def test_no_bare_feature_flags_comes_from_omnibase_core() -> None:
    owners = _owners("no-bare-feature-flags")
    assert [(url, rev) for url, rev, _ in owners] == [(CORE_REPO, EXPORTING_TAG)]
    assert owners[0][2].get("stages") == ["pre-commit"]


def test_config_names_no_onex_change_control_repository() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert OCC_REPO not in {block["repo"] for block in config["repos"]}


@pytest.mark.parametrize("hook_id", ["no-hardcoded-topics", "no-untracked-todos"])
def test_other_core_hooks_keep_their_pin(hook_id: str) -> None:
    """This change repoints one hook only; the other two keep their pin."""
    owners = _owners(hook_id)
    assert [(url, rev) for url, rev, _ in owners] == [(CORE_REPO, TOPICS_AND_TODOS_PIN)]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pre-commit config runs core's no-id-from-stamp hook (OMN-24065 AC1).

Failure mode: the hook id is absent from the config, or listed under a repo
block other than the omnibase_core one, so core's validator never runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[2] / ".pre-commit-config.yaml"


@pytest.mark.unit
def test_no_id_from_stamp_listed_under_omnibase_core() -> None:
    repos = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["repos"]
    owners = [
        repo["repo"]
        for repo in repos
        if "no-id-from-stamp" in {hook["id"] for hook in repo.get("hooks", [])}
    ]
    assert len(owners) == 1
    assert owners[0].rstrip("/").endswith("omnibase_core")

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21282 AC1, the workflow half: the bump PR carries the train's one body.

The train script renders the body (tests/scripts/test_train_pr_body_omn21282.py);
these tests pin that ``sibling-lock-refresh.yml`` asks for it, opens the PR
with it, and rewrites it on the open PR when a later night updates in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "sibling-lock-refresh.yml"
)
_BODY = "/tmp/sibling_pin_train_body.md"


def _step_running(needle: str) -> str:
    steps: list[dict[str, Any]] = yaml.safe_load(WORKFLOW.read_text())["jobs"][
        "refresh"
    ]["steps"]
    hits = [str(s.get("run", "")) for s in steps if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected one step running {needle!r}"
    return hits[0]


def test_train_step_writes_the_one_body() -> None:
    run = _step_running("--dev-tag-train")
    assert f"--body-out {_BODY}" in run


def test_pr_step_opens_with_and_rewrites_the_body() -> None:
    run = _step_running("gh pr create")
    assert f"cat {_BODY}" in run
    assert run.index(f"cat {_BODY}") < run.index("gh pr list")
    assert 'gh pr edit "$existing" --body-file' in run
    assert run.count("gh pr create") == 1

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22477: omniclaude is not on the onboarding proven set.

The sibling-pins file holds a CI pin for omniclaude, an old commit that lacks the
model-config handler phase 3 imports. Onboarding therefore takes omniclaude at the
last origin/dev commit at or before the anchor's time, never at that pin.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
_anchor = importlib.import_module("test_onboarding_anchor_handler_omn21255")
ws: Any = _anchor.ws  # fixture, re-exported so pytest collects it here
PIN: str = _anchor.PIN

pytestmark = pytest.mark.unit


def _omniclaude_clone(workspace: Path) -> tuple[str, str]:
    clone = workspace / "omniclaude"
    clone.mkdir(parents=True)
    _anchor._git(clone, "init", "-q", "-b", "dev")
    before = _anchor._commit(clone, "c1", "2001-09-09T01:00:00+00:00")
    after = _anchor._commit(clone, "c2", "2001-09-09T02:00:00+00:00")
    _anchor._git(clone, "update-ref", "refs/remotes/origin/dev", "HEAD")
    _anchor._git(
        clone, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/dev"
    )
    assert after != before
    return before, after


def test_omniclaude_ignores_its_ci_pin_and_takes_dev_at_the_anchor_time(
    ws: dict[str, str],
) -> None:
    workspace = Path(ws["workspace"])
    pins = workspace / "omnibase_infra/.github/sibling-pins.yaml"
    pins.write_text(f"pins:\n  omniclaude: {PIN}\n  pinned: {PIN}\n")
    before, _after = _omniclaude_clone(workspace)
    result = _anchor._run(ws, "anchored_commit omniclaude; anchored_commit pinned")
    # anchor time 01:46:40 sits between c1 (01:00) and c2 (02:00); a repo still
    # on the proven set keeps its pin.
    assert result.stdout.split() == [before, PIN], result.stdout + result.stderr

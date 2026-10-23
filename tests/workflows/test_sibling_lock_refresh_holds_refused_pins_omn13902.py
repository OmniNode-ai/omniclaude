# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The sibling-lock refresh holds back release pins internal-sibling-pins refuses (OMN-13902).

``uv lock --upgrade-package`` moves every PyPI-range sibling to its newest
release, and internal-sibling-pins (OMN-21282) refuses a moved release pin whose
sibling carries a newer dev merge tag. Siblings are dev-tagged on every merge,
so the refresh PR was red by construction: omniclaude#2947 moved omnibase-core
0.47.52 -> 0.47.53 while omnibase_core carried dev-20261022195312-6890233443b4.
These tests pin that the refresh judges its own lock with the check's handler,
puts every refused pin back at the base lock's version, and re-judges the result
before anything is committed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sibling-lock-refresh.yml"
HANDLER = "omniclaude.handlers.handler_internal_sibling_pins"


def _steps() -> list[dict[str, Any]]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = doc["jobs"]["refresh"]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    hits = [i for i, s in enumerate(steps) if needle in str(s.get("run", ""))]
    assert len(hits) == 1, f"expected exactly one step running {needle!r}, got {hits}"
    return hits[0]


def test_hold_back_runs_after_the_upgrade_and_before_anything_reads_the_lock() -> None:
    steps = _steps()
    upgrade = _index(steps, 'uv lock "${ARGS[@]}"')
    hold = _index(steps, HANDLER)
    sync = _index(steps, "--sync-capture-contract")
    delta = _index(steps, "git diff --quiet")
    assert upgrade < hold < sync < delta, (upgrade, hold, sync, delta)


def test_hold_back_judges_against_the_checked_out_lock_with_read_dev_tags() -> None:
    run = str(_steps()[_index(_steps(), HANDLER)]["run"])
    assert "git show HEAD:uv.lock" in run
    assert "--base-lock" in run
    assert "--needs-tags" in run
    assert "git ls-remote --tags --refs" in run
    assert "--dev-tags" in run


def test_refused_pins_are_relocked_at_their_base_version_and_rejudged() -> None:
    run = str(_steps()[_index(_steps(), HANDLER)]["run"])
    assert "^REFUSED" in run
    assert '"--upgrade-package" "${name}==${version}"' in run
    assert 'uv lock "${HOLD[@]}"' in run
    relock = run.index('uv lock "${HOLD[@]}"')
    # The last command is the unguarded re-judgement: under `set -e` a lock the
    # check still refuses stops the job before a PR is opened.
    assert "set -euo pipefail" in run
    assert run.rstrip().endswith('"${check[@]}"')
    assert run.rstrip().rindex('"${check[@]}"') > relock

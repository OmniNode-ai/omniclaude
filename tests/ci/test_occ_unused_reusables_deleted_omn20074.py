# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20074 S9: the OCC scripts no caller runs are gone from omniclaude.

``scripts/scaffold_occ_receipt.py`` wrote an onex_change_control DoD receipt
and ``scripts/materialize-dod-evidence-from-occ.sh`` copied OCC contract
evidence into a local receipt. No workflow, hook or script in any registry
repository runs either one at its default branch, and the only instruction that
named the scaffold tool was the dispatch-worker receipt-pairing rule, which now
points at the repo's own contract instead.

The reusables other repositories still call stay hosted here until their last
caller is gone, including the minting pair and the deploy gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILLS = REPO_ROOT / "plugins" / "onex" / "skills"

_DELETED = (
    "scripts/scaffold_occ_receipt.py",
    "tests/scripts/test_scaffold_occ_receipt.py",
    "scripts/materialize-dod-evidence-from-occ.sh",
    "tests/unit/test_dod_occ_materialization.py",
)

_STILL_CALLED = (
    ".github/workflows/call-occ-autobind-reusable.yml",
    ".github/workflows/call-occ-companion-effect-reusable.yml",
    ".github/workflows/deploy-gate-reusable.yml",
)


def test_unused_occ_scripts_are_deleted() -> None:
    present = [rel for rel in _DELETED if (REPO_ROOT / rel).exists()]
    assert not present, present


def test_no_skill_instructs_running_a_deleted_occ_script() -> None:
    names = [Path(rel).name for rel in _DELETED]
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {name}"
        for path in sorted(SKILLS.rglob("*.md"))
        for name in names
        if name in path.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_canonical_file_shape_baseline_drops_the_deleted_scripts() -> None:
    baseline = REPO_ROOT / ".onex_ratchets" / "canonical_file_shape_baseline.txt"
    rows = set(baseline.read_text(encoding="utf-8").splitlines())
    stale = [rel for rel in _DELETED if rel in rows]
    assert not stale, stale


def test_reusables_with_live_callers_stay_hosted() -> None:
    missing = [rel for rel in _STILL_CALLED if not (REPO_ROOT / rel).is_file()]
    assert not missing, missing

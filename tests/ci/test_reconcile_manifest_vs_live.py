# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the privileged manifest-vs-live reconcile (OMN-14854).

Exercises `reconcile()` directly with a stubbed live-context list (no `gh`
subprocess call) so the suite runs offline and deterministically.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_DIR = REPO_ROOT / ".github" / "actions" / "required-check-skip-guard"
if str(_GUARD_DIR) not in sys.path:
    sys.path.insert(0, str(_GUARD_DIR))

from reconcile_manifest_vs_live import reconcile  # noqa: E402


def _manifest(tmp_path: Path, gates: list[dict]) -> Path:
    path = tmp_path / "required-checks.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "classification": "toolchain",
                "repo": "fixture",
                "gates": gates,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_live_has_extra_context_missing_from_manifest(tmp_path: Path) -> None:
    manifest_path = _manifest(tmp_path, [{"name": "A", "mode": "REQUIRED"}])
    missing, stale = reconcile(manifest_path, ["A", "B"])
    assert missing == {"B"}
    assert stale == set()


def test_manifest_has_extra_required_row_not_live(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path, [{"name": "A", "mode": "REQUIRED"}, {"name": "C", "mode": "REQUIRED"}]
    )
    missing, stale = reconcile(manifest_path, ["A"])
    assert missing == set()
    assert stale == {"C"}


def test_exact_match_is_clean(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path, [{"name": "A", "mode": "REQUIRED"}, {"name": "B", "mode": "REQUIRED"}]
    )
    missing, stale = reconcile(manifest_path, ["A", "B"])
    assert missing == set()
    assert stale == set()


def test_advisory_rows_are_excluded_from_manifest_required_set(tmp_path: Path) -> None:
    manifest_path = _manifest(
        tmp_path,
        [
            {"name": "A", "mode": "REQUIRED"},
            {"name": "not-required-yet", "mode": "ADVISORY"},
        ],
    )
    missing, stale = reconcile(manifest_path, ["A"])
    assert missing == set()
    assert stale == set()


def test_branch_scoped_row_excluded_when_reconciling_a_different_branch(
    tmp_path: Path,
) -> None:
    """OMN-15117: a REQUIRED row carrying `branch: main` must not surface as
    `stale_in_manifest` when reconciling `dev` — it simply isn't in scope for
    that branch's comparison."""
    manifest_path = _manifest(
        tmp_path,
        [
            {"name": "A", "mode": "REQUIRED"},
            {"name": "verify / verify", "mode": "REQUIRED", "branch": "main"},
        ],
    )
    missing, stale = reconcile(manifest_path, ["A"], branch="dev")
    assert missing == set()
    assert stale == set()


def test_branch_scoped_row_included_when_reconciling_its_own_branch(
    tmp_path: Path,
) -> None:
    """The same row IS in scope, and must resolve cleanly, when reconciling
    against the branch it declares."""
    manifest_path = _manifest(
        tmp_path,
        [
            {"name": "A", "mode": "REQUIRED"},
            {"name": "verify / verify", "mode": "REQUIRED", "branch": "main"},
        ],
    )
    missing, stale = reconcile(manifest_path, ["A", "verify / verify"], branch="main")
    assert missing == set()
    assert stale == set()


def test_branch_scoped_row_missing_from_live_is_still_flagged_on_its_own_branch(
    tmp_path: Path,
) -> None:
    """A branch-scoped row is not exempt from detection on its own branch —
    only exempt from cross-branch noise."""
    manifest_path = _manifest(
        tmp_path,
        [{"name": "verify / verify", "mode": "REQUIRED", "branch": "main"}],
    )
    missing, stale = reconcile(manifest_path, [], branch="main")
    assert missing == set()
    assert stale == {"verify / verify"}


def test_no_branch_argument_preserves_legacy_behavior(tmp_path: Path) -> None:
    """Calling reconcile() without a `branch` kwarg (pre-OMN-15117 call sites)
    must count every REQUIRED row regardless of any `branch:` field — this is
    the pre-existing, un-scoped comparison."""
    manifest_path = _manifest(
        tmp_path,
        [{"name": "verify / verify", "mode": "REQUIRED", "branch": "main"}],
    )
    missing, stale = reconcile(manifest_path, ["verify / verify"])
    assert missing == set()
    assert stale == set()

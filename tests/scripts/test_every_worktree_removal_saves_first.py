# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Gate: every worktree-removal site in this repository saves first (OMN-19539).

The operator ruled on 2026-09-25 that every worktree-removal path saves the
worktree's diff and untracked files before removing it. A behavioural test per
path proves the paths that exist today; this scan keeps a NEW removal site from
landing without the save. It finds every ``git worktree remove`` call in the
shipped shell and Python under ``scripts/`` and ``plugins/`` and requires the
file to call ``worktree_removal_snapshot``. The saving file is also required to
name the helper BEFORE the removal, so a save bolted on after the fact fails.

The one exemption class is a tool removing a worktree it created itself in its
own ``mktemp`` scratch dir, which never holds anyone's work. Each exemption
names its reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = "worktree_removal_snapshot"

_SH_REMOVE = re.compile(r"\bgit\b.*\bworktree\s+remove\b")
_PY_REMOVE = re.compile(r"""["']worktree["']\s*,\s*["']remove["']""")

# A tool removing the scratch worktree it created under its own mktemp dir.
EXEMPT = {
    "scripts/rebase-wave.sh": "removes only worktrees it added under its own mktemp SCRATCH_DIR",
}


def _removal_lines(path: Path) -> list[int]:
    pattern = _SH_REMOVE if path.suffix == ".sh" else _PY_REMOVE
    hits: list[int] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith(("log ", "echo ")):
            continue
        if pattern.search(line):
            hits.append(number)
    return hits


def _removal_sites() -> dict[str, list[int]]:
    sites: dict[str, list[int]] = {}
    for base in ("scripts", "plugins"):
        for path in sorted((REPO_ROOT / base).rglob("*")):
            if path.suffix not in (".sh", ".py") or not path.is_file():
                continue
            if "/tests/" in path.as_posix() or path.name == f"{HELPER}.py":
                continue
            lines = _removal_lines(path)
            if lines:
                sites[path.relative_to(REPO_ROOT).as_posix()] = lines
    return sites


def test_the_scan_finds_the_known_removal_sites() -> None:
    """Positive control: a scan that finds nothing proves nothing."""
    sites = _removal_sites()
    for known in (
        "scripts/worktree_auto_prune.py",
        "scripts/prune-worktrees.sh",
        "plugins/onex/hooks/scripts/session-end.sh",
        "plugins/onex/hooks/lib/worktree_manager.py",
        "scripts/rebase-wave.sh",
    ):
        assert known in sites, f"scan no longer sees {known}: {sorted(sites)}"


def test_every_removal_site_saves_before_it_removes() -> None:
    missing: list[str] = []
    for rel, lines in _removal_sites().items():
        if rel in EXEMPT:
            continue
        text = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        helper_lines = [n for n, line in enumerate(text, 1) if HELPER in line]
        if not helper_lines:
            missing.append(f"{rel}: removes at line(s) {lines}, never calls {HELPER}")
        elif min(helper_lines) > min(lines):
            missing.append(
                f"{rel}: first removal at line {min(lines)} precedes the save"
            )
    assert not missing, "\n".join(missing)


def test_exemptions_still_exist() -> None:
    """A stale exemption is a hole waiting for a new file of the same name."""
    sites = _removal_sites()
    for rel in EXEMPT:
        assert rel in sites, f"exemption {rel} no longer removes a worktree; drop it"

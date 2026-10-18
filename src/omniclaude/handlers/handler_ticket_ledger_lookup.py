# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Rolling-ledger lookups of the ticket-creation guard (OMN-18404 rule 9).

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the defect-diagnosis rule (rule 15) without growing. The guard
loads this module by path and runs it under a bare interpreter with no
``omniclaude`` package, so it imports the standard library only.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


def ledger_path() -> Path | None:
    """The rolling ledger to resolve rulings against, or ``None``.

    ``ONEX_LEDGER_PATH`` first, which is where a dispatched lane's copy lives;
    ``$OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md`` second.
    """
    explicit = os.environ.get("ONEX_LEDGER_PATH", "").strip()
    if explicit:
        return Path(explicit)
    home = os.environ.get("OMNI_HOME", "").strip()
    if home:
        return Path(home) / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    return None


def rows_for_stamp(ledger: Path, stamp: str, separator: str) -> list[str]:
    """Every row of ``ledger`` (and its rolled archive) whose first cell is ``stamp``.

    An unreadable file contributes no rows, so an unreadable ledger approves
    nothing: the rewrite stays refused. A symlinked ledger, a symlinked
    ``archive`` directory and a symlinked archive file are never followed, so a
    ruling cannot be read from outside the ledger's own directory.
    """
    files = [ledger]
    archive = ledger.parent / "archive"
    if archive.is_dir() and not archive.is_symlink():
        files.extend(sorted(archive.glob(f"{ledger.stem}_*-split.md")))
    prefix = f"{stamp}{separator}"
    rows: list[str] = []
    for path in files:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        rows.extend(line for line in lines if line.startswith(prefix))
    return rows


def ruling_lookup(separator: str) -> Callable[[str], list[str]]:
    """Bind rule 9's ledger seam to the rolling ledger on this machine."""
    ledger = ledger_path()

    def lookup(stamp: str) -> list[str]:
        return rows_for_stamp(ledger, stamp, separator) if ledger is not None else []

    return lookup

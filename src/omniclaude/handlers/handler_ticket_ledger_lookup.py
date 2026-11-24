# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Work-ledger lookups of the ticket-creation guard (OMN-18404 rule 9, OMN-26567).

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py``, a baselined
file that may only shrink. The guard loads this module by path under a bare
interpreter with the standard library only, so the reader node is a subprocess,
never an import. A row is named by its stamp, the first cell of the row; rule 9
and rule 15 each resolve a stamp through the work-ledger reader node under their
own reader name and open no file. A reader that does not answer resolves nothing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from subprocess import SubprocessError, run

READER_MODULE = "omnimarket.nodes.node_work_ledger_reader_effect"
#: The reader names listed in ``moved_readers`` of the reader node's overlay.
RULING_READER = "ticket-ruling"
DIAGNOSIS_READER = "ticket-diagnosis"


def rows_for_stamp(
    reader: str, stamp: str, separator: str, bound_s: float = 25.0
) -> list[str]:
    """Rows the reader returns whose first cell is ``stamp`` (its ``--term`` matches
    anywhere in the first line); none when the reader errors, is absent or answers
    after ``bound_s``: the guard sits on a tool call and the reader can be slow."""
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return []
    hours = max(1, int((datetime.now(UTC) - then).total_seconds() // 3600) + 2)
    python = (
        os.environ.get("ONEX_LEDGER_READER_PYTHON")
        or f"{os.environ.get('OMNI_HOME', '')}/.onex-dispatch-venv/bin/python"
    )
    command = [python, "-m", READER_MODULE, "--reader", reader, "--query", "rows"]
    command += ["--window-hours", str(hours), "--term", stamp]
    try:
        done = run(
            command, capture_output=True, text=True, timeout=bound_s, check=False
        )
    except (OSError, SubprocessError):
        return []
    if done.returncode != 0:
        return []
    return [
        line for line in done.stdout.splitlines() if line.split(separator)[0] == stamp
    ]


def ruling_lookup(separator: str) -> Callable[[str], list[str]]:
    """Rule 9's ledger seam: a stamp to the rows of the ruling reader."""
    return lambda stamp: rows_for_stamp(RULING_READER, stamp, separator)


def diagnosis_lookup(separator: str) -> Callable[[str], list[str]]:
    """Rule 15's ledger seam: a stamp to the rows of the diagnosis reader."""
    return lambda stamp: rows_for_stamp(DIAGNOSIS_READER, stamp, separator)

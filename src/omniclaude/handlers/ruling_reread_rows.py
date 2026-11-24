# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ledger rows the publish-time ruling re-read judges, read narrowly (OMN-26330).

The re-read needs three things: the lane's own CLAIM rows, the lane's own ACK rows, and the RULING rows
appended since its newest CLAIM. It used to ask the work-ledger reader node for the CLAIM, RULING and ACK
rows of every lane over the node's 30 day ceiling in one read: 61565 rows matched and 263.3 s on a lab
host on 2026-11-24, past the 150 s bound of the call, so a lane could not publish at all. The same
facts come from two reads that stay inside the bound: the lane's CLAIM and ACK rows (``--row-lane``
over the ceiling: 13.8 s and 2 rows for this lane there), then the RULING rows of the hours since that
lane's newest CLAIM (3 hours: 10.4 s and 6 rows; the RULING rows of all 720 hours alone: 6.3 s and 540
rows). The CLAIM and ACK rows of every lane are what the unfiltered read paid for. The lane's CLAIM is
the one an unfiltered read would have kept, a RULING older than it is skipped by the re-read, and an ACK
only counts when it names the lane, so no row the re-read used is dropped. A read that does not answer
still raises :class:`~omniclaude.handlers.work_ledger_rows.LedgerRowsUnavailable`; the ledger file is
never read in its place and a longer bound is never the fix.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime

from omniclaude.handlers.work_ledger_rows import read_rows

#: The reader node's ceiling for a window, in hours (30 days).
MAX_WINDOW_HOURS = 24 * 30
_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


def newest_claim_stamp(rows: list[str], lane: str) -> str:
    """The timestamp of the newest CLAIM row of ``lane`` in ``rows``, or ``""`` when it has none."""
    stamps = []
    for raw in rows:
        cells = [cell.strip() for cell in raw.split(" | ")]
        stamp = cells[0].removeprefix("- ").strip()
        if len(cells) > 2 and cells[1] == "CLAIM" and _STAMP.fullmatch(stamp):
            if f"lane={lane}" in cells[2:]:
                stamps.append(stamp)
    return max(stamps, default="")


def ruling_reread_rows(
    reader: str,
    lane: str,
    *,
    environ: Mapping[str, str],
    now: datetime | None = None,
) -> list[str]:
    """The lane's CLAIM and ACK rows, then the RULING rows of the hours since its newest CLAIM."""
    own = read_rows(
        reader,
        MAX_WINDOW_HOURS,
        ("CLAIM", "ACK"),
        environ=environ,
        row_lanes=(lane,),
    )
    claim = newest_claim_stamp(own, lane)
    if not claim:
        return own  # no CLAIM: the caller refuses it, and no ruling can follow one
    opened = datetime.strptime(claim, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    age_s = ((now or datetime.now(UTC)) - opened).total_seconds()
    hours = min(MAX_WINDOW_HOURS, max(1, math.ceil(age_s / 3600) + 1))
    return [*own, *read_rows(reader, hours, ("RULING",), environ=environ)]

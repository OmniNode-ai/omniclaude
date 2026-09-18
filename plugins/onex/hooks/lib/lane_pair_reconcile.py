# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One-shot repair for agent-id-mangled lane pairs [OMN-18690].

What it repairs
---------------
Before OMN-18690 the ``SubagentStop`` guard handed
:func:`lane_registry.close_lane` the harness's agent id
(``a`` + lane name + ``-`` + 16 hex) instead of the dispatch-time lane
name. No OPEN record carries that string, so each death was written under
a synthetic ``unattributed-*`` id while the real dispatch record aged into
``died_no_terminal``. Every such lane is counted **twice** by
``onex-lane-reconcile``, and neither row carries the lane's tickets, tool
name or dispatch time.

The fix stops new pairs being created. This script resolves the ones
already on disk.

Why it appends rather than edits
--------------------------------
Lane records are governed evidence. A repair that rewrote them in place
would be indistinguishable, after the fact, from the corruption it
repairs -- and the registry offers no supersession of its own, one file
per lane keyed by ``lane_id``. So the repair writes a line to the
append-only journal :data:`lane_registry.RESOLUTIONS_FILENAME`, which
:func:`lane_registry.reconcile` applies as a read-time overlay. Every
record file is left byte-identical, and a resolution can be audited,
superseded by a later line, or ignored by deleting the journal.

Why the pairing is a proof rather than a guess
----------------------------------------------
A pair is only formed when **all** of the following hold, and the
resolution line records each of them:

1. the closed record's ``lane_id`` starts with ``unattributed-``;
2. its ``lane_name`` parses as ``a<name>-<16 hex>`` -- an anonymous
   ``a<hex>`` id embeds no name and is reported unpairable, never paired;
3. exactly one OPEN record in the **same session** carries that ``<name>``
   -- two candidates are reported ambiguous and left alone;
4. that record's ``dispatched_at`` precedes the closed record's
   ``closed_at``, because a lane dispatched after a death cannot be the
   lane that died;
5. that record's TTL has already elapsed, so it is a lane
   ``onex-lane-reconcile`` already reports as ``died_no_terminal``.

Rule 5 is why the repair cannot pre-empt a live lane. A twin can be
written at a usage-limit *pause* that the lane later resumes from (the
mechanism the parent ticket OMN-18130 tracks), and an open record still
inside its TTL may be that lane, still working. Resolving it would report
a running lane as dead -- the exact inversion this registry exists to
prevent. A first pass over this host's records found 33 such lanes, so
the bound is not theoretical.

The terminal state is copied from the twin. Nothing is upgraded to
``completed``: a lane that hit the usage-limit wall still reconciles as a
usage-limit death, it just stops reconciling as two separate failures.

Usage::

    onex-lane-pair-reconcile              # dry run, prints the pair count
    onex-lane-pair-reconcile --json
    onex-lane-pair-reconcile --execute    # append one resolution per pair

Refs: OMN-18690; parent OMN-18130; OMN-16471 (the registry).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

from lane_registry import (
    DEFAULT_OPEN_TTL_SECONDS,
    EnumLaneStatus,
    ModelLaneRecord,
    ModelLaneResolution,
    append_resolution,
    lane_name_from_agent_id,
    load_records,
    load_resolutions,
)

EXIT_OK = 0


@dataclass(frozen=True)
class ModelLanePair:
    """One proven pairing of a dispatch record and its unattributed twin."""

    open_lane_id: str
    unattributed_lane_id: str
    lane_name: str
    agent_id: str
    terminal_state: str
    terminal_reason: str


@dataclass(frozen=True)
class ModelPairReport:
    """What a pairing pass found, and what it did about it."""

    pairs: tuple[ModelLanePair, ...]
    ambiguous: int
    unpairable: int
    no_open_record: int
    already_resolved: int
    still_within_ttl: int
    executed: bool

    def to_json(self) -> dict[str, object]:
        """Render the report for ``--json``."""

        return {
            "ticket": "OMN-18690",
            "executed": self.executed,
            "counts": {
                "pairs": len(self.pairs),
                "ambiguous": self.ambiguous,
                "unpairable": self.unpairable,
                "no_open_record": self.no_open_record,
                "already_resolved": self.already_resolved,
                "still_within_ttl": self.still_within_ttl,
            },
            "pairs": [
                {
                    "open_lane_id": pair.open_lane_id,
                    "unattributed_lane_id": pair.unattributed_lane_id,
                    "lane_name": pair.lane_name,
                    "agent_id": pair.agent_id,
                    "terminal_state": pair.terminal_state,
                }
                for pair in self.pairs
            ],
        }


def _dispatch_precedes_close(open_record: ModelLaneRecord, closed_at: str) -> bool:
    """True when the dispatch is not later than the death it is paired with.

    An unparseable timestamp on either side is treated as *not proven*,
    so the pair is declined rather than formed on a comparison that could
    not be made.
    """

    if not open_record.dispatched_at or not closed_at:
        return False
    try:
        dispatched = datetime.fromisoformat(open_record.dispatched_at)
        closed = datetime.fromisoformat(closed_at)
    except ValueError:
        return False
    if dispatched.tzinfo is None:
        dispatched = dispatched.replace(tzinfo=UTC)
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=UTC)
    return dispatched <= closed


def _ttl_elapsed(
    open_record: ModelLaneRecord, *, moment: datetime, ttl_seconds: int
) -> bool:
    """True when the dispatch record is already past its TTL.

    An unparseable ``dispatched_at`` counts as elapsed, matching
    :func:`lane_registry.reconcile`, which cannot prove such a record
    young and so already reports it as a failure.
    """

    if not open_record.dispatched_at:
        return True
    try:
        dispatched = datetime.fromisoformat(open_record.dispatched_at)
    except ValueError:
        return True
    if dispatched.tzinfo is None:
        dispatched = dispatched.replace(tzinfo=UTC)
    return (moment - dispatched).total_seconds() > ttl_seconds


def pair_lanes(
    *, execute: bool = False, ttl_seconds: int = DEFAULT_OPEN_TTL_SECONDS
) -> ModelPairReport:
    """Pair mangled unattributed records with their open dispatch records.

    Writes nothing unless *execute* is true, and even then only ever
    appends to the resolution journal.
    """

    moment = datetime.now(UTC)
    records = load_records()
    resolved = load_resolutions()
    superseded = {
        resolution.superseded_lane_id
        for resolution in resolved.values()
        if resolution.superseded_lane_id
    }

    open_by_session: dict[tuple[str, str], list[ModelLaneRecord]] = {}
    for record in records:
        if record.status is EnumLaneStatus.OPEN and record.lane_name:
            open_by_session.setdefault(
                (record.session_id, record.lane_name), []
            ).append(record)

    pairs: list[ModelLanePair] = []
    ambiguous = 0
    unpairable = 0
    no_open_record = 0
    already_resolved = 0
    still_within_ttl = 0

    for record in records:
        if not record.lane_id.startswith("unattributed-"):
            continue
        if record.status is not EnumLaneStatus.CLOSED:
            continue
        if record.lane_id in superseded:
            already_resolved += 1
            continue

        state = record.terminal_state
        if state is None:
            # A closed record with no terminal state carries nothing to
            # transfer, so there is no resolution to append.
            unpairable += 1
            continue

        embedded = lane_name_from_agent_id(record.lane_name)
        if not embedded:
            unpairable += 1
            continue

        candidates = open_by_session.get((record.session_id, embedded), [])
        candidates = [
            candidate
            for candidate in candidates
            if candidate.lane_id not in resolved
            and _dispatch_precedes_close(candidate, record.closed_at)
        ]
        if len(candidates) > 1:
            ambiguous += 1
            continue
        if not candidates:
            no_open_record += 1
            continue
        # A lane still inside its TTL may be running right now -- a twin is
        # written at a usage-limit pause the lane can resume from. Never
        # resolve one; it would report a live lane as dead.
        if not _ttl_elapsed(candidates[0], moment=moment, ttl_seconds=ttl_seconds):
            still_within_ttl += 1
            continue

        target = candidates[0]
        pairs.append(
            ModelLanePair(
                open_lane_id=target.lane_id,
                unattributed_lane_id=record.lane_id,
                lane_name=target.lane_name,
                agent_id=record.lane_name,
                terminal_state=state.value,
                terminal_reason=record.terminal_reason,
            )
        )
        # Claim the target so a second twin in the same pass cannot also
        # pair onto it.
        resolved[target.lane_id] = ModelLaneResolution(
            lane_id=target.lane_id,
            superseded_lane_id=record.lane_id,
            terminal_state=state,
            terminal_reason=record.terminal_reason,
            resolved_at="",
        )

        if execute:
            append_resolution(
                ModelLaneResolution(
                    lane_id=target.lane_id,
                    superseded_lane_id=record.lane_id,
                    terminal_state=state,
                    terminal_reason=(
                        f"{record.terminal_reason} [OMN-18690: recovered from "
                        f"unattributed twin {record.lane_id}]"
                    ),
                    resolved_at=datetime.now(UTC).isoformat(),
                    evidence={
                        "paired_agent_id": record.lane_name,
                        "paired_lane_name": target.lane_name,
                        "paired_from": record.lane_id,
                        "pairing_rule": "a<lane_name>-<16 hex> agent id, unique open "
                        "record in the same session, dispatched_at <= closed_at",
                    },
                )
            )

    return ModelPairReport(
        pairs=tuple(pairs),
        ambiguous=ambiguous,
        unpairable=unpairable,
        no_open_record=no_open_record,
        already_resolved=already_resolved,
        still_within_ttl=still_within_ttl,
        executed=execute,
    )


def _render_human(report: ModelPairReport) -> str:
    lines = [
        "Lane pair reconciliation (OMN-18690)"
        + ("" if report.executed else "  [DRY RUN — nothing written]"),
        f"  pairs: {len(report.pairs)}",
        f"  ambiguous (two open lanes share the name): {report.ambiguous}",
        f"  unpairable (anonymous agent id, no name embedded): {report.unpairable}",
        f"  no matching open record: {report.no_open_record}",
        f"  already resolved: {report.already_resolved}",
        f"  skipped, open lane still within TTL (may be live): "
        f"{report.still_within_ttl}",
    ]
    if not report.executed and report.pairs:
        lines.append("")
        lines.append("Re-run with --execute to append one resolution per pair.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Pair and report. Dry run unless ``--execute`` is passed."""

    parser = argparse.ArgumentParser(
        prog="onex-lane-pair-reconcile",
        description=(
            "Pair agent-id-mangled unattributed-* lane records with the open "
            "dispatch records they belong to, and close the pair by APPENDING "
            "a resolution (OMN-18690). Never edits a lane record."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Append the resolutions. Without it, nothing is written.",
    )
    parser.add_argument("--json", action="store_true", help="Emit the report as JSON.")
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_OPEN_TTL_SECONDS,
        help=(
            "An open record younger than this may still be running and is "
            f"never resolved (default: {DEFAULT_OPEN_TTL_SECONDS})."
        ),
    )
    args = parser.parse_args(argv)

    report = pair_lanes(execute=args.execute, ttl_seconds=args.ttl_seconds)
    if args.json:
        sys.stdout.write(json.dumps(report.to_json(), indent=2) + "\n")
    else:
        sys.stdout.write(_render_human(report) + "\n")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())

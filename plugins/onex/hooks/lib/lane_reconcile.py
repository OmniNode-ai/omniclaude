# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane reconciliation CLI [OMN-16471].

Turns the durable lane records written by :mod:`lane_registry` and
:mod:`lane_termination_guard` into a **failing exit code**.

Why the exit code is the point
------------------------------
Friction F-09's fourth corrective action is "require a terminal record
per lane and treat its absence as a failure, not a pending". A record
nobody reads enforces nothing, and CLAUDE.md rule 5 is explicit that
detection which is not wired to a failing gate is advisory and gets
ignored. So this CLI exits ``1`` whenever any lane holds a terminal
failure state -- an observed death, or an OPEN dispatch whose TTL
elapsed with no terminal record -- and ``0`` only when every lane
reconciles as completed. A workflow tail, a closeout step, or an
overseer tick can call it and *fail*.

Usage::

    onex-lane-reconcile                 # human summary, exit 1 on failures
    onex-lane-reconcile --json          # machine-readable verdict
    onex-lane-reconcile --ttl-seconds 900
    onex-lane-reconcile --prune         # delete reconciled records

``--prune`` removes records that have been reported, so the next run is
not dominated by history. It refuses to remove still-running lanes.

Refs: OMN-16471; friction F-09 §"Corrective action" (d).
"""

from __future__ import annotations

import argparse
import json
import sys

from lane_registry import (
    DEFAULT_OPEN_TTL_SECONDS,
    ModelLaneReconciliation,
    lanes_dir,
    reconcile,
)

EXIT_OK = 0
EXIT_LANE_FAILURES = 1


def _render_human(verdict: ModelLaneReconciliation) -> str:
    lines = [
        "Lane reconciliation (OMN-16471)",
        f"  completed:       {len(verdict.completed)}",
        f"  failed:          {len(verdict.failed)}",
        f"  open within TTL: {len(verdict.open_within_ttl)}",
    ]
    if verdict.failed:
        lines.append("")
        lines.append("FAILED LANES — these did not complete:")
        for record in verdict.failed:
            state = (
                record.terminal_state.value
                if record.terminal_state is not None
                else "unknown"
            )
            tickets = ",".join(record.tickets) if record.tickets else "-"
            lines.append(
                f"  [{state}] {record.lane_name} "
                f"(session={record.session_id[:12] or '-'}, tickets={tickets})"
            )
            lines.append(f"      {record.terminal_reason}")
    return "\n".join(lines)


def _prune(verdict: ModelLaneReconciliation) -> int:
    """Delete records already reported; keep still-running lanes."""

    directory = lanes_dir()
    if directory is None:
        return 0
    removed = 0
    keep = {record.lane_id for record in verdict.open_within_ttl}
    for record in list(verdict.completed) + list(verdict.failed):
        if record.lane_id in keep:
            continue
        path = directory / f"{record.lane_id}.json"
        try:
            path.unlink()
        except OSError:
            continue
        removed += 1
    return removed


def main(argv: list[str] | None = None) -> int:
    """Reconcile lane records; return ``1`` when any lane failed."""

    parser = argparse.ArgumentParser(
        prog="onex-lane-reconcile",
        description=(
            "Reconcile agent-lane dispatch/termination records (OMN-16471). "
            "Exits 1 when any lane holds a failure terminal state, including "
            "a dispatched lane that never reported one."
        ),
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=DEFAULT_OPEN_TTL_SECONDS,
        help=(
            "An OPEN lane older than this is reported as died_no_terminal "
            f"(default: {DEFAULT_OPEN_TTL_SECONDS})."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Emit the verdict as JSON.")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete reconciled records after reporting them.",
    )
    args = parser.parse_args(argv)

    verdict = reconcile(ttl_seconds=args.ttl_seconds)
    payload = verdict.to_json()

    if args.prune:
        payload["pruned"] = _prune(verdict)

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(_render_human(verdict) + "\n")

    return EXIT_LANE_FAILURES if verdict.has_failures else EXIT_OK


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())

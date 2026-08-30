#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Fast-path hook emitter (OMN-17224): append one event, exit.

This replaces ``node_event_emit_effect_dispatch.py`` on the per-tool-call
hook path. That script imported the omnimarket handler stack and published
to Kafka inline; profiling put 31.08s of a 31.65s ``handle()`` in a lazily-
imported ``omnibase_infra`` chain that builds ~2,497 Pydantic classes. With
one such process forked per tool call, 14 ran concurrently at ~270% CPU.

Here the hook does one thing: serialize the event to the local journal.
Publishing is the drainer's job (``hook_emit_drainer.py``), which pays that
import once for the life of the machine instead of once per tool call.

Deliberately stdlib-only and free of any ``omnibase_infra`` / ``omnimarket``
import -- see ``hook_emit_journal`` for why that constraint is load-bearing
and mechanically tested.

Fail-open, like every hook on this path: always exits 0. A hook that cannot
record telemetry must still never break or slow the operator's session.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_emit_journal as journal  # noqa: E402


def _parse_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse; malformed input degrades to ``{}``."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument(
        "--journal-dir",
        default=None,
        help="Override the journal directory (defaults to ONEX_STATE_DIR).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=journal.DEFAULT_MAX_RECORDS,
        help="Backpressure bound; oldest records are dropped and counted.",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        # argparse exits non-zero on bad args; fail-open still applies.
        return 0

    try:
        target = (
            Path(args.journal_dir)
            if args.journal_dir
            else journal.default_journal_dir()
        )
        outcome = journal.append(
            target,
            event_type=args.event_type,
            payload=_parse_payload(args.payload),
            correlation_id=args.correlation_id,
            max_records=args.max_records,
        )
        if outcome.dropped_count:
            # Backpressure is worth a line in the hook log: it means the
            # drainer is not keeping up (or is not running at all).
            print(
                f"hook_emit_append: journal over bound; dropped "
                f"{outcome.dropped_count} oldest record(s)",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 -- outermost fail-open boundary
        print(f"hook_emit_append: unexpected error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

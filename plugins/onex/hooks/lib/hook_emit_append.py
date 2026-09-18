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

import hook_actor  # noqa: E402
import hook_emit_journal as journal  # noqa: E402
import hook_lane_attribution as lane_attribution  # noqa: E402


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
        "--cwd",
        default=None,
        help=(
            "The working directory the hook fired in, taken from the harness "
            "hook payload rather than this process's own cwd. Used to resolve "
            "the lane identity merged onto the event (OMN-18609)."
        ),
    )
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "The agent host that produced this event, as declared by the hook "
            "registration that invoked the caller (OMN-18704). Absent means "
            "the Claude Code host. Never inferred from the environment: a "
            "Codex hook inherits its parent's environment, so a Codex session "
            "launched from a Claude Code session carries CLAUDECODE=1."
        ),
    )
    parser.add_argument(
        "--turn-id",
        default=None,
        help=(
            "The host's per-turn identifier, when it supplies one. Codex does; "
            "Claude Code's hook input carries no turn identifier, so the field "
            "is null there rather than absent, and the envelope contract "
            "records why."
        ),
    )
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
        payload = _parse_payload(args.payload)
        # Lane attribution is merged here rather than in the shell hook so the
        # registry read costs nothing on the foreground path: this process is
        # already forked and disowned by the time it runs. Caller-supplied
        # lane keys are never trusted -- the registry is the authority, so an
        # existing key is overwritten rather than preserved.
        payload.update(lane_attribution.attribution_fields(args.cwd))
        # The actor is stamped here, after the caller's payload, for the same
        # reason lane attribution is: a caller-supplied key is never trusted.
        # The registration that the host resolved is the authority.
        payload["actor"] = hook_actor.resolve_actor(args.actor)
        turn_id = (args.turn_id or "").strip()
        payload["turn_id"] = turn_id or None
        outcome = journal.append(
            target,
            event_type=args.event_type,
            payload=payload,
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

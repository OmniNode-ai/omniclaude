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

Fail-loud (OMN-20110): an event that cannot be journalled exits 1 with the
cause on stderr. The hook runs this under ``hook_emit_bounded.py``, which
turns that exit, or a missed time budget, into a blocking error and one
operator alarm per failure episode. The operator ruling of 2026-09-29: a hook
may not fail silently.
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
import hook_turn_id  # noqa: E402


def _parse_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse; malformed input degrades to ``{}``."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def append_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    correlation_id: str | None,
    cwd: str | None,
    actor: str | None,
    host_turn_id: str | None,
    agent_id: str | None,
    transcript_path: str | None,
    session_id: str | None,
    journal_dir: str | None,
) -> str | None:
    """Stamp lane, actor and turn onto ``payload`` and journal it.

    Returns the turn id stamped on the record, so a caller journalling a
    second record for the same hook call (OMN-19551's content record) can
    carry the SAME turn instead of racing a second allocation.

    Raises whatever the journal raises; :func:`main` turns it into exit 1.
    """
    target = Path(journal_dir) if journal_dir else journal.default_journal_dir()
    # Lane attribution is merged here rather than in the shell hook so the
    # registry read costs nothing on the foreground path: this process is
    # already forked and disowned by the time it runs. Caller-supplied
    # lane keys are never trusted -- the registry is the authority, so an
    # existing key is overwritten rather than preserved.
    payload.update(
        lane_attribution.attribution_fields(
            cwd,
            transcript_path=transcript_path,
            session_id=session_id,
            agent_id=agent_id,
        )
    )
    # The actor is stamped here, after the caller's payload, for the same
    # reason lane attribution is: a caller-supplied key is never trusted.
    # The registration that the host resolved is the authority.
    payload["actor"] = hook_actor.resolve_actor(actor)
    # OMN-19517: a host-supplied turn id (Codex) is kept verbatim. Claude
    # Code sends none, and a null here reached the bus as sha256("null"),
    # one digest shared by every session, so the appender mints a turn per
    # session prompt instead. Session start and end stay null.
    turn_id = hook_turn_id.resolve_turn_id(
        hook_turn_id.turn_dir_for(target),
        event_type=event_type,
        # Never the correlation id: the scripts pass "unknown" there when
        # the input has no session, and a turn keyed on that would be
        # shared by every such session -- the defect again.
        session_id=session_id or _str_or_none(payload.get("session_id")),
        host_turn_id=host_turn_id,
    )
    payload["turn_id"] = turn_id
    journal.append(
        target,
        event_type=event_type,
        payload=payload,
        correlation_id=correlation_id,
    )
    return turn_id


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
            "The host's per-turn identifier, when it supplies one. Codex does "
            "and it is kept verbatim. Claude Code's hook input carries none, "
            "so the appender mints one per session prompt (OMN-19517, "
            "hook_turn_id); session start and end records carry null."
        ),
    )
    parser.add_argument(
        "--agent-id",
        default=None,
        help=(
            "The harness's id for the agent that fired this hook. Resolves the "
            "lane through the harness's own spawn sidecar, which is the only "
            "operand that identifies a lane at emit time: a dispatched lane's "
            "cwd is the session's directory, not its worktree (OMN-18609)."
        ),
    )
    parser.add_argument(
        "--transcript-path",
        default=None,
        help="The session transcript path, used to locate the agent sidecar.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Fallback locator for the agent sidecar when no transcript path is given.",
    )
    parser.add_argument(
        "--journal-dir",
        default=None,
        help="Override the journal directory (defaults to ONEX_STATE_DIR).",
    )
    args = parser.parse_args(argv)

    try:
        append_event(
            event_type=args.event_type,
            payload=_parse_payload(args.payload),
            correlation_id=args.correlation_id,
            cwd=args.cwd,
            actor=args.actor,
            host_turn_id=args.turn_id,
            agent_id=args.agent_id,
            transcript_path=args.transcript_path,
            session_id=args.session_id,
            journal_dir=args.journal_dir,
        )
    except Exception as exc:  # noqa: BLE001 -- outermost boundary: report, exit 1
        print(
            f"hook_emit_append: {args.event_type} NOT journalled: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    journal.emit_done()
    return 0


if __name__ == "__main__":
    sys.exit(main())

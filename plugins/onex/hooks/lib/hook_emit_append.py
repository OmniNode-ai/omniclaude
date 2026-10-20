#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Admit and stamp one hook event, journal it and exit (OMN-17224, OMN-17427).

Only the resident drainer publishes; a remote acknowledgement must never spend
the hook's time budget. Stdlib-only (see ``hook_emit_journal``). A journal
failure exits 1, which ``hook_emit_bounded.py`` turns into a block (OMN-20110).
"""

from __future__ import annotations

import argparse
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_actor  # noqa: E402
import hook_emit_journal as journal  # noqa: E402
import hook_lane_attribution as lane_attribution  # noqa: E402
import hook_turn_id  # noqa: E402

# OMN-17427: the stdlib handler that owns developer-principal admission. A
# missing file (a plugin tree without src/) falls back to the installed package.
_HANDLER = "handlers/handler_hook_local_bus_publish.py"
_BUS_HANDLER = Path(__file__).resolve().parents[4] / "src/omniclaude" / _HANDLER


def _load_bus_handler() -> Any:
    source: Path | None = _BUS_HANDLER
    if not _BUS_HANDLER.is_file():
        # Plugin caches carry no src tree. Locate the installed package without
        # executing its expensive __init__; the verified plugin venv owns it.
        package = importlib.machinery.PathFinder.find_spec("omniclaude")
        roots = (package.submodule_search_locations if package else None) or []
        source = next((p for r in roots if (p := Path(r) / _HANDLER).is_file()), None)
    spec = source and importlib.util.spec_from_file_location("hook_local_bus", source)
    if not spec or spec.loader is None:
        return None
    bus = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bus)
    return bus


def developer_event_suppressed(event_type: str) -> bool:
    admission = getattr(_load_bus_handler(), "developer_event_suppressed", None)
    return bool(admission and admission(event_type))


def _parse_payload(raw: str) -> dict[str, Any]:
    """Best-effort JSON parse; malformed input degrades to ``{}``."""
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _deferred_by_status(event_type: str, drainer_status: str | None) -> bool:
    """True when a ledger event's type is not listed by the drainer's status."""
    if not drainer_status or not journal.is_ledger_event_type(event_type):
        return False
    import hook_emit_health as health

    status = health.read_status(Path(drainer_status))
    publishable = None if status is None else status.publishable_event_types
    return publishable is None or event_type not in publishable


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
    drainer_status: str | None = None,
) -> str | None:
    """Admit, stamp and journal one event, returning its turn id.

    Unknown work-ledger types are deferred beside the journal until the drainer
    lists them as publishable. A journal failure propagates to main's error path.
    """
    # OMN-17427: drop the complete class before turn allocation, transport or
    # journal. Filtering a fan-out topic downstream would leave its evt half and
    # could still spool a command the contractor cannot publish.
    if developer_event_suppressed(event_type):
        return host_turn_id
    target = Path(journal_dir) if journal_dir else journal.default_journal_dir()
    # The registry is the authority for lane attribution. Caller-supplied
    # lane keys are overwritten rather than trusted.
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
    event = {
        "event_type": event_type,
        "payload": payload,
        "correlation_id": correlation_id,
    }
    if _deferred_by_status(event_type, drainer_status):
        journal.defer(target, **event)
    else:
        journal.append(target, **event)
    return turn_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-type", required=True)
    parser.add_argument("--payload", default="{}")
    parser.add_argument("--correlation-id", default=None)
    # The working directory the hook fired in, taken from the harness hook payload
    # rather than this process's own cwd. Used to resolve the lane identity merged
    # onto the event (OMN-18609).
    parser.add_argument("--cwd", default=None, help="the hook's cwd (OMN-18609)")
    # The agent host that produced this event, as declared by the hook registration
    # that invoked the caller (OMN-18704). Absent means the Claude Code host. Never
    # inferred from the environment: a Codex hook inherits its parent's environment,
    # so a Codex session launched from a Claude Code session carries CLAUDECODE=1.
    parser.add_argument(
        "--actor", default=None, help="the declared agent host (OMN-18704)"
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
    parser.add_argument(
        "--drainer-status",
        default=None,
        help=(
            "The drainer's status file (OMN-20735). A work.ledger.* event whose "
            "type it does not list as publishable is deferred, not journalled."
        ),
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
            drainer_status=args.drainer_status,
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

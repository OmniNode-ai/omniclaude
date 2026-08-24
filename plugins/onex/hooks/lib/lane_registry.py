# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Durable agent-lane dispatch/termination registry [OMN-16471].

Why this exists
---------------
A dispatched agent lane that *dies* produces the same observable shape as
one that *completed*: silence. Friction report ``F-09``
(``omni_home/docs/tracking/2026-08-24-system-friction-report.md``, lines
224-246) measured the consequence in a single 34h window: 4 lane deaths,
11 permanently unresumable agent ids, 6 ``Not logged in`` resume
failures, and -- the P0 -- ``verify-build-drive`` terminating at **0
tokens / 0 tool calls / 285 ms**, so that the mandated adversarial verify
of a 2.47M-token, 7-agent build drive never ran *and the workflow scored
the stage as complete*.

The root cause is not behavioural. There is simply no durable,
machine-readable record of a lane's existence or its terminal state, so:

* a lane that dies before producing any artifact leaves zero trace --
  absence of output is indistinguishable from absence of dispatch;
* nothing ever asks "which dispatched lanes never reported a terminal
  state?", so an open lane decays into a *pending*, and a pending reads
  as *fine*.

This module is the record. :func:`open_lane` is called from the
``PreToolUse`` dispatch seam, :func:`close_lane` from ``SubagentStop``
(see :mod:`lane_termination_guard`), and :func:`reconcile` turns the two
into a verdict where an unclosed lane past its TTL is a **terminal
failure**, never a pending.

Correlation is best-effort, and deliberately fails visible
-----------------------------------------------------------
Claude Code does not hand the ``SubagentStop`` payload the id of the
``Task``/``Agent`` call that started the lane, so open and close records
cannot be joined on a harness-supplied key. :func:`close_lane` therefore
resolves a target in this order:

1. exact ``lane_name`` match among the session's OPEN records
   (newest first);
2. the single OPEN record in the session, when exactly one is open;
3. no target -- the terminal record is still written, attributed to a
   synthetic ``unattributed-*`` lane id.

Every fallback leaves the ambiguous OPEN records untouched, so a
mis-correlation degrades into "reconcile reports an open lane", never
into "a dead lane was silently marked complete". The direction of the
failure is the whole point.

Stdlib-only, and never raises into a hook
-----------------------------------------
Hooks run under the lite-mode system interpreter where pydantic is not
guaranteed to be importable, so this module uses ``@dataclass`` rather
than Pydantic -- the same deliberate exception the sibling
``subagent_report_contract_guard`` and ``subagent_secret_leak_guard``
modules take, for the same reason. Every public function is
best-effort: an unset or unwritable ``ONEX_STATE_DIR`` yields ``None``
rather than an exception, because a registry that can wedge a dispatch
is worse than no registry.

Refs: OMN-16471; friction F-09. Sibling seams: OMN-15213 (SubagentStop
report-contract guard), OMN-15062 (SubagentStop secret-leak guard).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

# Lane records live here, one JSON file per lane, under $ONEX_STATE_DIR.
LANES_SUBDIR = ("hooks", "lanes")

# A lane still OPEN this long after dispatch is reported as a death rather
# than a pending. Sized above the longest lane observed in the F-09 window
# (``omn15459-supersession``, 2h48m) so an ordinary long lane is never
# misreported, while a lane that vanished is not waited on indefinitely.
DEFAULT_OPEN_TTL_SECONDS = 4 * 60 * 60

# Tool names that dispatch an agent lane. ``Task`` is the classic
# subagent tool; ``Agent`` is its current name; the ``Workflow`` fan-out
# dispatches lanes too. Kept in sync with ``cost_accounting._TOOL_NAMES``.
DISPATCH_TOOL_NAMES = ("Task", "Agent", "Workflow")

_RE_TICKET = re.compile(r"\bOMN-\d{3,6}\b")

# Prompt text is never stored -- only a digest, so a lane record can be
# correlated to its brief without the registry becoming a second copy of
# every dispatch prompt (which would put secrets on disk).
_PROMPT_DIGEST_CHARS = 16


class EnumLaneStatus(StrEnum):
    """Lifecycle status of a lane record."""

    OPEN = "open"
    CLOSED = "closed"


class EnumLaneTerminalState(StrEnum):
    """How a lane ended.

    Every member except :attr:`COMPLETED` is a **failure**. That is the
    contract F-09 asks for: the states below exist so that a death stops
    being reported as a finished stage.
    """

    COMPLETED = "completed"
    #: Terminated under 1s with zero tool calls -- the ``verify-build-drive``
    #: shape. The lane did no work at all.
    DIED_ZERO_WORK = "died_zero_work"
    #: Weekly/session usage-limit wall.
    DIED_USAGE_LIMIT = "died_usage_limit"
    #: ``Not logged in`` / ``authentication_failed``.
    DIED_AUTH_FAILED = "died_auth_failed"
    #: Server error mid-response / transport death.
    DIED_API_ERROR = "died_api_error"
    #: ``No transcript found for agent ID`` -- the lane cannot be resumed,
    #: ever. A distinct state so a dead resume id stops being retried as
    #: though it were live.
    NOT_RESUMABLE = "not_resumable"
    #: Dispatched, never reported a terminal state, TTL elapsed. Absence of
    #: a terminal record is a failure, not a pending.
    DIED_NO_TERMINAL = "died_no_terminal"


#: Terminal states that mean the lane failed. Used by :func:`reconcile` and
#: by the reconcile CLI's exit code.
FAILURE_STATES = frozenset(
    state for state in EnumLaneTerminalState if state != EnumLaneTerminalState.COMPLETED
)


@dataclass(frozen=True)
class ModelLaneRecord:
    """One lane's durable record."""

    lane_id: str
    lane_name: str
    session_id: str
    tool_name: str
    dispatched_at: str
    status: EnumLaneStatus
    tickets: tuple[str, ...] = ()
    prompt_digest: str = ""
    terminal_state: EnumLaneTerminalState | None = None
    terminal_reason: str = ""
    closed_at: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Render to the on-disk shape."""

        return {
            "ticket": "OMN-16471",
            "lane_id": self.lane_id,
            "lane_name": self.lane_name,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "dispatched_at": self.dispatched_at,
            "status": self.status.value,
            "tickets": list(self.tickets),
            "prompt_digest": self.prompt_digest,
            "terminal_state": (
                self.terminal_state.value if self.terminal_state is not None else None
            ),
            "terminal_reason": self.terminal_reason,
            "closed_at": self.closed_at,
            "evidence": dict(self.evidence),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> ModelLaneRecord | None:
        """Parse an on-disk record, or ``None`` if it is not one."""

        lane_id = payload.get("lane_id")
        if not isinstance(lane_id, str) or not lane_id:
            return None
        raw_status = str(payload.get("status") or EnumLaneStatus.OPEN.value)
        try:
            status = EnumLaneStatus(raw_status)
        except ValueError:
            status = EnumLaneStatus.OPEN
        raw_terminal = payload.get("terminal_state")
        terminal: EnumLaneTerminalState | None = None
        if isinstance(raw_terminal, str) and raw_terminal:
            try:
                terminal = EnumLaneTerminalState(raw_terminal)
            except ValueError:
                terminal = None
        tickets = payload.get("tickets")
        evidence = payload.get("evidence")
        return cls(
            lane_id=lane_id,
            lane_name=str(payload.get("lane_name") or ""),
            session_id=str(payload.get("session_id") or ""),
            tool_name=str(payload.get("tool_name") or ""),
            dispatched_at=str(payload.get("dispatched_at") or ""),
            status=status,
            tickets=tuple(str(t) for t in tickets) if isinstance(tickets, list) else (),
            prompt_digest=str(payload.get("prompt_digest") or ""),
            terminal_state=terminal,
            terminal_reason=str(payload.get("terminal_reason") or ""),
            closed_at=str(payload.get("closed_at") or ""),
            evidence=dict(evidence) if isinstance(evidence, dict) else {},
        )


@dataclass(frozen=True)
class ModelLaneReconciliation:
    """Verdict over every lane record in the registry."""

    completed: tuple[ModelLaneRecord, ...]
    failed: tuple[ModelLaneRecord, ...]
    open_within_ttl: tuple[ModelLaneRecord, ...]

    @property
    def has_failures(self) -> bool:
        """True when at least one lane holds a failure terminal state."""

        return bool(self.failed)

    def to_json(self) -> dict[str, Any]:
        """Render the verdict for the reconcile CLI."""

        return {
            "ticket": "OMN-16471",
            "has_failures": self.has_failures,
            "counts": {
                "completed": len(self.completed),
                "failed": len(self.failed),
                "open_within_ttl": len(self.open_within_ttl),
            },
            "failed": [record.to_json() for record in self.failed],
            "open_within_ttl": [record.to_json() for record in self.open_within_ttl],
            "completed": [record.to_json() for record in self.completed],
        }


def lanes_dir() -> Path | None:
    """Return the lane-record directory, or ``None`` when unavailable.

    ``None`` (rather than an exception) so an unset ``ONEX_STATE_DIR``
    degrades the registry instead of wedging the dispatch it observes.
    """

    try:
        from onex_state import ensure_state_dir

        return ensure_state_dir(*LANES_SUBDIR)
    except Exception:  # noqa: BLE001 - state dir unset/unwritable must not raise
        return None


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _write_record(record: ModelLaneRecord) -> Path | None:
    """Atomically persist *record*; ``None`` when the registry is unavailable."""

    directory = lanes_dir()
    if directory is None:
        return None
    path = directory / f"{record.lane_id}.json"
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(record.to_json(), indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return None
    return path


def load_records() -> tuple[ModelLaneRecord, ...]:
    """Read every lane record. Unreadable/foreign files are skipped."""

    directory = lanes_dir()
    if directory is None:
        return ()
    records: list[ModelLaneRecord] = []
    try:
        paths = sorted(directory.glob("*.json"))
    except OSError:
        return ()
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        record = ModelLaneRecord.from_json(payload)
        if record is not None:
            records.append(record)
    return tuple(records)


def extract_lane_name(tool_input: dict[str, Any]) -> str:
    """Derive a human lane name from a dispatch tool's input.

    Prefers the caller-supplied agent name, then the subagent type, then
    the short description -- the same identifiers the ledger and
    ``ListAgents`` use, so a registry record can be matched to a lane by
    eye as well as mechanically.
    """

    for key in ("name", "agent_name", "subagent_type", "description", "task"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    return "unnamed-lane"


def _prompt_digest(tool_input: dict[str, Any]) -> str:
    parts = []
    for key in ("prompt", "message", "description", "task"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            parts.append(value)
    if not parts:
        return ""
    blob = "\n".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(blob).hexdigest()[:_PROMPT_DIGEST_CHARS]


def _tickets(tool_input: dict[str, Any]) -> tuple[str, ...]:
    parts = []
    for value in tool_input.values():
        if isinstance(value, str):
            parts.append(value)
    found = _RE_TICKET.findall("\n".join(parts))
    seen: list[str] = []
    for ticket in found:
        if ticket not in seen:
            seen.append(ticket)
    return tuple(seen[:10])


def _lane_id(session_id: str, lane_name: str, dispatched_at: str) -> str:
    seed = f"{session_id}|{lane_name}|{dispatched_at}".encode(errors="replace")
    return f"lane-{hashlib.sha256(seed).hexdigest()[:20]}"


def open_lane(event: dict[str, Any]) -> ModelLaneRecord | None:
    """Record a dispatch from a ``PreToolUse`` event.

    Returns ``None`` -- writing nothing -- when the event is not a
    dispatch of an agent lane, or when the registry is unavailable. The
    record it writes is what makes a lane that later dies before reaching
    ``SubagentStop`` visible at all.
    """

    tool_name = str(event.get("tool_name") or event.get("toolName") or "")
    if tool_name not in DISPATCH_TOOL_NAMES:
        return None
    raw_input = event.get("tool_input") or event.get("toolInput") or {}
    tool_input = raw_input if isinstance(raw_input, dict) else {}

    dispatched_at = _now().isoformat()
    session_id = str(event.get("session_id") or event.get("sessionId") or "")
    lane_name = extract_lane_name(tool_input)
    record = ModelLaneRecord(
        lane_id=_lane_id(session_id, lane_name, dispatched_at),
        lane_name=lane_name,
        session_id=session_id,
        tool_name=tool_name,
        dispatched_at=dispatched_at,
        status=EnumLaneStatus.OPEN,
        tickets=_tickets(tool_input),
        prompt_digest=_prompt_digest(tool_input),
    )
    if _write_record(record) is None:
        return None
    return record


def _select_close_target(
    records: tuple[ModelLaneRecord, ...],
    session_id: str,
    lane_name: str,
) -> ModelLaneRecord | None:
    """Pick which OPEN record a terminal event belongs to.

    See the module docstring: exact name match, then a unique open lane in
    the session, then nothing. Never guesses between two candidates --
    guessing would close the wrong lane and hide a real death.
    """

    open_in_session = [
        record
        for record in records
        if record.status is EnumLaneStatus.OPEN and record.session_id == session_id
    ]
    if not open_in_session:
        return None
    if lane_name:
        named = [record for record in open_in_session if record.lane_name == lane_name]
        if named:
            return max(named, key=lambda record: record.dispatched_at)
    if len(open_in_session) == 1:
        return open_in_session[0]
    return None


def close_lane(
    *,
    session_id: str,
    lane_name: str,
    terminal_state: EnumLaneTerminalState,
    terminal_reason: str,
    evidence: dict[str, Any] | None = None,
) -> ModelLaneRecord | None:
    """Write the terminal record for a lane.

    When no OPEN record can be attributed (see the module docstring) the
    terminal record is written anyway under a synthetic ``unattributed-*``
    lane id: a death that cannot be matched to its dispatch is still a
    death, and dropping it would restore exactly the silence this module
    exists to remove.
    """

    closed_at = _now().isoformat()
    target = _select_close_target(load_records(), session_id, lane_name)
    if target is None:
        lane_id = f"unattributed-{_lane_id(session_id, lane_name, closed_at)[5:]}"
        target = ModelLaneRecord(
            lane_id=lane_id,
            lane_name=lane_name or "unnamed-lane",
            session_id=session_id,
            tool_name="",
            dispatched_at="",
            status=EnumLaneStatus.OPEN,
        )
    closed = ModelLaneRecord(
        lane_id=target.lane_id,
        lane_name=target.lane_name,
        session_id=target.session_id,
        tool_name=target.tool_name,
        dispatched_at=target.dispatched_at,
        status=EnumLaneStatus.CLOSED,
        tickets=target.tickets,
        prompt_digest=target.prompt_digest,
        terminal_state=terminal_state,
        terminal_reason=terminal_reason,
        closed_at=closed_at,
        evidence=dict(evidence or {}),
    )
    if _write_record(closed) is None:
        return None
    return closed


def reconcile(
    *,
    ttl_seconds: int = DEFAULT_OPEN_TTL_SECONDS,
    now: datetime | None = None,
    records: tuple[ModelLaneRecord, ...] | None = None,
) -> ModelLaneReconciliation:
    """Classify every lane record into completed / failed / still-running.

    An OPEN record older than *ttl_seconds* is promoted to
    :attr:`EnumLaneTerminalState.DIED_NO_TERMINAL` and reported as a
    failure. That promotion is the mechanism behind F-09's fourth
    corrective action -- "treat the absence of a terminal row as a
    failure, not a pending".
    """

    moment = now or _now()
    all_records = load_records() if records is None else records
    completed: list[ModelLaneRecord] = []
    failed: list[ModelLaneRecord] = []
    running: list[ModelLaneRecord] = []

    for record in all_records:
        if record.status is EnumLaneStatus.CLOSED:
            if record.terminal_state in FAILURE_STATES:
                failed.append(record)
            else:
                completed.append(record)
            continue

        dispatched = _parse_ts(record.dispatched_at)
        # An OPEN record with an unparseable dispatch timestamp cannot be
        # proven young, so it fails closed rather than hiding in the
        # still-running bucket forever.
        expired = (
            dispatched is None or (moment - dispatched).total_seconds() > ttl_seconds
        )
        if expired:
            failed.append(
                ModelLaneRecord(
                    lane_id=record.lane_id,
                    lane_name=record.lane_name,
                    session_id=record.session_id,
                    tool_name=record.tool_name,
                    dispatched_at=record.dispatched_at,
                    status=EnumLaneStatus.CLOSED,
                    tickets=record.tickets,
                    prompt_digest=record.prompt_digest,
                    terminal_state=EnumLaneTerminalState.DIED_NO_TERMINAL,
                    terminal_reason=(
                        "dispatched lane never reported a terminal state within "
                        f"{ttl_seconds}s"
                    ),
                    closed_at="",
                    evidence=dict(record.evidence),
                )
            )
        else:
            running.append(record)

    return ModelLaneReconciliation(
        completed=tuple(completed),
        failed=tuple(failed),
        open_within_ttl=tuple(running),
    )


def _cli_main() -> int:
    """Record a dispatch from a ``PreToolUse`` stdin payload.

    Always exits 0 and always emits nothing. This hook is an observer at
    the dispatch seam, not a gate: a registry that can refuse or slow a
    dispatch would be a worse failure than the invisibility it exists to
    fix, and speaking on stdout at ``PreToolUse`` injects context into
    every single lane launch.
    """

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    if not isinstance(event, dict):
        return 0
    try:
        open_lane(event)
    except Exception:  # noqa: BLE001 - the registry must never wedge a dispatch
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(_cli_main())

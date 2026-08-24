# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""SubagentStop lane-termination guard [OMN-16471].

Classifies *how a lane ended* from transcript evidence, so that a death
stops being scored as a completed stage.

The defect (friction F-09)
--------------------------
``omni_home/docs/tracking/2026-08-24-system-friction-report.md`` §F-09
records a 34h window with 4 lane deaths, 11 permanently unresumable
agent ids and 6 ``Not logged in`` resume failures. The P0 instance:
workflow ``wf_49e3ed80-aab``'s ``verify-build-drive`` lane terminated at
**0 tokens / 0 tool calls / 285 ms**. It was the mandated adversarial
verify of a 2.47M-token, 7-agent build drive. It never ran, and nothing
in the system said so -- the workflow reported the stage as complete.
Quoting the report's failure-mode line: "a lane that dies at 285ms
produces the same 'workflow finished' shape as one that completed."

The two existing ``SubagentStop`` guards do not close this. OMN-15062
scans the final message for secrets; OMN-15213 checks that the final
message *looks like a report*. Neither asks the prior question -- did
this lane do any work at all? A lane that produced no final message at
all sails through both: the report-contract guard's documented fail
posture is ALLOW on ``no_message_extracted``, precisely so it does not
freeze ordinary turns. That is correct for a report-shape gate and is
exactly the hole a zero-work death falls through.

What this guard does
--------------------
Computes two facts the agent cannot author -- tool-call count and lane
duration -- and scans the transcript tail for the death signatures F-09
enumerates, then assigns one terminal state:

``NOT_RESUMABLE`` > ``DIED_USAGE_LIMIT`` > ``DIED_AUTH_FAILED`` >
``DIED_API_ERROR`` > ``DIED_ZERO_WORK`` > ``COMPLETED``

Explicit death signatures outrank the zero-work heuristic because they
*explain* it: a lane that died at the weekly-limit wall is reported as a
usage-limit death, not as an unexplained no-op. All of them are
failures; the ordering only decides which reason is recorded.

Every non-``COMPLETED`` verdict writes a durable terminal record through
:mod:`lane_registry`, which is what the reconcile CLI later fails on.
``DIED_ZERO_WORK`` additionally *blocks* once: a lane that did nothing is
the one case where a forced continuation turn is a free retry rather
than noise. Loop safety matches the sibling guard -- ``stop_hook_active``
means the turn is already continuing because a stop hook blocked it, so
the verdict stays but the block is dropped and the record is written.

Fail posture
------------
Fail-OPEN on every uncertainty: an unreadable transcript, missing
timestamps, or an unavailable state dir yields ``COMPLETED`` /
``insufficient_evidence`` rather than a block. This is an accounting
gate, not a security control, and blocking every subagent turn in every
OmniNode repo because a transcript shape changed would be a far larger
outage than the one it prevents. The zero-work rule requires *positive*
evidence of both conditions (a measured sub-threshold duration AND zero
tool calls) before it fires.

Uses ``@dataclass`` rather than Pydantic, matching its two sibling
``SubagentStop`` guards: these modules must import under the lite-mode
system interpreter, where pydantic is not guaranteed to be present.

Refs: OMN-16471; friction F-09. Siblings: OMN-15213, OMN-15062.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lane_registry import EnumLaneTerminalState, close_lane, extract_lane_name

# A lane that ran less than this AND made zero tool calls did no work.
# Both conditions are required: a fast lane that called tools did work,
# and a long lane with no tool calls may be a legitimate reasoning-only
# return. The observed death was 285 ms, so 1000 ms sits an order of
# magnitude above it while staying far below any real lane.
MIN_LANE_DURATION_MS = 1000

# Only the tail of a transcript is scanned for death signatures: the
# error that killed a lane is written at the end, and a lane that merely
# *discussed* usage limits mid-run must not be classed as having died of
# one.
TAIL_LINES_SCANNED = 40

_RE_USAGE_LIMIT = re.compile(
    r"(?:hit your (?:weekly|session|5-hour|five-hour) limit"
    r"|usage limit reached"
    r"|claude usage limit"
    r"|out of (?:weekly |session )?(?:usage|tokens)"
    r"|rate_limit_error)",
    re.IGNORECASE,
)
_RE_AUTH_FAILED = re.compile(
    r"(?:not logged in"
    r"|please run /login"
    r"|authentication_failed"
    r"|oauth token (?:has )?expired"
    r"|invalid api key)",
    re.IGNORECASE,
)
_RE_API_ERROR = re.compile(
    r"(?:server error mid-response"
    r"|api_error"
    r"|overloaded_error"
    r"|internal server error"
    r"|connection error after \d+ retries)",
    re.IGNORECASE,
)
_RE_NOT_RESUMABLE = re.compile(
    r"no transcript found(?: for agent id)?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModelLaneMetrics:
    """Work actually observed in a lane's transcript.

    ``duration_ms`` is ``None`` when it could not be measured; callers
    must not treat that as zero.
    """

    tool_calls: int
    duration_ms: int | None
    entries: int


@dataclass(frozen=True)
class ModelLaneTermination:
    """The classified end-state of one lane."""

    terminal_state: EnumLaneTerminalState
    reason: str
    metrics: ModelLaneMetrics
    lane_name: str
    session_id: str
    blocking: bool

    @property
    def is_failure(self) -> bool:
        """True when the lane did not complete."""

        return self.terminal_state is not EnumLaneTerminalState.COMPLETED


def _read_transcript_lines(stop_event: dict[str, Any]) -> list[str]:
    """Return the transcript's raw JSONL lines, or ``[]`` when unavailable."""

    for key in ("agent_transcript_path", "transcript_path"):
        raw_path = stop_event.get(key)
        if isinstance(raw_path, str) and raw_path:
            try:
                text = Path(raw_path).read_text(encoding="utf-8")
            except OSError:
                continue
            return [line for line in text.splitlines() if line.strip()]

    blob = stop_event.get("transcript")
    if isinstance(blob, str) and blob:
        return [line for line in blob.splitlines() if line.strip()]
    return []


def _count_tool_uses(entry: dict[str, Any]) -> int:
    """Count tool_use blocks in one transcript entry."""

    if entry.get("type") == "tool_use":
        return 1
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if content is None:
        content = entry.get("content")
    if not isinstance(content, list):
        return 0
    return sum(
        1
        for part in content
        if isinstance(part, dict) and part.get("type") == "tool_use"
    )


def _entry_timestamp(entry: dict[str, Any]) -> datetime | None:
    raw = entry.get("timestamp") or entry.get("ts")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _event_duration_ms(stop_event: dict[str, Any]) -> int | None:
    """Prefer a harness-supplied duration when the payload carries one."""

    for key in ("duration_ms", "total_duration_ms", "durationMs"):
        value = stop_event.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float) and value >= 0:
            return int(value)
    return None


def transcript_metrics(stop_event: dict[str, Any]) -> ModelLaneMetrics:
    """Measure tool-call count and wall duration from the transcript.

    These are the two facts a dying lane cannot author for itself, which
    is why the classification rests on them rather than on the lane's own
    final message.
    """

    lines = _read_transcript_lines(stop_event)
    tool_calls = 0
    entries = 0
    first: datetime | None = None
    last: datetime | None = None

    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        entries += 1
        tool_calls += _count_tool_uses(entry)
        stamp = _entry_timestamp(entry)
        if stamp is None:
            continue
        if first is None or stamp < first:
            first = stamp
        if last is None or stamp > last:
            last = stamp

    duration_ms = _event_duration_ms(stop_event)
    if duration_ms is None and first is not None and last is not None:
        duration_ms = int((last - first).total_seconds() * 1000)

    return ModelLaneMetrics(
        tool_calls=tool_calls, duration_ms=duration_ms, entries=entries
    )


def _tail_text(stop_event: dict[str, Any]) -> str:
    lines = _read_transcript_lines(stop_event)
    return "\n".join(lines[-TAIL_LINES_SCANNED:])


def _death_signature(text: str) -> tuple[EnumLaneTerminalState, str] | None:
    """Match the F-09 death signatures, highest precedence first."""

    if _RE_NOT_RESUMABLE.search(text):
        return (EnumLaneTerminalState.NOT_RESUMABLE, "no_transcript_for_agent_id")
    if _RE_USAGE_LIMIT.search(text):
        return (EnumLaneTerminalState.DIED_USAGE_LIMIT, "usage_limit_wall")
    if _RE_AUTH_FAILED.search(text):
        return (EnumLaneTerminalState.DIED_AUTH_FAILED, "authentication_failed")
    if _RE_API_ERROR.search(text):
        return (EnumLaneTerminalState.DIED_API_ERROR, "api_transport_error")
    return None


def classify_lane_termination(stop_event: dict[str, Any]) -> ModelLaneTermination:
    """Assign a terminal state to a ``SubagentStop`` event.

    ``stop_hook_active`` drops the block (the turn is already continuing
    because a stop hook blocked it) without softening the verdict, so a
    zero-work lane cannot wedge in an unbounded block/reply/block cycle.
    """

    session_id = str(stop_event.get("session_id") or stop_event.get("sessionId") or "")
    raw_input = stop_event.get("tool_input") or stop_event.get("toolInput") or {}
    lane_name = (
        extract_lane_name(raw_input)
        if isinstance(raw_input, dict) and raw_input
        else str(
            stop_event.get("agent_name")
            or stop_event.get("subagent_type")
            or stop_event.get("agent_id")
            or ""
        )
    )

    metrics = transcript_metrics(stop_event)
    signature = _death_signature(_tail_text(stop_event))

    if signature is not None:
        state, reason = signature
        blocking = False
    elif metrics.duration_ms is not None and (
        metrics.duration_ms < MIN_LANE_DURATION_MS and metrics.tool_calls == 0
    ):
        state = EnumLaneTerminalState.DIED_ZERO_WORK
        reason = (
            f"terminated after {metrics.duration_ms}ms with 0 tool calls "
            f"(threshold {MIN_LANE_DURATION_MS}ms)"
        )
        blocking = True
    else:
        state = EnumLaneTerminalState.COMPLETED
        reason = (
            "completed"
            if metrics.duration_ms is not None
            else "insufficient_evidence_of_death"
        )
        blocking = False

    if blocking and stop_event.get("stop_hook_active"):
        blocking = False
        reason = f"{reason} [retry_exhausted]"

    return ModelLaneTermination(
        terminal_state=state,
        reason=reason,
        metrics=metrics,
        lane_name=lane_name,
        session_id=session_id,
        blocking=blocking,
    )


def record_termination(result: ModelLaneTermination) -> None:
    """Persist a terminal lane record; never raises into the hook path.

    Written for **every** verdict, not only failures: a ``COMPLETED``
    record is what lets :func:`lane_registry.reconcile` distinguish a
    lane that finished from one that vanished. Without the completed
    half, every lane would eventually reconcile as
    ``DIED_NO_TERMINAL``.
    """

    try:
        close_lane(
            session_id=result.session_id,
            lane_name=result.lane_name,
            terminal_state=result.terminal_state,
            terminal_reason=result.reason,
            evidence={
                "tool_calls": result.metrics.tool_calls,
                "duration_ms": result.metrics.duration_ms,
                "transcript_entries": result.metrics.entries,
                "recorded_at": datetime.now(UTC).isoformat(),
            },
        )
    except Exception:  # noqa: BLE001 - registry failure must not wedge the hook
        return


def _hook_output(result: ModelLaneTermination) -> dict[str, Any] | None:
    """Render a verdict into a Claude Code hook envelope, or ``None``.

    ``None`` means emit nothing. The PASS path is deliberately silent for
    the OMN-15213 reason: a hook that speaks at end-of-turn becomes the
    notification an agent replies to, and that reply clobbers the lane's
    real report.
    """

    if not result.is_failure:
        return None

    duration = (
        f"{result.metrics.duration_ms}ms"
        if result.metrics.duration_ms is not None
        else "unknown duration"
    )
    reason = (
        f"LANE TERMINATED - FAILURE ({result.terminal_state.value}): "
        f"{result.reason}. Observed: {result.metrics.tool_calls} tool calls in "
        f"{duration} across {result.metrics.entries} transcript entries "
        "(OMN-16471). This lane did NOT complete. Do not report it as a finished "
        "stage: re-dispatch it, or record the failure explicitly with its terminal "
        "state. A durable lane record was written; `onex-lane-reconcile` will fail "
        "while this lane is unresolved."
    )
    output: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStop",
            "additionalContext": reason,
        }
    }
    if result.blocking:
        # Both the top-level decision/reason form and the hookSpecificOutput
        # form are emitted: this repo's registered SubagentStop guards use the
        # latter, while Stop/SubagentStop blocking is documented against the
        # former. Emitting both is strictly more likely to be honored.
        output["decision"] = "block"
        output["reason"] = reason
        output["hookSpecificOutput"]["decision"] = "block"
    return output


def _cli_main() -> int:
    """Read the ``SubagentStop`` stdin JSON, classify, record, emit.

    Exit codes mirror the sibling guards: 0 = allow, 2 = block.
    """

    raw = sys.stdin.read()
    try:
        event = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        event = {}

    result = classify_lane_termination(event)
    record_termination(result)

    output = _hook_output(result)
    if output is None:
        return 0

    sys.stdout.write(json.dumps(output))
    sys.stdout.write("\n")
    sys.stderr.write(str(output.get("reason") or "") + "\n")
    return 2 if result.blocking else 0


if __name__ == "__main__":  # pragma: no cover - exercised by the shell wrapper
    raise SystemExit(_cli_main())

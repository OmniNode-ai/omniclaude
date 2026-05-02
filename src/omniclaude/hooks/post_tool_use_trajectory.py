# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PostToolUse PRM trajectory hook (OMN-10370).

After every tool call:
1. Constructs a ModelTrajectoryEntry from the tool envelope
2. Appends to trajectory_store
3. Runs all 5 PRM detectors
4. Passes matches through escalation tracker
5. Injects course-correction on severity >= 1; exits non-zero on severity == 3

CLI usage (invoked by post_tool_use_trajectory.sh):
    python3 -m omniclaude.hooks.post_tool_use_trajectory < tool_envelope.json

Exit codes:
    0 — allow (pass-through; optionally injects additionalContext)
    2 — hard stop (severity_level == 3)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

# Claude Code tool envelopes are untyped external API boundaries.
_Envelope = (
    dict[  # ONEX_EXCLUDE: dict_str_any - external/untyped Claude Code tool envelope
        str, Any
    ]
)


def _load_trajectory_store(
    session_id: str,
) -> Any:  # ONEX_EXCLUDE: any_type - lazy-loaded omnibase_core type
    from omnibase_core.agents.trajectory_store import TrajectoryStore

    return TrajectoryStore(session_id=session_id)


def _load_detectors() -> Any:  # ONEX_EXCLUDE: any_type - lazy-loaded detector callables
    from omnibase_core.agents.prm_detectors import (
        detect_context_thrash,
        detect_expansion_drift,
        detect_ping_pong,
        detect_repetition_loop,
        detect_stuck_on_test,
    )

    return [
        detect_repetition_loop,
        detect_ping_pong,
        detect_expansion_drift,
        detect_stuck_on_test,
        detect_context_thrash,
    ]


def _load_escalation_tracker(
    session_id: str,
) -> Any:  # ONEX_EXCLUDE: any_type - lazy-loaded EscalationTracker
    from omnibase_core.agents.prm_escalation import EscalationTracker

    return EscalationTracker(session_id=session_id)


def _make_trajectory_entry(
    step: int, agent: str, action: str, target: str, result: str
) -> Any:  # ONEX_EXCLUDE: any_type - lazy-loaded ModelTrajectoryEntry
    from omnibase_core.models.agents.model_trajectory_entry import ModelTrajectoryEntry

    return ModelTrajectoryEntry(
        step=step, agent=agent, action=action, target=target, result=result
    )


# Module-level singletons — lazily initialized
trajectory_store: Any = None  # ONEX_EXCLUDE: any_type - lazy-loaded TrajectoryStore
_last_processed_step: int = 0


def _get_store(
    session_id: str,
) -> Any:  # ONEX_EXCLUDE: any_type - lazy-loaded TrajectoryStore
    global trajectory_store
    if trajectory_store is None:
        trajectory_store = _load_trajectory_store(session_id)
    return trajectory_store


def _extract_target(tool_name: str, tool_input: _Envelope) -> str:
    for key in ("file_path", "path", "command", "query", "subject", "prompt"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            return val
    for val in tool_input.values():
        if isinstance(val, str) and val:
            return val
    return ""


def _extract_result(tool_response: _Envelope) -> str:
    if tool_response.get("error"):
        return "error"
    return "ok"


def build_trajectory_entry(
    step: int,
    envelope: _Envelope,
) -> (
    Any  # ONEX_EXCLUDE: any_type - return type is ModelTrajectoryEntry, concrete at runtime
):
    """Construct a ModelTrajectoryEntry from a PostToolUse envelope."""
    session_id: str = (
        envelope.get("sessionId") or envelope.get("session_id") or "unknown"
    )
    tool_name: str = envelope.get("tool_name") or "unknown"
    tool_input: _Envelope = envelope.get("tool_input") or {}
    tool_response: _Envelope = envelope.get("tool_response") or {}

    target = _extract_target(tool_name, tool_input)
    result = _extract_result(tool_response)

    return _make_trajectory_entry(
        step=step,
        agent=session_id,
        action=tool_name,
        target=target,
        result=result,
    )


def _run_detectors(
    entries: list[Any],  # ONEX_EXCLUDE: any_type - PRM entry type concrete at runtime
    last_processed_step: int,
) -> list[Any]:  # ONEX_EXCLUDE: any_type - PRM match type concrete at runtime
    """Run all 5 PRM pattern detectors and aggregate results."""
    detectors = _load_detectors()
    matches: list[Any] = []  # ONEX_EXCLUDE: any_type - PRM match type concrete at runtime  # fmt: skip
    for detector in detectors:
        matches.extend(detector(entries, last_processed_step=last_processed_step))
    return matches


def _escalate_matches(
    matches: list[Any],  # ONEX_EXCLUDE: any_type - PRM match type concrete at runtime
    session_id: str,
) -> list[
    Any  # ONEX_EXCLUDE: any_type - PRM escalation result type concrete at runtime
]:
    """Pass PRM matches through the escalation tracker, return escalation results."""
    tracker = _load_escalation_tracker(session_id)
    results = []
    for match in matches:
        result = tracker.process(match)
        results.append(result)
    return results


@dataclass
class HookResult:
    exit_code: int
    additional_context: str | None


def process_tool_envelope(envelope: _Envelope, step: int) -> HookResult:
    """Core hook logic: append entry, detect patterns, escalate, return result."""
    global _last_processed_step

    session_id: str = (
        envelope.get("sessionId") or envelope.get("session_id") or "unknown"
    )
    store = _get_store(session_id)

    entry = build_trajectory_entry(step=step, envelope=envelope)
    store.append(entry)

    entries = store.read_recent(200)
    matches = _run_detectors(entries, last_processed_step=_last_processed_step)
    escalation_results = _escalate_matches(matches, session_id=session_id)

    if not escalation_results:
        return HookResult(exit_code=0, additional_context=None)

    max_severity = max(r.severity_level for r in escalation_results)
    _last_processed_step = step

    corrections = "\n\n".join(r.course_correction for r in escalation_results)

    if max_severity >= 3:
        return HookResult(exit_code=2, additional_context=corrections)

    return HookResult(exit_code=0, additional_context=corrections)


def main() -> int:
    raw = sys.stdin.read()
    try:
        envelope = json.loads(raw)
    except json.JSONDecodeError:
        print(raw, end="")  # noqa: T201
        return 0

    store = _get_store(
        envelope.get("sessionId") or envelope.get("session_id") or "unknown"
    )
    step = len(store.read_recent(10000)) + 1

    result = process_tool_envelope(envelope, step=step)

    if result.additional_context:
        output = dict(envelope)
        output.setdefault("hookSpecificOutput", {})
        existing = output["hookSpecificOutput"].get("additionalContext", "")
        if existing:
            output["hookSpecificOutput"]["additionalContext"] = (
                existing + "\n\n" + result.additional_context
            )
        else:
            output["hookSpecificOutput"]["additionalContext"] = (
                result.additional_context
            )
        output["hookSpecificOutput"]["hookEventName"] = "PostToolUse"
        print(json.dumps(output))  # noqa: T201
    else:
        print(raw, end="")  # noqa: T201

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())

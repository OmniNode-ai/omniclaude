"""FixTransition detection and Kafka emission for the Agent Trace system.

A FixTransition is detected when a new ChangeFrame (with outcome=pass) resolves
a previously open failure within the same trace session. The transition captures
which failure was fixed, which frames were involved, and what diff produced the fix.

FixTransitions are:
1. Persisted to the fix_transitions table (via TRACE-02 DDL)
2. Emitted to Kafka topic 'onex.evt.omniclaude.fix-transition.v1' (non-blocking)

Design constraints:
- detect_fix_transition() is pure logic, no I/O (testable without DB)
- emit_fix_transition_event() is the I/O boundary (mocked in tests)
- Kafka emission follows the hook pattern: non-blocking, data loss acceptable

Stage 7 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from omniclaude.trace.change_frame import ChangeFrame

# ---------------------------------------------------------------------------
# FixTransition model
# ---------------------------------------------------------------------------


class FixTransition(BaseModel):
    """Record of a failure→success transition between two ChangeFrames.

    Immutable after creation — emitted to Kafka and persisted to DB.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    transition_id: UUID
    failure_signature_id: str  # Which failure class was resolved
    initial_frame_id: UUID  # First frame with this failure signature
    success_frame_id: UUID  # First frame where failure is gone
    delta_hash: str  # SHA-256 of the fix diff (diff between frames)
    files_involved: list[str]  # Files that changed between initial and success frames


# ---------------------------------------------------------------------------
# In-memory "database" type for pure detection logic
# (In production, this would be a DB query; for tests, a list of frames)
# ---------------------------------------------------------------------------


@dataclass
class OpenFailure:
    """An unresolved failure frame tracked for transition detection."""

    frame_id: UUID
    trace_id: str
    failure_signature_id: str
    diff_patch: str
    files_changed: list[str]
    already_resolved: bool = False


# ---------------------------------------------------------------------------
# Fix diff helpers
# ---------------------------------------------------------------------------


def compute_fix_diff_hash(initial_patch: str, success_patch: str) -> str:
    """Compute a stable SHA-256 hash representing the diff-of-diffs.

    Combines both patches in a deterministic way to produce a unique
    fingerprint for the fix transformation.

    Args:
        initial_patch: Unified diff from the failing frame
        success_patch: Unified diff from the succeeding frame

    Returns:
        SHA-256 hash string (64 hex chars)
    """
    combined = f"INITIAL:\n{initial_patch}\nSUCCESS:\n{success_patch}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def extract_unique_files(
    initial_files: list[str],
    success_files: list[str],
) -> list[str]:
    """Return the union of files changed across both frames, deduplicated.

    Args:
        initial_files: Files changed in the initial (failing) frame
        success_files: Files changed in the success frame

    Returns:
        Sorted, deduplicated list of file paths
    """
    combined = set(initial_files) | set(success_files)
    return sorted(combined)


# ---------------------------------------------------------------------------
# Core detection function (pure logic, no I/O)
# ---------------------------------------------------------------------------


def detect_fix_transition(
    new_frame: ChangeFrame,
    open_failures: list[OpenFailure],
) -> FixTransition | None:
    """Detect if a new passing frame resolves an open failure in the same session.

    Algorithm:
    1. If new_frame.outcome.status != "pass" → return None
    2. Find open failures with same trace_id that are not already resolved
    3. If found: take the first (chronologically earliest) open failure
    4. Compute fix diff hash and files involved
    5. Return FixTransition

    Args:
        new_frame: The newly persisted ChangeFrame
        open_failures: List of known open failures from the same session
            (caller is responsible for filtering by trace_id and resolved status)

    Returns:
        FixTransition if a resolution is detected, None otherwise
    """
    # Only passing frames can resolve a failure
    if new_frame.outcome.status != "pass":
        return None

    # Find unresolved failures in the same trace session
    same_session_failures = [
        f
        for f in open_failures
        if f.trace_id == new_frame.trace_id and not f.already_resolved
    ]

    if not same_session_failures:
        return None

    # Take the chronologically first open failure (caller sorts by timestamp)
    initial_failure = same_session_failures[0]

    # Compute fix fingerprint
    delta_hash = compute_fix_diff_hash(
        initial_failure.diff_patch,
        new_frame.delta.diff_patch,
    )

    # Collect all files involved in the fix
    files_involved = extract_unique_files(
        initial_failure.files_changed,
        new_frame.delta.files_changed,
    )

    return FixTransition(
        transition_id=uuid4(),
        failure_signature_id=initial_failure.failure_signature_id,
        initial_frame_id=initial_failure.frame_id,
        success_frame_id=new_frame.frame_id,
        delta_hash=delta_hash,
        files_involved=files_involved,
    )


# ---------------------------------------------------------------------------
# Kafka event serialization
# ---------------------------------------------------------------------------


#: Kafka topic for fix transition events (ONEX naming: onex.{kind}.{producer}.{event}.v{n})
FIX_TRANSITION_TOPIC: Literal["onex.evt.omniclaude.fix-transition.v1"] = (
    "onex.evt.omniclaude.fix-transition.v1"
)


def serialize_fix_transition_event(
    transition: FixTransition,
    failure_type: str,
    primary_signal: str,
    timestamp_utc: str,
) -> str:
    """Serialize a FixTransition to a JSON Kafka event payload.

    Args:
        transition: The FixTransition to serialize
        failure_type: Failure classification (e.g. "test_fail", "lint_fail")
        primary_signal: Primary error signal from the failure signature
        timestamp_utc: ISO-8601 UTC timestamp (explicitly injected)

    Returns:
        JSON string suitable for Kafka emission
    """
    payload = {
        "event_type": "fix_transition",
        "transition_id": str(transition.transition_id),
        "failure_signature_id": transition.failure_signature_id,
        "initial_frame_id": str(transition.initial_frame_id),
        "success_frame_id": str(transition.success_frame_id),
        "delta_hash": transition.delta_hash,
        "files_involved": transition.files_involved,
        "failure_type": failure_type,
        "primary_signal": primary_signal,
        "timestamp": timestamp_utc,
    }
    return json.dumps(payload, separators=(",", ":"))


#: Type alias for the Kafka emit callable: (topic, payload) → success bool
type EmitCallable = Callable[[str, str], bool]


def emit_fix_transition_event(
    transition: FixTransition,
    failure_type: str,
    primary_signal: str,
    timestamp_utc: str,
    emit_fn: EmitCallable,
) -> bool:
    """Emit a FixTransition event to Kafka via the provided emit function.

    Non-blocking by design — follows the hook emit pattern. Data loss is
    acceptable; the fix_transitions table provides the durable record.

    Args:
        transition: The FixTransition to emit
        failure_type: Failure classification for the event payload
        primary_signal: Primary error signal from the failure signature
        timestamp_utc: ISO-8601 UTC timestamp (explicitly injected)
        emit_fn: Callable(topic, payload) → bool (True=success, False=dropped)

    Returns:
        True if emitted successfully, False if dropped (non-blocking behavior)
    """
    payload = serialize_fix_transition_event(
        transition,
        failure_type=failure_type,
        primary_signal=primary_signal,
        timestamp_utc=timestamp_utc,
    )
    try:
        return emit_fn(FIX_TRANSITION_TOPIC, payload)
    except Exception:  # noqa: BLE001 — emit errors must never propagate to caller
        return False

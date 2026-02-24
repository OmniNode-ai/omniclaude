# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""FixTransition integration with OmniIntelligence and ContextScoring.

This module provides the omniclaude-side wiring that converts FixTransitions
into structured learning artifacts for OmniIntelligence:

1. ContextItem construction — converts a FixTransition into a FAILURE_PATTERN
   ContextItem for injection into OmniIntelligence's context retrieval system.

2. Scoring functions — pure functions that compute attribution signals:
   - score_file_touched_match: boost files touched in prior fix transitions
   - score_failure_signature_match: boost frames with matching failure sigs

3. Pattern promotion — detects when the same fix has been applied ≥ N times,
   signalling an automation candidate.

4. Event dispatch — parse a raw Kafka event payload (from TRACE-07's
   agent-trace-fix-transitions topic) and drive the integration pipeline.

Design constraints:
- All core functions are pure (no I/O) — testable without DB or Kafka
- I/O boundaries (DB lookup, context store) are injected callables
- No direct Kafka imports (ARCH-002 cross-repo guard)
- Kafka is consumed via the emit pattern; never blocked on

Stage 9 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from omniclaude.trace.fix_transition import FIX_TRANSITION_TOPIC, FixTransition

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum number of identical FixTransitions before promotion is flagged.
PATTERN_PROMOTION_THRESHOLD: int = 3

#: Score boost per historical fix touching a candidate file (capped at 1.0).
FILE_TOUCHED_MATCH_SCORE_PER_FIX: float = 0.2

#: Maximum FILE_TOUCHED_MATCH score (capped to prevent oversaturation).
FILE_TOUCHED_MATCH_MAX_SCORE: float = 1.0

#: Literal context item type emitted to OmniIntelligence.
CONTEXT_ITEM_TYPE: Literal["FAILURE_PATTERN"] = "FAILURE_PATTERN"


# ---------------------------------------------------------------------------
# ContextItem — the artifact sent to OmniIntelligence
# ---------------------------------------------------------------------------


class ContextItem(BaseModel):
    """Structured artifact for OmniIntelligence context injection.

    One ContextItem is produced per FixTransition. OmniIntelligence stores
    these items and retrieves them when an agent encounters the same failure
    signature in a future session.

    Immutable after creation — the item represents a point-in-time event.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    item_type: Literal["FAILURE_PATTERN"]
    content: str  # Human-readable fix summary for context injection
    failure_signature_id: str  # Which failure class was resolved
    failure_type: str  # e.g. "test_fail", "lint_fail"
    delta_hash: str  # SHA-256 fingerprint of the fix diff
    files_involved: list[str]  # Files that changed to achieve the fix
    initial_frame_id: str  # UUID string — frame where failure first appeared
    success_frame_id: str  # UUID string — frame where failure was resolved
    primary_signal: str  # Primary error signal (e.g. "AssertionError", "E501")


# ---------------------------------------------------------------------------
# PatternPromotionCandidate — returned when promotion threshold is reached
# ---------------------------------------------------------------------------


class PatternPromotionCandidate(BaseModel):
    """Signals that a recurring fix pattern is eligible for promotion.

    When the same delta_hash has resolved the same failure_signature_id
    PATTERN_PROMOTION_THRESHOLD or more times, OmniIntelligence should
    consider naming this pattern and alerting for automation.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)

    failure_signature_id: str
    delta_hash: str
    occurrence_count: int
    files_involved: list[str]
    promotion_message: str


# ---------------------------------------------------------------------------
# FixTransitionEvent — parsed Kafka payload
# ---------------------------------------------------------------------------


@dataclass
class FixTransitionEvent:
    """Parsed representation of a Kafka event from FIX_TRANSITION_TOPIC.

    Produced by parse_fix_transition_event(); consumed by
    process_fix_transition_event().
    """

    transition_id: str
    failure_signature_id: str
    initial_frame_id: str
    success_frame_id: str
    delta_hash: str
    files_involved: list[str]
    failure_type: str
    primary_signal: str
    timestamp: str


# ---------------------------------------------------------------------------
# Pure function: build_context_item_from_fix_transition
# ---------------------------------------------------------------------------


def build_context_item_from_fix_transition(
    fix_transition: FixTransition,
    failure_type: str,
    primary_signal: str,
) -> ContextItem:
    """Construct a ContextItem from a FixTransition.

    Args:
        fix_transition: The resolved FixTransition.
        failure_type: Classification of the failure (e.g. "test_fail").
        primary_signal: Human-readable primary error signal (e.g. "AssertionError").

    Returns:
        ContextItem of type FAILURE_PATTERN ready for OmniIntelligence injection.
    """
    files_str = ", ".join(fix_transition.files_involved)
    content = (
        f"Fix for {primary_signal}: changed {files_str}"
        if fix_transition.files_involved
        else f"Fix for {primary_signal}"
    )

    return ContextItem(
        item_type=CONTEXT_ITEM_TYPE,
        content=content,
        failure_signature_id=fix_transition.failure_signature_id,
        failure_type=failure_type,
        delta_hash=fix_transition.delta_hash,
        files_involved=fix_transition.files_involved,
        initial_frame_id=str(fix_transition.initial_frame_id),
        success_frame_id=str(fix_transition.success_frame_id),
        primary_signal=primary_signal,
    )


# ---------------------------------------------------------------------------
# Pure function: score_file_touched_match
# ---------------------------------------------------------------------------


def score_file_touched_match(
    candidate_file: str,
    historical_fix_count: int,
) -> float:
    """Compute FILE_TOUCHED_MATCH score boost for a candidate file.

    Files that have appeared in prior fix transitions for the same failure
    signature get a retrieval score boost. This directs agent attention to
    the files most likely to contain the fix.

    Args:
        candidate_file: File path being evaluated for context injection.
            (Parameter is unused in score calculation — score depends only on
            how many times this file appeared in historical transitions.
            Callers look up historical_fix_count from the DB.)
        historical_fix_count: Number of prior FixTransitions that involved
            this file for the current failure_signature_id.

    Returns:
        Score in [0.0, 1.0]. Returns 0.0 for files with no prior fix history.
    """
    _ = candidate_file  # score is based on count, not the file name itself
    if historical_fix_count <= 0:
        return 0.0
    raw = historical_fix_count * FILE_TOUCHED_MATCH_SCORE_PER_FIX
    return min(raw, FILE_TOUCHED_MATCH_MAX_SCORE)


# ---------------------------------------------------------------------------
# Pure function: score_failure_signature_match
# ---------------------------------------------------------------------------


def score_failure_signature_match(
    current_failure_signature_id: str | None,
    context_item_failure_signature_id: str,
) -> float:
    """Compute failure_signature_match attribution signal.

    Returns 1.0 when the current agent session's failure signature matches
    the ContextItem's failure_signature_id, 0.0 otherwise.

    Args:
        current_failure_signature_id: The active failure signature in this
            agent session (None if no active failure).
        context_item_failure_signature_id: The failure_signature_id recorded
            in the ContextItem being evaluated.

    Returns:
        1.0 if signatures match, 0.0 otherwise.
    """
    if current_failure_signature_id is None:
        return 0.0
    return (
        1.0
        if current_failure_signature_id == context_item_failure_signature_id
        else 0.0
    )


# ---------------------------------------------------------------------------
# Pure function: check_pattern_promotion
# ---------------------------------------------------------------------------


def check_pattern_promotion(
    failure_signature_id: str,
    delta_hash: str,
    occurrence_count: int,
    files_involved: list[str],
    threshold: int = PATTERN_PROMOTION_THRESHOLD,
) -> PatternPromotionCandidate | None:
    """Check whether a recurring fix pattern has crossed the promotion threshold.

    When the same delta_hash has been applied to resolve the same failure
    signature at least `threshold` times, the pattern is a promotion candidate.
    OmniIntelligence should name this pattern and alert for automation.

    Args:
        failure_signature_id: The failure class being checked.
        delta_hash: The fix diff fingerprint (same fix applied repeatedly).
        occurrence_count: How many FixTransitions share this signature + delta_hash.
        files_involved: Files touched by the canonical fix.
        threshold: Minimum occurrences before promotion (default: 3).

    Returns:
        PatternPromotionCandidate if threshold reached, None otherwise.
    """
    if occurrence_count < threshold:
        return None

    message = (
        f"Failure class '{failure_signature_id}' has been fixed {occurrence_count} times "
        f"with the same delta (hash: {delta_hash[:12]}…). "
        f"Files: {', '.join(files_involved)}. "
        f"Consider automating this fix pattern."
    )

    return PatternPromotionCandidate(
        failure_signature_id=failure_signature_id,
        delta_hash=delta_hash,
        occurrence_count=occurrence_count,
        files_involved=files_involved,
        promotion_message=message,
    )


# ---------------------------------------------------------------------------
# Parsing: raw Kafka event payload → FixTransitionEvent
# ---------------------------------------------------------------------------


def parse_fix_transition_event(payload: str) -> FixTransitionEvent | None:
    """Parse a raw Kafka payload string into a FixTransitionEvent.

    Args:
        payload: JSON string from the agent-trace-fix-transitions topic.

    Returns:
        FixTransitionEvent if the payload is valid, None if malformed.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return None

    required = [
        "event_type",
        "transition_id",
        "failure_signature_id",
        "initial_frame_id",
        "success_frame_id",
        "delta_hash",
        "files_involved",
        "failure_type",
        "primary_signal",
        "timestamp",
    ]
    for key in required:
        if key not in data:
            return None

    if data.get("event_type") != "fix_transition":
        return None

    files = data["files_involved"]
    if not isinstance(files, list):
        return None

    return FixTransitionEvent(
        transition_id=str(data["transition_id"]),
        failure_signature_id=str(data["failure_signature_id"]),
        initial_frame_id=str(data["initial_frame_id"]),
        success_frame_id=str(data["success_frame_id"]),
        delta_hash=str(data["delta_hash"]),
        files_involved=[str(f) for f in files],
        failure_type=str(data["failure_type"]),
        primary_signal=str(data["primary_signal"]),
        timestamp=str(data["timestamp"]),
    )


# ---------------------------------------------------------------------------
# Type aliases for injectable I/O callables
# ---------------------------------------------------------------------------

#: Stores a ContextItem in OmniIntelligence. Returns True on success.
type StoreContextItemFn = Callable[[ContextItem], bool]

#: Looks up how many prior FixTransitions involved a file for a given sig.
#: Callable(failure_signature_id, candidate_file) -> count
type LookupFileTouchCountFn = Callable[[str, str], int]

#: Looks up the occurrence count of a specific delta_hash for a signature.
#: Callable(failure_signature_id, delta_hash) -> count
type LookupOccurrenceCountFn = Callable[[str, str], int]

#: Handles a PatternPromotionCandidate (e.g. alerts, stores record).
type HandlePromotionFn = Callable[[PatternPromotionCandidate], None]


# ---------------------------------------------------------------------------
# Integration pipeline: process a single fix transition event
# ---------------------------------------------------------------------------


@dataclass
class FixTransitionProcessingResult:
    """Result of processing a single fix transition event through the pipeline."""

    event: FixTransitionEvent
    context_item: ContextItem
    context_item_stored: bool
    promotion_candidate: PatternPromotionCandidate | None
    errors: list[str] = field(default_factory=list)


def process_fix_transition_event(
    payload: str,
    store_context_item: StoreContextItemFn,
    lookup_occurrence_count: LookupOccurrenceCountFn,
    handle_promotion: HandlePromotionFn | None = None,
    promotion_threshold: int = PATTERN_PROMOTION_THRESHOLD,
) -> FixTransitionProcessingResult | None:
    """Process a single fix transition Kafka event through the integration pipeline.

    Steps:
    1. Parse the raw JSON payload
    2. Build a ContextItem (FAILURE_PATTERN) for OmniIntelligence
    3. Store the ContextItem via the injected store function
    4. Check pattern promotion threshold
    5. If promoted: call handle_promotion (if provided)

    Args:
        payload: Raw JSON string from agent-trace-fix-transitions topic.
        store_context_item: Callable that persists the ContextItem.
        lookup_occurrence_count: Callable that returns how many prior
            FixTransitions share the same (failure_signature_id, delta_hash).
        handle_promotion: Optional callable for promotion alerts.
        promotion_threshold: Minimum occurrences for promotion.

    Returns:
        FixTransitionProcessingResult if payload is valid, None if malformed.
    """
    event = parse_fix_transition_event(payload)
    if event is None:
        return None

    errors: list[str] = []

    # Step 2: Build ContextItem
    # Reconstruct a minimal FixTransition from the event for building the item
    try:
        fix_transition = FixTransition(
            transition_id=UUID(event.transition_id),
            failure_signature_id=event.failure_signature_id,
            initial_frame_id=UUID(event.initial_frame_id),
            success_frame_id=UUID(event.success_frame_id),
            delta_hash=event.delta_hash,
            files_involved=event.files_involved,
        )
        context_item = build_context_item_from_fix_transition(
            fix_transition,
            failure_type=event.failure_type,
            primary_signal=event.primary_signal,
        )
    except Exception as exc:  # noqa: BLE001 — surface but don't propagate
        errors.append(f"Failed to build ContextItem: {exc}")
        # Return early — can't proceed without the ContextItem
        return FixTransitionProcessingResult(
            event=event,
            context_item=ContextItem(
                item_type=CONTEXT_ITEM_TYPE,
                content="",
                failure_signature_id=event.failure_signature_id,
                failure_type=event.failure_type,
                delta_hash=event.delta_hash,
                files_involved=event.files_involved,
                initial_frame_id=event.initial_frame_id,
                success_frame_id=event.success_frame_id,
                primary_signal=event.primary_signal,
            ),
            context_item_stored=False,
            promotion_candidate=None,
            errors=errors,
        )

    # Step 3: Store ContextItem
    try:
        stored = store_context_item(context_item)
    except Exception as exc:  # noqa: BLE001 — emit errors must never propagate
        stored = False
        errors.append(f"Failed to store ContextItem: {exc}")

    # Step 4: Check pattern promotion
    promotion_candidate: PatternPromotionCandidate | None = None
    try:
        count = lookup_occurrence_count(event.failure_signature_id, event.delta_hash)
        promotion_candidate = check_pattern_promotion(
            failure_signature_id=event.failure_signature_id,
            delta_hash=event.delta_hash,
            occurrence_count=count,
            files_involved=event.files_involved,
            threshold=promotion_threshold,
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"Failed to check promotion: {exc}")

    # Step 5: Handle promotion
    if promotion_candidate is not None and handle_promotion is not None:
        try:
            handle_promotion(promotion_candidate)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"Failed to handle promotion: {exc}")

    return FixTransitionProcessingResult(
        event=event,
        context_item=context_item,
        context_item_stored=stored,
        promotion_candidate=promotion_candidate,
        errors=errors,
    )


# ---------------------------------------------------------------------------
# Topic constant re-export (for consumer configuration)
# ---------------------------------------------------------------------------

#: Topic to consume from for fix transition events (re-exported for convenience).
FIX_TRANSITION_CONSUMER_TOPIC: str = FIX_TRANSITION_TOPIC

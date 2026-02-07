#!/usr/bin/env python3
"""Guardrail logic for routing feedback reinforcement.

Gates whether a session's routing decision should be used to reinforce
the routing model. Prevents learning from noise by requiring:
    1. Context injection actually occurred (no injection = no signal)
    2. Clear session outcome (success or failed, not abandoned/unknown)
    3. Minimum utilization AND accuracy thresholds met

All functions are pure — no network calls, no datetime.now(), no side effects.

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

import math
from typing import NamedTuple

# =============================================================================
# Constants
# =============================================================================

# Minimum utilization score to consider feedback signal meaningful.
# Below this, the injected context was barely used — unreliable signal.
MIN_UTILIZATION_THRESHOLD: float = 0.2

# Minimum agent match score to consider feedback signal meaningful.
# Below this, the agent selection was essentially random — unreliable signal.
MIN_ACCURACY_THRESHOLD: float = 0.5

# Skip reason constants for observability and Slack messaging.
SKIP_NO_INJECTION = "NO_INJECTION"
SKIP_UNCLEAR_OUTCOME = "UNCLEAR_OUTCOME"
SKIP_LOW_UTILIZATION_AND_ACCURACY = "LOW_UTILIZATION_AND_ACCURACY"

# Outcomes that provide a clear signal for reinforcement.
CLEAR_OUTCOMES: frozenset[str] = frozenset({"success", "failed"})


# =============================================================================
# Result Type
# =============================================================================


class GuardrailResult(NamedTuple):
    """Result of guardrail evaluation."""

    should_reinforce: bool  # Whether to emit routing.feedback
    skip_reason: str | None  # Why reinforcement was skipped (None if should_reinforce)
    details: dict[str, object]  # Diagnostic details for logging


# =============================================================================
# Core Logic
# =============================================================================


def should_reinforce_routing(
    injection_occurred: bool,
    utilization_score: float,
    agent_match_score: float,
    session_outcome: str,
) -> GuardrailResult:
    """Evaluate whether routing feedback should be recorded.

    Gates are evaluated in order (cheapest first). As soon as a gate
    fails, we short-circuit with the appropriate skip reason.

    Args:
        injection_occurred: Whether context injection happened this session.
        utilization_score: 0.0-1.0 ratio of injected identifiers reused.
        agent_match_score: 0.0-1.0 graded accuracy of agent selection.
        session_outcome: One of: success, failed, abandoned, unknown.

    Returns:
        GuardrailResult with decision, skip reason, and diagnostic details.
    """
    # Clamp scores to valid range; treat NaN as 0.0 (no signal)
    if math.isnan(utilization_score) or math.isinf(utilization_score):
        utilization_score = 0.0
    else:
        utilization_score = max(0.0, min(1.0, utilization_score))

    if math.isnan(agent_match_score) or math.isinf(agent_match_score):
        agent_match_score = 0.0
    else:
        agent_match_score = max(0.0, min(1.0, agent_match_score))

    details: dict[str, object] = {
        "injection_occurred": injection_occurred,
        "utilization_score": utilization_score,
        "agent_match_score": agent_match_score,
        "session_outcome": session_outcome,
    }

    # Gate 1: Must have injected context (no injection = no feedback signal)
    if not injection_occurred:
        return GuardrailResult(
            should_reinforce=False,
            skip_reason=SKIP_NO_INJECTION,
            details=details,
        )

    # Gate 2: Must have clear outcome (success or failed)
    if session_outcome not in CLEAR_OUTCOMES:
        return GuardrailResult(
            should_reinforce=False,
            skip_reason=SKIP_UNCLEAR_OUTCOME,
            details=details,
        )

    # Gate 3: Utilization AND accuracy must meet minimums
    if utilization_score < MIN_UTILIZATION_THRESHOLD or agent_match_score < MIN_ACCURACY_THRESHOLD:
        return GuardrailResult(
            should_reinforce=False,
            skip_reason=SKIP_LOW_UTILIZATION_AND_ACCURACY,
            details=details,
        )

    # All gates passed — reinforce
    return GuardrailResult(
        should_reinforce=True,
        skip_reason=None,
        details=details,
    )


__all__ = [
    # Constants
    "CLEAR_OUTCOMES",
    "MIN_ACCURACY_THRESHOLD",
    "MIN_UTILIZATION_THRESHOLD",
    "SKIP_LOW_UTILIZATION_AND_ACCURACY",
    "SKIP_NO_INJECTION",
    "SKIP_UNCLEAR_OUTCOME",
    # Types
    "GuardrailResult",
    # Functions
    "should_reinforce_routing",
]

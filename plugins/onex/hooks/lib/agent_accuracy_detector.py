#!/usr/bin/env python3
"""Graded accuracy scoring for agent selection.

Evaluates how well the selected agent matches the session's actual signals
by comparing the agent's activation patterns against observed context.

Scoring method: weighted overlap between agent trigger patterns and session
signals (tool names, file paths, keywords). Returns a 0.0-1.0 score.

All functions are pure — no network calls, no datetime.now(), no side effects.

Part of OMN-1892: Add feedback loop with guardrails.
"""

from __future__ import annotations

from typing import NamedTuple

# =============================================================================
# Result Type
# =============================================================================


class AgentMatchResult(NamedTuple):
    """Result of agent accuracy detection."""

    score: float  # 0.0-1.0 accuracy score
    method: str  # Scoring method used
    matched_triggers: list[str]  # Which triggers matched
    total_triggers: int  # Total triggers evaluated


# =============================================================================
# Core Logic
# =============================================================================


def calculate_agent_match_score(
    selected_agent: str,
    agent_triggers: list[str],
    context_signals: list[str],
) -> AgentMatchResult:
    """Calculate how well the selected agent matches session context.

    Compares the agent's activation triggers (from YAML) against the actual
    context signals observed during the session (tool names used, file paths
    modified, keywords from prompts).

    Scoring:
        score = matched_triggers / total_triggers
        If no triggers defined, score = 0.0 (no signal).

    Args:
        selected_agent: Name of the agent that was selected (for logging).
        agent_triggers: Activation patterns from the agent's YAML config
            (explicit_triggers + context_triggers).
        context_signals: Observed session signals (tool names, file paths,
            prompt keywords, etc.). Should be lowercase for comparison.

    Returns:
        AgentMatchResult with score, method, and match details.
    """
    if not agent_triggers:
        return AgentMatchResult(
            score=0.0,
            method="no_triggers",
            matched_triggers=[],
            total_triggers=0,
        )

    # Normalize signals for case-insensitive comparison
    signals_lower = {s.lower() for s in context_signals}
    signals_joined = " ".join(signals_lower)

    matched: list[str] = []
    for trigger in agent_triggers:
        trigger_lower = trigger.lower()
        # Check if trigger appears as substring in any signal
        if trigger_lower in signals_joined:
            matched.append(trigger)

    total = len(agent_triggers)
    score = len(matched) / total if total > 0 else 0.0

    return AgentMatchResult(
        score=score,
        method="trigger_overlap",
        matched_triggers=matched,
        total_triggers=total,
    )


__all__ = [
    # Types
    "AgentMatchResult",
    # Functions
    "calculate_agent_match_score",
]

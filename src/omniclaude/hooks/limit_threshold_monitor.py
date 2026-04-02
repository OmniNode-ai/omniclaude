# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Limit threshold monitor for session checkpoint decisions.

Compares current limit status against configurable thresholds and returns
a structured decision about whether to checkpoint. Pure compute — no IO.

Priority order: context > session > weekly (context exhaustion is the
hardest stop; weekly is the most gradual degradation).

See Also:
    - ``statusline_parser.py`` for limit data extraction (OMN-7284)
    - ``model_session_checkpoint.py`` for ``EnumCheckpointReason`` (OMN-7283)
    - ``handler_session_limit_transfer.py`` for acting on decisions (OMN-7290)
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.model_session_checkpoint import EnumCheckpointReason
from omniclaude.hooks.statusline_parser import ModelLimitStatus


class ModelLimitThresholds(BaseModel):
    """Configurable thresholds for checkpoint triggers.

    Each limit type has a ``warn`` and ``critical`` threshold. Warn indicates
    the system should prepare for a checkpoint; critical means checkpoint now.

    Attributes:
        context_warn: Context % at which to warn (default 80).
        context_critical: Context % at which to checkpoint immediately (default 90).
        session_warn: Session % at which to warn (default 85).
        session_critical: Session % at which to checkpoint immediately (default 95).
        weekly_warn: Weekly % at which to warn (default 80).
        weekly_critical: Weekly % at which to checkpoint immediately (default 90).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_warn: int = Field(default=80, ge=0, le=100)
    context_critical: int = Field(default=90, ge=0, le=100)
    session_warn: int = Field(default=85, ge=0, le=100)
    session_critical: int = Field(default=95, ge=0, le=100)
    weekly_warn: int = Field(default=80, ge=0, le=100)
    weekly_critical: int = Field(default=90, ge=0, le=100)


class ModelCheckpointDecision(BaseModel):
    """Result of threshold evaluation.

    Attributes:
        should_checkpoint: Whether a checkpoint should be triggered.
        reason: The limit type that triggered the decision.
        urgency: ``none``, ``warn``, or ``critical``.
        message: Human-readable explanation of the decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    should_checkpoint: bool = Field(default=False)
    reason: EnumCheckpointReason | None = Field(default=None)
    urgency: str = Field(default="none")
    message: str = Field(default="")


def evaluate_limits(
    status: ModelLimitStatus,
    thresholds: ModelLimitThresholds | None = None,
) -> ModelCheckpointDecision:
    """Evaluate current limits against thresholds.

    Checks limits in priority order: context > session > weekly.
    Returns the first triggered threshold (critical takes priority over warn
    for the same limit type).

    Args:
        status: Current limit status from ``read_limit_status()``.
        thresholds: Custom thresholds. Defaults to ``ModelLimitThresholds()``.

    Returns:
        A ``ModelCheckpointDecision`` indicating whether to checkpoint.
    """
    t = thresholds or ModelLimitThresholds()

    # Check context (highest priority — hardest stop)
    if status.context_percent is not None:
        if status.context_percent >= t.context_critical:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.CONTEXT_LIMIT,
                urgency="critical",
                message=(
                    f"Context at {status.context_percent}% "
                    f"(critical threshold: {t.context_critical}%)"
                ),
            )
        if status.context_percent >= t.context_warn:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.CONTEXT_LIMIT,
                urgency="warn",
                message=(
                    f"Context at {status.context_percent}% "
                    f"(warn threshold: {t.context_warn}%)"
                ),
            )

    # Check session (five-hour limit)
    if status.session_percent is not None:
        if status.session_percent >= t.session_critical:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.SESSION_LIMIT,
                urgency="critical",
                message=(
                    f"Session at {status.session_percent}% "
                    f"(critical threshold: {t.session_critical}%)"
                ),
            )
        if status.session_percent >= t.session_warn:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.SESSION_LIMIT,
                urgency="warn",
                message=(
                    f"Session at {status.session_percent}% "
                    f"(warn threshold: {t.session_warn}%)"
                ),
            )

    # Check weekly (most gradual)
    if status.weekly_percent is not None:
        if status.weekly_percent >= t.weekly_critical:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.WEEKLY_LIMIT,
                urgency="critical",
                message=(
                    f"Weekly at {status.weekly_percent}% "
                    f"(critical threshold: {t.weekly_critical}%)"
                ),
            )
        if status.weekly_percent >= t.weekly_warn:
            return ModelCheckpointDecision(
                should_checkpoint=True,
                reason=EnumCheckpointReason.WEEKLY_LIMIT,
                urgency="warn",
                message=(
                    f"Weekly at {status.weekly_percent}% "
                    f"(warn threshold: {t.weekly_warn}%)"
                ),
            )

    return ModelCheckpointDecision(
        should_checkpoint=False,
        reason=None,
        urgency="none",
        message="All limits within safe range",
    )


__all__ = [
    "ModelCheckpointDecision",
    "ModelLimitThresholds",
    "evaluate_limits",
]

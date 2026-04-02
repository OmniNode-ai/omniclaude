# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session limit transfer handler — graceful handoff when limits approach.

Evaluates current limit status and determines the appropriate transfer action:

| Condition              | Action                                      |
|------------------------|---------------------------------------------|
| Context >= critical    | Checkpoint + exit (watchdog resumes)        |
| Session >= critical    | Checkpoint + exit (watchdog resumes)        |
| Weekly >= warn + active| Switch to cheaper model (haiku)             |
| Weekly >= critical     | Transfer to local LLMs only (degraded)      |
| All limits OK          | No action                                   |

This handler is the top-level orchestrator that combines the limit threshold
monitor with concrete transfer actions. It does NOT write checkpoints itself
— callers must use ``SessionCheckpointWriter`` when the action requires it.

See Also:
    - ``limit_threshold_monitor.py`` for threshold evaluation (OMN-7287)
    - ``session_checkpoint_writer.py`` for persistence (OMN-7286)
    - ``caia-watchdog.sh`` for the external resume process (OMN-7288)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.limit_threshold_monitor import (
    ModelCheckpointDecision,
    ModelLimitThresholds,
    evaluate_limits,
)
from omniclaude.hooks.model_session_checkpoint import EnumCheckpointReason
from omniclaude.hooks.statusline_parser import ModelLimitStatus


class EnumTransferAction(StrEnum):
    """Concrete transfer action to take when limits approach.

    Attributes:
        NONE: All limits within safe range, no action needed.
        CHECKPOINT_AND_EXIT: Write checkpoint and exit session for watchdog resume.
        SWITCH_TO_HAIKU: Switch to cheaper model to conserve weekly budget.
        TRANSFER_TO_LOCAL_LLM: Move all work to local LLMs (degraded mode).
    """

    NONE = "none"
    CHECKPOINT_AND_EXIT = "checkpoint_and_exit"
    SWITCH_TO_HAIKU = "switch_to_haiku"
    TRANSFER_TO_LOCAL_LLM = "transfer_to_local_llm"


class ModelTransferDecision(BaseModel):
    """Result of the transfer decision evaluation.

    Attributes:
        action: The concrete transfer action to take.
        reason: The underlying checkpoint reason that triggered this action.
        urgency: ``none``, ``warn``, or ``critical``.
        message: Human-readable explanation.
        checkpoint_needed: Whether a checkpoint file should be written.
        suggested_model: Model to switch to, if applicable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: EnumTransferAction = Field(default=EnumTransferAction.NONE)
    reason: EnumCheckpointReason | None = Field(default=None)
    urgency: str = Field(default="none")
    message: str = Field(default="")
    checkpoint_needed: bool = Field(default=False)
    suggested_model: str | None = Field(
        default=None,
        description="Model to switch to (e.g., 'haiku' or 'local_vllm')",
    )


def determine_transfer_action(
    status: ModelLimitStatus,
    thresholds: ModelLimitThresholds | None = None,
) -> ModelTransferDecision:
    """Determine the appropriate transfer action based on current limits.

    Applies additional logic on top of the raw threshold evaluation to
    decide between checkpoint-and-exit, model switching, and local LLM
    transfer.

    Decision matrix:
    1. Context or session critical -> checkpoint and exit
    2. Weekly critical -> transfer to local LLMs entirely
    3. Weekly warn (+ active session) -> switch to cheaper model
    4. Context or session warn -> checkpoint and exit (prepare for hard stop)
    5. All OK -> no action

    Args:
        status: Current limit status.
        thresholds: Custom thresholds. Defaults to ``ModelLimitThresholds()``.

    Returns:
        A ``ModelTransferDecision`` with the action and metadata.
    """
    decision: ModelCheckpointDecision = evaluate_limits(status, thresholds)

    if not decision.should_checkpoint:
        return ModelTransferDecision(
            action=EnumTransferAction.NONE,
            urgency="none",
            message="All limits within safe range",
        )

    # Critical context or session -> checkpoint and exit immediately
    if (
        decision.reason
        in (
            EnumCheckpointReason.CONTEXT_LIMIT,
            EnumCheckpointReason.SESSION_LIMIT,
        )
        and decision.urgency == "critical"
    ):
        return ModelTransferDecision(
            action=EnumTransferAction.CHECKPOINT_AND_EXIT,
            reason=decision.reason,
            urgency="critical",
            message=decision.message,
            checkpoint_needed=True,
        )

    # Weekly critical -> transfer to local LLMs
    if (
        decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        and decision.urgency == "critical"
    ):
        return ModelTransferDecision(
            action=EnumTransferAction.TRANSFER_TO_LOCAL_LLM,
            reason=EnumCheckpointReason.WEEKLY_LIMIT,
            urgency="critical",
            message=decision.message,
            checkpoint_needed=True,
            suggested_model="local_vllm",
        )

    # Weekly warn -> switch to cheaper model
    if (
        decision.reason == EnumCheckpointReason.WEEKLY_LIMIT
        and decision.urgency == "warn"
    ):
        return ModelTransferDecision(
            action=EnumTransferAction.SWITCH_TO_HAIKU,
            reason=EnumCheckpointReason.WEEKLY_LIMIT,
            urgency="warn",
            message=decision.message,
            checkpoint_needed=False,
            suggested_model="haiku",
        )

    # Context or session warn -> checkpoint and prepare
    if decision.urgency == "warn":
        return ModelTransferDecision(
            action=EnumTransferAction.CHECKPOINT_AND_EXIT,
            reason=decision.reason,
            urgency="warn",
            message=decision.message,
            checkpoint_needed=True,
        )

    # Fallback (should not reach here with current threshold logic)
    return ModelTransferDecision(
        action=EnumTransferAction.CHECKPOINT_AND_EXIT,
        reason=decision.reason,
        urgency=decision.urgency,
        message=decision.message,
        checkpoint_needed=True,
    )


__all__ = [
    "EnumTransferAction",
    "ModelTransferDecision",
    "determine_transfer_action",
]

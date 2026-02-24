# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Output model for NodeTransitionSelectorEffect."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_transition_selector_effect.models.model_typed_action import (
    ModelTypedAction,
)


class SelectionErrorKind(StrEnum):
    """Structured error kinds for transition selection failures.

    These are returned as structured errors rather than raised exceptions,
    so the boundary enforcer can handle them without crashing the loop.
    """

    SELECTION_TIMEOUT = "selection_timeout"
    MALFORMED_OUTPUT = "malformed_output"
    OUT_OF_SET = "out_of_set"
    MODEL_UNAVAILABLE = "model_unavailable"
    PROMPT_BUILD_ERROR = "prompt_build_error"


class ModelTransitionSelectorResult(BaseModel):
    """Output model for the transition selector effect node.

    On success, selected_action is populated and error_kind / error_detail
    are None. On failure, selected_action is None and error_kind describes
    what went wrong so the boundary enforcer can act appropriately.

    Attributes:
        selected_action: The chosen TypedAction from the action_set.
            None on any selection failure.
        error_kind: Structured error kind; None on success.
        error_detail: Human-readable error detail; None on success.
        model_raw_output: Raw model output string for debugging.
            Populated even on parse failures.
        duration_ms: Time taken for the selection in milliseconds.
        correlation_id: Correlation ID carried from the request.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_action: ModelTypedAction | None = Field(
        default=None,
        description="The chosen TypedAction from the action_set; None on failure",
    )
    error_kind: SelectionErrorKind | None = Field(
        default=None,
        description="Structured error kind; None on success",
    )
    error_detail: str | None = Field(
        default=None,
        description="Human-readable error detail; None on success",
    )
    model_raw_output: str | None = Field(
        default=None,
        description="Raw model output string for debugging",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time taken for the selection in milliseconds",
    )
    correlation_id: UUID = Field(
        ...,
        description="Correlation ID carried from the request",
    )

    @property
    def success(self) -> bool:
        """True if a valid action was selected."""
        return self.selected_action is not None and self.error_kind is None


__all__ = ["ModelTransitionSelectorResult", "SelectionErrorKind"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Frozen Pydantic models for the hook measurement harness (OMN-13278)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hook_measurement.enums import EnumHookWindow, EnumTokenProvenance


class ModelToolCallRecord(BaseModel):
    """One normalized per tool-call observation read from telemetry surfaces.

    Sourced from the ``cost_records`` SQLite table written by the
    cost-accounting hook (OMN-10619). Latency, when available, is joined from
    the PRM trajectory log; it is optional because the cost DB does not record
    timing directly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    recorded_at: datetime = Field(
        description="UTC timestamp the cost record was written.",
    )
    session_id: str | None = Field(
        default=None,
        description="Claude Code session id, when the hook resolved one.",
    )
    tool_name: str = Field(description="Tool that was invoked (Read/Bash/Agent/...).")
    is_delegated: bool = Field(
        default=False,
        description="Whether the call was intercepted/delegated by the model router.",
    )
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    token_provenance: EnumTokenProvenance = Field(
        default=EnumTokenProvenance.UNKNOWN,
    )
    actual_cost_usd: float = Field(default=0.0, ge=0.0)
    baseline_cost_usd: float = Field(default=0.0, ge=0.0)
    latency_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Per tool-call latency, joined from the trajectory log when present.",
    )

    @property
    def total_tokens(self) -> int:
        """Sum of input and output tokens for this call."""
        return self.input_tokens + self.output_tokens


class ModelWindowMetrics(BaseModel):
    """Aggregate metrics for one measurement window."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window: EnumHookWindow
    tool_call_count: int = Field(ge=0)
    turn_count: int = Field(
        ge=0,
        description="Distinct session ids observed; proxy for turn/session count.",
    )
    total_tokens: int = Field(ge=0)
    total_cost_usd: float = Field(ge=0.0)
    mean_tokens_per_call: float = Field(ge=0.0)
    mean_tokens_per_turn: float = Field(
        ge=0.0,
        description="Total tokens divided by distinct sessions (tokens/turn proxy).",
    )
    mean_latency_ms: float | None = Field(
        default=None,
        ge=0.0,
        description="Mean per tool-call latency over records that carried timing.",
    )
    delegated_call_count: int = Field(
        ge=0,
        description="Calls the model router intercepted (outcome-impact proxy).",
    )
    measured_token_fraction: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of records whose tokens were MEASURED (not estimated).",
    )


class ModelHookComparison(BaseModel):
    """The hooks-off vs hooks-on comparison and the derived deltas.

    Deltas are expressed as ``on - off`` for absolute fields and as a
    multiplicative ratio (``on / off``) where the relative change is the useful
    signal. Ratios are ``None`` when the off-window denominator is zero.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hooks_off: ModelWindowMetrics
    hooks_on: ModelWindowMetrics

    tokens_per_turn_delta: float = Field(
        description="hooks_on.mean_tokens_per_turn - hooks_off.mean_tokens_per_turn.",
    )
    tokens_per_turn_ratio: float | None = Field(
        default=None,
        description="hooks_on / hooks_off mean tokens per turn; None if off==0.",
    )
    tokens_per_call_delta: float
    latency_per_call_delta_ms: float | None = Field(
        default=None,
        description="Mean latency delta; None unless both windows carry timing.",
    )
    delegated_fraction_off: float = Field(ge=0.0, le=1.0)
    delegated_fraction_on: float = Field(ge=0.0, le=1.0)

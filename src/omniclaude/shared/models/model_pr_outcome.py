# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PR outcome event model for OMN-3138.

Emitted after a PR merge or revert is detected, capturing the terminal
outcome of a PR that was tracked by the pr-queue-pipeline.

Topic:
    onex.evt.omniclaude.pr-outcome.v1

Storage semantics:
    Event table (append-only, keyed by outcome_id). Terminal event for a PR
    within a pipeline run.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelPROutcome(BaseModel):
    """Terminal outcome event for a PR after merge or revert detection.

    Emitted once per PR at the terminal point of the pr-queue-pipeline
    processing. Links back to the changeset via ``changeset_id`` (if a
    changeset was emitted for this PR).

    Attributes:
        event_id: Unique ID for this event instance.
        outcome_id: Unique ID for this outcome record.
        pr_number: GitHub PR number.
        pr_ref: Full PR reference (e.g. "OmniNode-ai/omniclaude#247").
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        outcome: Terminal outcome of the PR.
        merge_sha: Merge commit SHA (if merged). None if reverted or failed.
        merge_method: Merge method used (squash/merge/rebase). None if not merged.
        changeset_id: Links to the originating ModelPRChangeSet (if emitted).
        gate_token: Gate attestation token from the Slack gate (if applicable).
        pipeline_phase: Which pipeline phase produced this outcome.
        run_id: Pipeline run identifier for correlation.
        correlation_id: End-to-end correlation identifier.
        run_fingerprint: Deterministic fingerprint of the pipeline run.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    outcome_id: UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique ID for this outcome record",
    )
    pr_number: int = Field(..., ge=1, description="GitHub PR number")
    pr_ref: str = Field(
        ...,
        min_length=1,
        description="Full PR reference (e.g. 'OmniNode-ai/omniclaude#247')",
    )
    repo: str = Field(
        ...,
        min_length=1,
        description="Repository slug (e.g. 'OmniNode-ai/omniclaude')",
    )
    outcome: Literal["merged", "reverted", "failed", "skipped"] = Field(
        ...,
        description="Terminal outcome of the PR",
    )
    merge_sha: str | None = Field(
        default=None,
        description="Merge commit SHA (if merged)",
    )
    merge_method: Literal["squash", "merge", "rebase"] | None = Field(
        default=None,
        description="Merge method used (if merged)",
    )
    changeset_id: UUID | None = Field(
        default=None,
        description="Links to the originating ModelPRChangeSet (if emitted)",
    )
    gate_token: str | None = Field(
        default=None,
        description="Gate attestation token from the Slack gate",
    )
    pipeline_phase: Literal["merge_phase3", "merge_phase4", "fix", "review"] | None = (
        Field(
            default=None,
            description="Which pipeline phase produced this outcome",
        )
    )
    run_id: UUID = Field(..., description="Pipeline run identifier for correlation")
    correlation_id: UUID = Field(..., description="End-to-end correlation identifier")
    run_fingerprint: str = Field(
        ...,
        min_length=1,
        description="Deterministic fingerprint of the pipeline run",
    )
    emitted_at: datetime = Field(
        ...,
        description="UTC timestamp when the event was emitted (injected by emitter)",
    )
    session_id: str | None = None


__all__ = [
    "ModelPROutcome",
]

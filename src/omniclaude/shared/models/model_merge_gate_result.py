# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Merge gate result event model for OMN-3138.

Emitted after Tier A gate checks are run locally on a PR's contract changes.
Captures the results of linter_contract.py validation and other structural
checks.

Topic:
    onex.evt.omniclaude.merge-gate-decision.v1

Storage semantics:
    Event table (append-only, keyed by gate_run_id). Consumers may filter
    by changeset_id to correlate with the originating ModelPRChangeSet.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelGateCheckResult(BaseModel):
    """Result of a single gate check within a Tier A validation run.

    Attributes:
        check_name: Human-readable name of the check (e.g. "contract_schema",
            "topic_naming", "declared_topics_exist").
        passed: Whether the check passed.
        severity: Severity level if the check failed.
        message: Human-readable description of the check outcome.
        file_path: File path the check was run against (if applicable).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    check_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable name of the check",
    )
    passed: bool = Field(..., description="Whether the check passed")
    severity: Literal["critical", "major", "minor", "info"] = Field(
        default="info",
        description="Severity level if the check failed",
    )
    message: str = Field(
        default="",
        description="Human-readable description of the check outcome",
    )
    file_path: str | None = Field(
        default=None,
        description="File path the check was run against",
    )


class ModelMergeGateResult(BaseModel):
    """Aggregate result of Tier A gate checks for a PR changeset.

    Emitted after running linter_contract.py and other structural validations
    on the contract changes detected in a PR. The ``changeset_id`` links this
    result back to the originating ``ModelPRChangeSet``.

    Attributes:
        event_id: Unique ID for this event instance.
        gate_run_id: Unique ID for this gate check run.
        changeset_id: Links to the originating ModelPRChangeSet.
        pr_ref: Full PR reference (e.g. "OmniNode-ai/omniclaude#247").
        repo: Repository slug.
        tier: Gate tier level (currently only "A" is implemented).
        overall_passed: Whether all checks passed.
        checks: Individual check results.
        checks_passed: Count of checks that passed.
        checks_failed: Count of checks that failed.
        run_id: Pipeline run identifier for correlation.
        correlation_id: End-to-end correlation identifier.
        run_fingerprint: Deterministic fingerprint of the pipeline run.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    gate_run_id: UUID = Field(
        default_factory=uuid.uuid4,
        description="Unique ID for this gate check run",
    )
    changeset_id: UUID = Field(
        ...,
        description="Links to the originating ModelPRChangeSet",
    )
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
    tier: Literal["A", "B", "C"] = Field(
        default="A",
        description="Gate tier level (currently only 'A' is implemented)",
    )
    overall_passed: bool = Field(..., description="Whether all checks passed")
    checks: list[ModelGateCheckResult] = Field(
        default_factory=list,
        description="Individual check results",
    )
    checks_passed: int = Field(
        default=0, ge=0, description="Count of checks that passed"
    )
    checks_failed: int = Field(
        default=0, ge=0, description="Count of checks that failed"
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
    "ModelGateCheckResult",
    "ModelMergeGateResult",
]

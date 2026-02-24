# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Core Pydantic models for the Agent Trace and PR Debugging System.

All models are frozen (immutable) after construction per ONEX invariants.
ChangeFrame invariants are enforced via @model_validator.

Stage 1 of DESIGN_AGENT_TRACE_PR_DEBUGGING_SYSTEM.md
"""

from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FailureType(str, Enum):
    """Classification of the type of failure that occurred in a ChangeFrame."""

    TEST_FAIL = "test_fail"
    TYPE_FAIL = "type_fail"
    LINT_FAIL = "lint_fail"
    BUILD_FAIL = "build_fail"
    RUNTIME_FAIL = "runtime_fail"


class OutcomeStatus(str, Enum):
    """High-level classification of a ChangeFrame's outcome."""

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    PARTIAL = "partial"


class AssociationMethod(str, Enum):
    """Method used to associate a ChangeFrame with a PREnvelope."""

    COMMIT_ANCESTRY = "commit_ancestry"
    BRANCH_NAME = "branch_name"
    DIFF_OVERLAP = "diff_overlap"
    PATCH_HASH = "patch_hash"


# ---------------------------------------------------------------------------
# Sub-models (all frozen)
# ---------------------------------------------------------------------------


class ModelFrameConfig(BaseModel):
    """LLM configuration at the time the ChangeFrame was produced."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    temperature: float | None = None
    seed: int | None = None
    max_tokens: int | None = None


class ModelIntentRef(BaseModel):
    """Reference to the intent (prompt) that triggered this ChangeFrame."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    prompt_hash: str
    ticket_id: str | None = None
    contract_hash: str | None = None

    @field_validator("prompt_hash")
    @classmethod
    def prompt_hash_nonempty(cls, v: str) -> str:
        """Ensure prompt_hash is non-empty."""
        if not v.strip():
            raise ValueError("prompt_hash must not be empty")
        return v


class ModelWorkspaceRef(BaseModel):
    """Reference to the workspace state at frame capture time."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    repo: str
    branch: str
    base_commit: str

    @field_validator("base_commit")
    @classmethod
    def base_commit_nonempty(cls, v: str) -> str:
        """Ensure base_commit is non-empty."""
        if not v.strip():
            raise ValueError("base_commit must not be empty")
        return v


class ModelDelta(BaseModel):
    """The actual code change captured in this ChangeFrame."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    diff_patch: str
    files_changed: list[str]
    loc_added: int
    loc_removed: int
    pre_hashes: dict[str, str] = {}
    post_hashes: dict[str, str] = {}

    @field_validator("loc_added", "loc_removed")
    @classmethod
    def loc_non_negative(cls, v: int) -> int:
        """Ensure loc values are non-negative."""
        if v < 0:
            raise ValueError("loc values must be non-negative")
        return v


class ModelToolEvent(BaseModel):
    """Record of a single tool invocation during frame execution."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    tool_name: str
    input_hash: str
    output_hash: str
    raw_pointer: str | None = None


class ModelCheckResult(BaseModel):
    """Result of a single quality check (lint, typecheck, test, etc.)."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    command: str
    environment_hash: str
    exit_code: int
    output_hash: str
    truncated_output: str = ""


class ModelOutcome(BaseModel):
    """High-level outcome classification for a ChangeFrame."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    status: Literal["pass", "fail", "partial"]
    failure_signature_id: str | None = None


class ModelEvidence(BaseModel):
    """Evidence (logs) captured alongside the ChangeFrame."""

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    truncated_logs: str = ""
    full_log_pointer: str | None = None


# ---------------------------------------------------------------------------
# Primary model: ChangeFrame
# ---------------------------------------------------------------------------


class ChangeFrame(BaseModel):
    """Atomic agent execution record — the fundamental unit of the trace system.

    A ChangeFrame captures everything that happened during one meaningful agent
    action: the workspace state, the change made, the checks run, and the outcome.

    Frame Invariants (enforced via @model_validator):
    1. delta.diff_patch must be non-empty (something changed)
    2. len(checks) >= 1 (at least one check was run)
    3. outcome.status is set (classified outcome)

    All three must hold or the frame is invalid.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    frame_id: UUID
    parent_frame_id: UUID | None = None
    trace_id: str
    timestamp_utc: str
    agent_id: str
    model_id: str

    frame_config: ModelFrameConfig
    intent_ref: ModelIntentRef
    workspace_ref: ModelWorkspaceRef
    delta: ModelDelta
    tool_events: list[ModelToolEvent] = []
    checks: list[ModelCheckResult]
    outcome: ModelOutcome
    evidence: ModelEvidence = ModelEvidence()

    @model_validator(mode="after")
    def validate_frame_invariants(self) -> ChangeFrame:
        """Enforce all three ChangeFrame invariants.

        Invariant 1: delta.diff_patch must be non-empty.
        Invariant 2: at least one check must have been run.
        Invariant 3: outcome.status must be set (Pydantic enforces Literal type).
        """
        # Invariant 1: non-empty delta
        if not self.delta.diff_patch.strip():
            raise ValueError(
                "ChangeFrame invariant violation: delta.diff_patch must be non-empty. "
                "A frame requires at least one meaningful code change."
            )

        # Invariant 2: at least one check
        if len(self.checks) < 1:
            raise ValueError(
                "ChangeFrame invariant violation: at least one check must be present. "
                "Frames without quality checks cannot have a valid outcome."
            )

        # Invariant 3: outcome.status is enforced by Pydantic's Literal type.
        # If ModelOutcome.status is set to a valid Literal value, this invariant holds.
        # We add an explicit guard for clarity and future-proofing.
        if not self.outcome.status:
            raise ValueError(
                "ChangeFrame invariant violation: outcome.status must be set. "
                "Use 'pass', 'fail', or 'partial'."
            )

        return self

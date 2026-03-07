# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""PR changeset event model for OMN-3138.

Emitted when a PR is opened or updated, capturing the set of contract changes
detected via ``git diff``. The ``changeset_id`` is deterministic (uuid5) so
that duplicate emissions for the same PR ref + SHA range are idempotent.

Topic:
    onex.evt.omniclaude.pr-changeset-created.v1

Storage semantics:
    Event table (append-only, keyed by changeset_id). Consumers may deduplicate
    on changeset_id.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Namespace for deterministic changeset_id generation.
# uuid5(NAMESPACE, f"{pr_ref}:{base_sha}:{head_sha}")
CHANGESET_UUID_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


class ModelContractChange(BaseModel):
    """A single contract file change detected in the PR diff.

    Attributes:
        file_path: Relative path to the contract.yaml file.
        change_type: Whether the contract was added, modified, or deleted.
        declared_topics: Topic names declared in the contract (extracted from
            the contract YAML ``declared_topics`` field). Empty list if the
            contract was deleted or topics could not be parsed.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    file_path: str = Field(
        ...,
        min_length=1,
        description="Relative path to the contract.yaml file",
    )
    change_type: Literal["added", "modified", "deleted"] = Field(
        ...,
        description="Whether the contract was added, modified, or deleted",
    )
    declared_topics: list[str] = Field(
        default_factory=list,
        description="Topic names declared in the contract YAML",
    )


class ModelPRChangeSet(BaseModel):
    """Structured changeset emitted on PR open/update with contract changes.

    The ``changeset_id`` is deterministic:
    ``uuid5(CHANGESET_UUID_NAMESPACE, f"{pr_ref}:{base_sha}:{head_sha}")``

    This ensures that re-processing the same PR state produces the same
    changeset_id, enabling idempotent downstream processing.

    Attributes:
        event_id: Unique ID for this event instance.
        changeset_id: Deterministic ID derived from pr_ref + SHA range.
        pr_number: GitHub PR number.
        pr_ref: Full PR reference (e.g. "OmniNode-ai/omniclaude#247").
        repo: Repository slug (e.g. "OmniNode-ai/omniclaude").
        base_sha: Base commit SHA of the PR.
        head_sha: Head commit SHA of the PR.
        contract_changes: List of contract file changes detected.
        total_files_changed: Total number of files changed in the PR diff.
        run_id: Pipeline run identifier for correlation.
        correlation_id: End-to-end correlation identifier.
        run_fingerprint: Deterministic fingerprint of the pipeline run.
        emitted_at: UTC timestamp when the event was emitted (injected by emitter).
        session_id: Optional Claude Code session identifier.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    event_id: UUID = Field(default_factory=uuid.uuid4)
    changeset_id: UUID = Field(
        ...,
        description="Deterministic ID: uuid5(NAMESPACE, '{pr_ref}:{base_sha}:{head_sha}')",
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
    base_sha: str = Field(
        ...,
        min_length=7,
        description="Base commit SHA of the PR",
    )
    head_sha: str = Field(
        ...,
        min_length=7,
        description="Head commit SHA of the PR",
    )
    contract_changes: list[ModelContractChange] = Field(
        default_factory=list,
        description="Contract file changes detected in the PR diff",
    )
    total_files_changed: int = Field(
        default=0,
        ge=0,
        description="Total number of files changed in the PR diff",
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


def build_changeset_id(pr_ref: str, base_sha: str, head_sha: str) -> UUID:
    """Build a deterministic changeset_id from PR ref and SHA range.

    Args:
        pr_ref: Full PR reference (e.g. "OmniNode-ai/omniclaude#247").
        base_sha: Base commit SHA.
        head_sha: Head commit SHA.

    Returns:
        Deterministic UUID5 derived from the input parameters.
    """
    return uuid.uuid5(CHANGESET_UUID_NAMESPACE, f"{pr_ref}:{base_sha}:{head_sha}")


__all__ = [
    "CHANGESET_UUID_NAMESPACE",
    "ModelContractChange",
    "ModelPRChangeSet",
    "build_changeset_id",
]

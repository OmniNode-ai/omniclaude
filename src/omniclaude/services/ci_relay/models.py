# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Pydantic models for the CI relay service.

CICallbackPayload: inbound from GH Actions notify-completion step.
PRStatusEvent: outbound to Kafka topic ``onex.evt.omniclaude.github-pr-status.v1``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class CICallbackPayload(BaseModel):
    """Payload sent by GH Actions notify-completion step.

    Constructed via ``jq -nc`` in the workflow YAML for guaranteed valid JSON.
    """

    repo: str = Field(..., description="Full repo slug, e.g. 'OmniNode-ai/omniclaude'")
    pr: int = Field(
        ...,
        description=("PR number. 0 if push-triggered (relay resolves via sha lookup)"),
    )
    conclusion: str = Field(
        ...,
        description=("Workflow conclusion: success, failure, cancelled, timed_out"),
    )
    sha: str = Field(..., description="Head commit SHA")
    run_id: int = Field(..., description="GH Actions run ID")
    ref: str = Field(..., description="Git ref, e.g. 'refs/pull/42/merge'")
    head_ref: str = Field(..., description="Head branch name, e.g. 'feature/my-branch'")
    base_ref: str = Field(..., description="Base branch name, e.g. 'main'")
    workflow_url: str = Field(..., description="URL to the workflow run")
    jobs: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of job summary dicts (name, conclusion, url)",
    )


class PRStatusEvent(BaseModel):
    """Event published to ``onex.evt.omniclaude.github-pr-status.v1``.

    Extends CICallbackPayload with envelope fields for the ONEX event bus.
    """

    # Envelope fields (Phase 3 message envelope)
    schema_version: str = Field(
        default="1.0.0", description="Schema version for this event type"
    )
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique message identifier",
    )
    emitted_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO 8601 UTC timestamp of emission",
    )
    trace: dict[str, str] = Field(
        default_factory=dict,
        description="Trace context (correlation_id, parent_id, etc.)",
    )

    # Payload fields (from CICallbackPayload)
    repo: str
    pr: int
    conclusion: str
    sha: str
    run_id: int
    ref: str
    head_ref: str
    base_ref: str
    workflow_url: str
    jobs: list[dict[str, Any]] = Field(default_factory=list)

    # Relay-added fields
    dedupe_key: str = Field(
        ...,
        description="Idempotency key: '{repo}:{sha}:{run_id}'",
    )
    resolved_pr: int | None = Field(
        default=None,
        description="PR number resolved from sha when original pr=0",
    )

    @classmethod
    def from_callback(
        cls,
        payload: CICallbackPayload,
        *,
        resolved_pr: int | None = None,
        trace: dict[str, str] | None = None,
    ) -> PRStatusEvent:
        """Create a PRStatusEvent from a CICallbackPayload.

        Args:
            payload: The inbound callback payload.
            resolved_pr: PR number resolved via sha lookup (when payload.pr=0).
            trace: Optional trace context to include.

        Returns:
            PRStatusEvent ready for Kafka publication.
        """
        dedupe_key = f"{payload.repo}:{payload.sha}:{payload.run_id}"
        return cls(
            repo=payload.repo,
            pr=payload.pr,
            conclusion=payload.conclusion,
            sha=payload.sha,
            run_id=payload.run_id,
            ref=payload.ref,
            head_ref=payload.head_ref,
            base_ref=payload.base_ref,
            workflow_url=payload.workflow_url,
            jobs=payload.jobs,
            dedupe_key=dedupe_key,
            resolved_pr=resolved_pr,
            trace=trace or {},
        )

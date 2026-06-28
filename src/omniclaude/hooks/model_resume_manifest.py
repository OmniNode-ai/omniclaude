# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Resume manifest model for anchor-first workflow ordering (OMN-13049).

Workers write a :class:`ModelResumeManifest` at every phase boundary so that
a worker death never strands a diagnosed defect without identity.  The manifest
is persisted to ``$ONEX_STATE_DIR/manifests/<ticket_id>/manifest.yaml``.

Phase 0 (``phase_0_anchor``) must be completed — ticket filed and WIP branch
pushed — before any long implementation leg begins.

See Also:
    - ``resume_manifest_writer.py`` for persistence helpers
    - ``dispatch_worker`` skill for injection into worker prompts (Rule 6)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumResumeManifestPhase(StrEnum):
    """Ordered phases written to the resume manifest.

    Attributes:
        PHASE_0_ANCHOR: Linear ticket filed + WIP branch pushed (must run first).
        IMPLEMENT: Code is being written in the worktree.
        LOCAL_REVIEW: Local review skill running.
        CREATE_PR: PR is being created.
        DONE: All phases completed; PR is open or merged.
    """

    PHASE_0_ANCHOR = "phase_0_anchor"
    IMPLEMENT = "implement"
    LOCAL_REVIEW = "local_review"
    CREATE_PR = "create_pr"
    DONE = "done"


class ModelResumeManifest(BaseModel):
    """Phase-boundary manifest written by workers for anchor-first ordering.

    A manifest is written immediately after phase 0 (WIP push) and updated at
    every subsequent phase boundary.  On any auth or usage-limit error the
    manifest is flushed with ``auth_error_detected=True`` and a
    ``survivor_note`` so the defect retains identity even if the worker dies.

    Storage: ``$ONEX_STATE_DIR/manifests/<ticket_id>/manifest.yaml``.

    Attributes:
        schema_version: Forward-compatibility version string.
        ticket_id: Linear ticket identifier (e.g., ``OMN-13049``).
        run_id: Unique run UUID for correlation across restarts.
        linear_ticket_url: Full Linear URL once the ticket is filed or verified.
        wip_branch: Name of the WIP branch pushed in phase 0.
        wip_pushed_at: ISO-8601 timestamp when the WIP branch was first pushed.
        phase: Current or last-completed phase.
        phase_started_at: ISO-8601 timestamp when the current phase began.
        phase_completed_at: ISO-8601 timestamp when the phase completed;
            ``None`` while the phase is still in-flight.
        auth_error_detected: ``True`` when an auth or usage-limit error triggered
            the manifest flush.
        survivor_note: Human-readable description of the diagnosed defect written
            on abnormal termination so the work has identity without a filed PR.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = (
        Field(  # string-version-ok: persisted to .onex_state/manifests/
            default="1.0.0",
            description="Manifest schema version for forward compatibility",
        )
    )
    ticket_id: str = Field(
        min_length=1,
        max_length=64,
        description="Linear ticket identifier (e.g., OMN-13049)",
    )
    run_id: str = Field(
        min_length=1,
        description="Unique run UUID for correlation",
    )
    linear_ticket_url: str | None = Field(
        default=None,
        description="Full Linear URL once the ticket is filed or verified",
    )
    wip_branch: str | None = Field(
        default=None,
        description="WIP branch name pushed in phase 0",
    )
    wip_pushed_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when the WIP branch was first pushed",
    )
    phase: EnumResumeManifestPhase = Field(
        description="Current or last-completed phase",
    )
    phase_started_at: str = Field(
        description="ISO-8601 timestamp when the current phase began",
    )
    phase_completed_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when the phase completed; None while in-flight",
    )
    auth_error_detected: bool = Field(
        default=False,
        description="True when an auth or usage-limit error triggered a manifest flush",
    )
    survivor_note: str | None = Field(
        default=None,
        description=(
            "Diagnostic note written on abnormal termination so the defect has identity"
        ),
    )


__all__ = [
    "EnumResumeManifestPhase",
    "ModelResumeManifest",
]

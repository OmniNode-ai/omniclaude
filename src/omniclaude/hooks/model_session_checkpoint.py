# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session-level checkpoint model for limit-aware session continuity.

When Claude Code approaches context, session, or weekly limits, the orchestrator
writes a ``ModelSessionCheckpoint`` to disk so an external watchdog process can
resume work after limits reset.

Checkpoint files live at ``.onex_state/orchestrator/checkpoint.yaml``.

This is distinct from the pipeline-level checkpoint in ``pipeline_checkpoint.py``
which tracks *skill phases*. This module tracks *session limits* and provides
enough state for a cold resume via ``claude -p``.

See Also:
    - ``session_checkpoint_writer.py`` for persistence (OMN-7286)
    - ``statusline_parser.py`` for limit data extraction (OMN-7284)
    - ``limit_threshold_monitor.py`` for threshold evaluation (OMN-7287)
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumCheckpointReason(StrEnum):
    """Reason a session checkpoint was triggered.

    Attributes:
        CONTEXT_LIMIT: Context window approaching capacity.
        SESSION_LIMIT: Session token/time limit approaching.
        WEEKLY_LIMIT: Weekly rate limit approaching.
        EXPLICIT: User or skill triggered checkpoint manually.
    """

    CONTEXT_LIMIT = "context_limit"
    SESSION_LIMIT = "session_limit"
    WEEKLY_LIMIT = "weekly_limit"
    EXPLICIT = "explicit"


class ModelSessionCheckpoint(BaseModel):
    """Session-level checkpoint written when limits approach.

    Contains enough state for a watchdog process to resume work via
    ``claude -p`` after limits reset. All fields are serializable to YAML.

    Attributes:
        schema_version: Forward-compatibility version string.
        session_id: Claude Code session ID.
        checkpoint_reason: Why the checkpoint was triggered.
        created_at: ISO-8601 timestamp when checkpoint was created.
        reset_at: ISO-8601 timestamp when limits are expected to reset.
        resume_prompt: Self-contained prompt for ``claude -p`` to continue work.
        active_epic: Linear epic ID currently being worked on.
        active_tickets: In-progress Linear ticket IDs.
        active_prs: Open PR references (``repo#num`` format).
        pipeline_state: Which skill/phase was running (e.g. ``ticket-pipeline:implement``).
        context_percent: Context window usage at checkpoint time (0-100).
        session_percent: Session limit usage at checkpoint time (0-100).
        weekly_percent: Weekly limit usage at checkpoint time (0-100).
        working_directory: Absolute path to the working directory.
        git_branch: Current git branch name.
        worktree_path: Absolute path to the worktree, if applicable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(
        default="1.0.0",
        description="Checkpoint schema version for forward compatibility",
    )
    session_id: str = Field(description="Claude Code session ID")
    checkpoint_reason: EnumCheckpointReason = Field(
        description="Why the checkpoint was triggered",
    )
    created_at: str = Field(description="ISO-8601 creation timestamp")
    reset_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp when limits are expected to reset",
    )

    # What was running
    resume_prompt: str = Field(
        description="Self-contained prompt for claude -p to continue work",
    )
    active_epic: str | None = Field(
        default=None,
        description="Linear epic ID currently being worked on",
    )
    active_tickets: list[str] = Field(
        default_factory=list,
        description="In-progress Linear ticket IDs",
    )
    active_prs: list[str] = Field(
        default_factory=list,
        description="Open PR references (repo#num format)",
    )
    pipeline_state: str | None = Field(
        default=None,
        description="Which skill/phase was running (e.g. ticket-pipeline:implement)",
    )

    # Limit data at checkpoint time
    context_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Context window usage percentage (0-100)",
    )
    session_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Session limit usage percentage (0-100)",
    )
    weekly_percent: int | None = Field(
        default=None,
        ge=0,
        le=100,
        description="Weekly limit usage percentage (0-100)",
    )

    # Working context
    working_directory: str | None = Field(
        default=None,
        description="Absolute path to the working directory",
    )
    git_branch: str | None = Field(
        default=None,
        description="Current git branch name",
    )
    worktree_path: str | None = Field(
        default=None,
        description="Absolute path to the worktree, if applicable",
    )


__all__ = [
    "EnumCheckpointReason",
    "ModelSessionCheckpoint",
]

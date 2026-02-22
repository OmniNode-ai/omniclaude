"""Agent Trace and PR Debugging System — trace package.

This package provides schema definitions and ORM-compatible table definitions
for the Agent Trace system (TRACE-02).

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for these tables must be applied once the freeze lifts.
See src/omniclaude/trace/db_schema.py for the complete DDL.

This package also implements the core data models, persistence, and analysis
infrastructure for tracking agent execution as ChangeFrames.

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for these tables must be applied once the freeze lifts.
See src/omniclaude/trace/db_schema.py for the complete DDL.
"""

from omniclaude.trace.change_frame import (
    AssociationMethod,
    ChangeFrame,
    FailureType,
    ModelCheckResult,
    ModelDelta,
    ModelEvidence,
    ModelFrameConfig,
    ModelIntentRef,
    ModelOutcome,
    ModelToolEvent,
    ModelWorkspaceRef,
    OutcomeStatus,
)
from omniclaude.trace.pr_envelope import (
    AssociationResult,
    ModelCIArtifact,
    ModelPRBodyVersion,
    ModelPRText,
    ModelPRTimeline,
    PRDescriptionDelta,
    PREnvelope,
)

__all__ = [
    # change_frame exports
    "AssociationMethod",
    "ChangeFrame",
    "FailureType",
    "ModelCheckResult",
    "ModelDelta",
    "ModelEvidence",
    "ModelFrameConfig",
    "ModelIntentRef",
    "ModelOutcome",
    "ModelToolEvent",
    "ModelWorkspaceRef",
    "OutcomeStatus",
    # pr_envelope exports
    "AssociationResult",
    "ModelCIArtifact",
    "ModelPRBodyVersion",
    "ModelPRText",
    "ModelPRTimeline",
    "PRDescriptionDelta",
    "PREnvelope",
]

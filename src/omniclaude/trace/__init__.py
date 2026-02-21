"""Agent Trace and PR Debugging System — trace package.

This package provides schema definitions and ORM-compatible table definitions
for the Agent Trace system (TRACE-02).

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for these tables must be applied once the freeze lifts.
See src/omniclaude/trace/db_schema.py for the complete DDL.

This package also implements the core data models, persistence, and analysis
infrastructure for tracking agent execution as ChangeFrames.
"""

from omniclaude.trace.models import (
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

__all__ = [
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
]

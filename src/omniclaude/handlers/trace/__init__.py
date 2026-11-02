# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Agent Trace and PR Debugging System — trace package.

This package provides schema definitions and ORM-compatible table definitions
for the Agent Trace system (TRACE-02).

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for these tables must be applied once the freeze lifts.
See src/omniclaude/models/trace/db_schema.py for the complete DDL.

This package also implements the core data models, persistence, and analysis
infrastructure for tracking agent execution as ChangeFrames.

NOTE: Migration freeze is active (OMN-2055 / .migration_freeze).
The Alembic migration for these tables must be applied once the freeze lifts.
See src/omniclaude/models/trace/db_schema.py for the complete DDL.
"""

from omniclaude.handlers.trace.failure_signature import (
    FailureSignature,
    compute_failure_signature,
)
from omniclaude.handlers.trace.fix_transition import (
    FixTransition,
    OpenFailure,
)
from omniclaude.handlers.trace.intelligence_integration import (
    ContextItem,
    FixTransitionEvent,
    FixTransitionProcessingResult,
    PatternPromotionCandidate,
    build_context_item_from_fix_transition,
    check_pattern_promotion,
    parse_fix_transition_event,
    process_fix_transition_event,
    score_failure_signature_match,
    score_file_touched_match,
)
from omniclaude.handlers.trace.replay_engine import (
    ReplayEngine,
    ReplayMode,
    ReplayResult,
)
from omniclaude.models.trace.change_frame import (
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
from omniclaude.models.trace.pr_envelope import (
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
    # replay_engine exports
    "ReplayEngine",
    "ReplayMode",
    "ReplayResult",
    # failure_signature exports
    "FailureSignature",
    "compute_failure_signature",
    # fix_transition exports
    "FixTransition",
    "OpenFailure",
    # intelligence_integration exports
    "ContextItem",
    "FixTransitionEvent",
    "FixTransitionProcessingResult",
    "PatternPromotionCandidate",
    "build_context_item_from_fix_transition",
    "check_pattern_promotion",
    "parse_fix_transition_event",
    "process_fix_transition_event",
    "score_failure_signature_match",
    "score_file_touched_match",
]

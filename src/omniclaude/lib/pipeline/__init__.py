# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Pipeline policy enforcement and state management."""

from __future__ import annotations

from omniclaude.lib.pipeline.fingerprint_engine import (
    classify_severity,
    compute_fingerprint_set,
    detect_new_major,
    detect_repeat_issues,
    normalize_finding,
)
from omniclaude.lib.pipeline.models import (
    IssueFingerprint,
    IterationRecord,
    PhaseResult,
    PipelinePolicy,
)

__all__ = [
    "PipelinePolicy",
    "IssueFingerprint",
    "PhaseResult",
    "IterationRecord",
    "normalize_finding",
    "compute_fingerprint_set",
    "detect_repeat_issues",
    "detect_new_major",
    "classify_severity",
]

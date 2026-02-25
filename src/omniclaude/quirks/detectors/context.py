# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""DetectionContext — input container passed to every QuirkDetector.

All fields are optional except ``session_id``.  Detectors gracefully skip
analysis when required fields for their domain are absent.

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DetectionContext(BaseModel):
    """Immutable input bundle supplied to every ``QuirkDetector.detect()`` call.

    Attributes:
        session_id: The Claude Code session identifier for the current run.
        diff: Unified diff string (``git diff`` output) for the current
            change set.  Used by diff-aware detectors (STUB_CODE, NO_TESTS).
        model_output: Raw text produced by the model in the current turn.
            Used by output-aware detectors (SYCOPHANCY).
        file_paths: List of file paths touched in the current change set
            (relative to the repository root).  May duplicate paths already
            encoded in ``diff``; detectors choose which representation to use.
        session_history: Ordered list of previous model output strings in
            the same session, oldest first.  Supplied to detectors that
            require turn-level context (e.g. position-reversal detection).
    """

    model_config = ConfigDict(frozen=True)

    session_id: str = Field(..., min_length=1)
    diff: str | None = None
    model_output: str | None = None
    file_paths: list[str] = Field(default_factory=list)
    session_history: list[str] = Field(default_factory=list)

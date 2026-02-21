# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Enum for ambiguity resolution paths.

Records whether an ambiguity in the NL input was resolved via explicit
clarification from the user or via model-based inference.  This is required
by OMN-2504 (Ambiguity Gate) for auditable resolution traceability.
"""

from __future__ import annotations

from enum import Enum


class EnumResolutionPath(str, Enum):
    """How an ambiguity was resolved on the way to a structured Intent object.

    Variants:
        NONE: No ambiguity detected — no resolution needed.
        CLARIFICATION: User explicitly resolved the ambiguity via follow-up.
        INFERENCE: Model inferred the resolution without explicit user input.
        UNRESOLVED: Ambiguity was detected but not yet resolved.
    """

    NONE = "NONE"
    CLARIFICATION = "CLARIFICATION"
    INFERENCE = "INFERENCE"
    UNRESOLVED = "UNRESOLVED"


__all__ = ["EnumResolutionPath"]

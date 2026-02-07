# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Internal pure-Python routing logic.

This package contains the ported routing algorithms with ZERO ONEX imports.
All modules use dict[str, Any] interfaces. The handler layer adapts between
typed ONEX models and these pure-Python internals.

Exported:
    TriggerMatcher: Fuzzy trigger matching with scoring
    ConfidenceScorer: Multi-dimensional confidence scoring
    ConfidenceScore: Dataclass for confidence breakdown
"""

from __future__ import annotations

from .confidence_scoring import ConfidenceScore, ConfidenceScorer
from .trigger_matching import TriggerMatcher

__all__ = [
    "ConfidenceScore",
    "ConfidenceScorer",
    "TriggerMatcher",
]

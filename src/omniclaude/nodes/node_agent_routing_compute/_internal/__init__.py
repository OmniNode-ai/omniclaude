# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Internal pure-Python routing logic.

This package contains the ported routing algorithms with ZERO ONEX imports.
Interfaces use narrow TypedDicts (defined in ``_types``) instead of
``dict[str, Any]``.  The handler layer adapts between typed ONEX models
and these pure-Python internals.

Exported:
    TriggerMatcher: Fuzzy trigger matching with scoring
    ConfidenceScorer: Multi-dimensional confidence scoring
    ConfidenceScore: Dataclass for confidence breakdown
    AgentData: TypedDict for agent registry entries
    HistoricalRecord: TypedDict for historical performance data
    AgentRegistry: TypedDict for registry structure
    RoutingContext: TypedDict for execution context
"""

from __future__ import annotations

from ._types import AgentData, AgentRegistry, HistoricalRecord, RoutingContext
from .confidence_scoring import ConfidenceScore, ConfidenceScorer
from .trigger_matching import TriggerMatcher

__all__ = [
    "AgentData",
    "AgentRegistry",
    "ConfidenceScore",
    "ConfidenceScorer",
    "HistoricalRecord",
    "RoutingContext",
    "TriggerMatcher",
]

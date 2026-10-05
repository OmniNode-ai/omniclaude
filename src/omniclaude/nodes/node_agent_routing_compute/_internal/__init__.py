# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
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
    TypedDictAgentRegistry: TypedDict for registry structure
    RoutingContext: TypedDict for execution context
"""

from __future__ import annotations

from ._types import AgentData, HistoricalRecord, RoutingContext, TypedDictAgentRegistry
from .confidence_scoring import ConfidenceScore, ConfidenceScorer
from .trigger_matching import TriggerMatcher

__all__ = [
    "AgentData",
    "TypedDictAgentRegistry",
    "ConfidenceScore",
    "ConfidenceScorer",
    "HistoricalRecord",
    "RoutingContext",
    "TriggerMatcher",
]

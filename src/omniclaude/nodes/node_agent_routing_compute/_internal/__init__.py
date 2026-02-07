# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Internal pure-Python routing logic.

This package contains the ported routing algorithms with ZERO ONEX imports.
All modules use TypedDict interfaces. The handler layer adapts between
typed ONEX models and these pure-Python internals.

Exported:
    TriggerMatcher: Fuzzy trigger matching with scoring
    ConfidenceScorer: Multi-dimensional confidence scoring
    ConfidenceScore: Dataclass for confidence breakdown
    AgentData: TypedDict for agent registry entries
    AgentHistory: TypedDict for historical performance data
    AgentRegistry: TypedDict for registry structure
    RoutingContext: TypedDict for execution context
"""

from __future__ import annotations

from .confidence_scoring import (
    AgentData,
    AgentHistory,
    ConfidenceScore,
    ConfidenceScorer,
    RoutingContext,
)
from .trigger_matching import AgentRegistry, TriggerMatcher

__all__ = [
    "AgentData",
    "AgentHistory",
    "AgentRegistry",
    "ConfidenceScore",
    "ConfidenceScorer",
    "RoutingContext",
    "TriggerMatcher",
]

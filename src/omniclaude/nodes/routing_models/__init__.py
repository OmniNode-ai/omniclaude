# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Strongly-typed Pydantic models for agent routing.

This package contains data-only models (no logic) for the routing subsystem.
Models are grouped by their future node affinity:

Compute Node Models:
    - ModelRoutingRequest: Input to the routing compute node
    - ModelRoutingResult: Output from the routing compute node
    - ModelConfidenceBreakdown: Detailed confidence scoring breakdown
    - ModelAgentDefinition: Agent identity and activation patterns

Effect Node Models:
    - ModelEmissionRequest: Input to the emission effect node
    - ModelEmissionResult: Output from the emission effect node

Reducer Models:
    - ModelAgentRoutingStats: Aggregated routing statistics
    - ModelAgentStatsEntry: Per-agent statistics entry

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to import
    them, that is the signal to promote them to omnibase_core.

Invariant:
    Models must remain inert. No helper methods that smuggle logic.
    No calculate_* methods. No validate_* beyond Pydantic field validation.
"""

from .model_agent_definition import ModelAgentDefinition
from .model_agent_routing_stats import ModelAgentRoutingStats
from .model_agent_stats_entry import ModelAgentStatsEntry
from .model_confidence_breakdown import ModelConfidenceBreakdown
from .model_emission_request import ModelEmissionRequest
from .model_emission_result import ModelEmissionResult
from .model_routing_request import ModelRoutingRequest
from .model_routing_result import ModelRoutingResult

__all__ = [
    "ModelAgentDefinition",
    "ModelAgentRoutingStats",
    "ModelAgentStatsEntry",
    "ModelConfidenceBreakdown",
    "ModelEmissionRequest",
    "ModelEmissionResult",
    "ModelRoutingRequest",
    "ModelRoutingResult",
]

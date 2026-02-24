# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Routing models - re-exports from canonical node model locations.

This package provides convenient access to all routing-related models
without requiring knowledge of which node owns each model. The canonical
definitions live in each node's ``models/`` sub-package; this module
simply re-exports them.

Compute Node Models (node_agent_routing_compute):
    - ModelRoutingRequest: Input to the routing compute node
    - ModelRoutingResult: Output from the routing compute node
    - ModelRoutingCandidate: Single routing candidate with confidence
    - ModelConfidenceBreakdown: Detailed confidence scoring breakdown
    - ModelAgentDefinition: Agent identity and activation patterns

Effect Node Models (node_routing_emission_effect):
    - ModelEmissionRequest: Input to the emission effect node
    - ModelEmissionResult: Output from the emission effect node

Reducer Models (node_routing_history_reducer):
    - ModelAgentRoutingStats: Aggregated routing statistics
    - ModelAgentStatsEntry: Per-agent statistics entry

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to import
    them, that is the signal to promote them to omnibase_core.

Invariant:
    Models must remain inert. No helper methods that smuggle logic.
    No calculate_* methods. No validate_* beyond Pydantic field validation.
"""

from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelAgentDefinition,
    ModelConfidenceBreakdown,
    ModelRoutingCandidate,
    ModelRoutingRequest,
    ModelRoutingResult,
)
from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionRequest,
    ModelEmissionResult,
)
from omniclaude.nodes.node_routing_history_reducer.models import (
    ModelAgentRoutingStats,
    ModelAgentStatsEntry,
)

__all__ = [
    "ModelAgentDefinition",
    "ModelAgentRoutingStats",
    "ModelAgentStatsEntry",
    "ModelConfidenceBreakdown",
    "ModelEmissionRequest",
    "ModelEmissionResult",
    "ModelRoutingCandidate",
    "ModelRoutingRequest",
    "ModelRoutingResult",
]

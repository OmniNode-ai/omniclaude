# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Models for the NodeRoutingHistoryReducer node.

Reducer node models - routing history statistics.
All models are frozen and inert (no logic methods).

Model Ownership:
    These models are PRIVATE to omniclaude. If external repos need to
    import them, that is the signal to promote to omnibase_core.

Invariant: ModelAgentRoutingStats is EVIDENCE, not STATE. It is a
read-only snapshot used as input to confidence scoring.
"""

from .model_agent_routing_stats import ModelAgentRoutingStats
from .model_agent_stats_entry import ModelAgentStatsEntry

__all__ = [
    "ModelAgentRoutingStats",
    "ModelAgentStatsEntry",
]

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for the OmniMemory pattern cache (OMN-2506 integration).

Defines the interface the Plan DAG Generator uses to query OmniMemory
for promoted patterns without importing the concrete implementation.
"""

from __future__ import annotations

from omniclaude.nodes.node_plan_dag_generator.protocol_promoted_pattern import (
    PromotedPatternProtocol,
)


class PatternCacheProtocol:
    """Protocol for OmniMemory pattern cache (defined in OMN-2506).

    Provides a minimal interface so the DAG generator can query for cached
    patterns without importing OMN-2506's concrete implementation.
    """

    def get_pattern(self, pattern_id: str) -> PromotedPatternProtocol | None:
        """Retrieve a promoted pattern by ID.  Returns None on cache miss."""
        raise NotImplementedError


__all__ = ["PatternCacheProtocol"]

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""NodePatternPersistenceEffect - Contract-driven effect node for learned patterns.

This package provides the NodePatternPersistenceEffect node for storing and
querying learned patterns with pluggable backends.

Capability: learned_pattern.storage

Exported Components:
    Node:
        NodePatternPersistenceEffect - The effect node class (minimal shell)

    Models:
        ModelLearnedPatternRecord - Pattern record for storage/retrieval
        ModelLearnedPatternQuery - Query parameters with filtering/pagination
        ModelLearnedPatternQueryResult - Query operation result
        ModelLearnedPatternUpsertResult - Upsert operation result

    Protocols:
        ProtocolPatternPersistence - Interface for persistence backends

Example Usage:
    ```python
    from omniclaude.nodes.node_pattern_persistence_effect import (
        NodePatternPersistenceEffect,
        ModelLearnedPatternQuery,
        ProtocolPatternPersistence,
    )

    # Resolve handler via container
    handler = await container.get_service_async(ProtocolPatternPersistence)

    # Query patterns
    query = ModelLearnedPatternQuery(
        domain="testing",
        min_confidence=0.7,
        include_general=True,
        limit=20,
    )
    result = await handler.query_patterns(query)
    ```
"""

from .models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternQueryResult,
    ModelLearnedPatternRecord,
    ModelLearnedPatternUpsertResult,
)
from .node import NodePatternPersistenceEffect
from .protocols import ProtocolPatternPersistence

__all__ = [
    # Node
    "NodePatternPersistenceEffect",
    # Models
    "ModelLearnedPatternRecord",
    "ModelLearnedPatternQuery",
    "ModelLearnedPatternQueryResult",
    "ModelLearnedPatternUpsertResult",
    # Protocols
    "ProtocolPatternPersistence",
]

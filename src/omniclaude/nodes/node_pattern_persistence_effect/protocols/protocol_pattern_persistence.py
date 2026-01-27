# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for learned pattern persistence backends.

Operation Mapping (from node contract io_operations):
    - query_patterns operation -> ProtocolPatternPersistence.query_patterns()
    - upsert_pattern operation -> ProtocolPatternPersistence.upsert_pattern()

Implementors must:
    1. Provide handler_key property identifying the backend (e.g., 'postgresql')
    2. Implement query_patterns with execution order: filters -> union -> sort -> offset -> limit
    3. Implement upsert_pattern with idempotent behavior (ON CONFLICT UPDATE)

Sort Order:
    Query results must be sorted by confidence DESC, then usage_count DESC.

Pagination Semantics:
    - total_count: Count of filtered set AFTER include_general union, BEFORE limit/offset
    - include_general: When True AND domain is specified, adds domain='general' patterns
    - General patterns count toward limit (not added after)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from uuid import UUID

from omniclaude.nodes.node_pattern_persistence_effect.models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternQueryResult,
    ModelLearnedPatternRecord,
    ModelLearnedPatternUpsertResult,
)


@runtime_checkable
class ProtocolPatternPersistence(Protocol):
    """Protocol for learned pattern persistence backends.

    This protocol defines the interface for storage backends that persist and
    retrieve learned patterns. Implementations are responsible for:

    - Storing patterns with idempotent upsert behavior
    - Querying patterns with domain filtering and confidence thresholds
    - Supporting pagination with offset/limit
    - Including 'general' domain patterns when requested

    Attributes:
        handler_key: Backend identifier used for routing (e.g., 'postgresql')

    Example usage via container resolution:
        handler = await container.get_service_async(ProtocolPatternPersistence)
        result = await handler.query_patterns(query, correlation_id=cid)
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier (e.g., 'postgresql', 'sqlite', 'memory').

        This key is used for handler routing when multiple backends are
        registered. The node contract's handler_routing.backends configuration
        maps backend keys to handler implementations.
        """
        ...

    async def query_patterns(
        self,
        query: ModelLearnedPatternQuery,
        correlation_id: UUID | None = None,
    ) -> ModelLearnedPatternQueryResult:
        """Query patterns with optional filters.

        Execution order (MUST be followed by all implementations):
            1. Apply filters (domain, min_confidence)
            2. Apply include_general union (if domain set and include_general=True)
            3. Sort by confidence DESC, usage_count DESC
            4. Apply offset
            5. Apply limit

        Args:
            query: Query parameters including domain filter, min_confidence,
                   include_general flag, limit, and offset.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelLearnedPatternQueryResult with:
                - success: True if query executed successfully
                - records: Tuple of matching ModelLearnedPatternRecord objects
                - total_count: Total matches AFTER include_general union,
                               BEFORE limit/offset (for pagination UI)
                - error: Error message if success is False
                - duration_ms: Query execution time
                - backend_type: The handler_key of the backend
                - correlation_id: The correlation ID used for this request
        """
        ...

    async def upsert_pattern(
        self,
        pattern: ModelLearnedPatternRecord,
        correlation_id: UUID | None = None,
    ) -> ModelLearnedPatternUpsertResult:
        """Insert or update a pattern (idempotent via pattern_id).

        This operation is idempotent: calling it multiple times with the same
        pattern_id will update the existing record rather than creating duplicates.

        The implementation should use ON CONFLICT UPDATE (PostgreSQL) or
        equivalent upsert mechanism for the backend.

        Args:
            pattern: The pattern record to insert or update. The pattern_id
                     field serves as the unique key for idempotent behavior.
            correlation_id: Optional correlation ID for request tracing.
                           If not provided, implementations should generate one.

        Returns:
            ModelLearnedPatternUpsertResult with:
                - success: True if upsert executed successfully
                - pattern_id: The pattern_id of the affected record
                - operation: 'insert' if new record, 'update' if existing
                - error: Error message if success is False
                - duration_ms: Upsert execution time
                - correlation_id: The correlation ID used for this request
        """
        ...

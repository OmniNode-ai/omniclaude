# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""PostgreSQL implementation of ProtocolPatternPersistence.

This handler implements the ProtocolPatternPersistence protocol for storing
and retrieving learned patterns using PostgreSQL via HandlerDb.

Handler Contract:
    Location: contracts/handlers/pattern_storage_postgres/contract.yaml
    Capabilities: learned_pattern.storage.query, learned_pattern.storage.upsert

Query Execution Order (per protocol spec):
    1. Apply filters (domain, min_confidence)
    2. Apply include_general union (if domain set and include_general=True)
    3. Sort by confidence DESC, usage_count DESC
    4. Apply offset
    5. Apply limit

HandlerDb Envelope Format:
    {
        "operation": "db.query",
        "payload": {"sql": "...", "parameters": [...]},
        "correlation_id": UUID
    }

Response Access:
    output.result.payload.rows -> List of row dicts
    output.result.status -> EnumResponseStatus
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Literal
from uuid import UUID, uuid4

from omnibase_infra.enums.enum_response_status import EnumResponseStatus
from omnibase_infra.handlers.handler_db import HandlerDb

from omniclaude.nodes.node_pattern_persistence_effect.models import (
    ModelLearnedPatternQuery,
    ModelLearnedPatternQueryResult,
    ModelLearnedPatternRecord,
    ModelLearnedPatternUpsertResult,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


def _build_db_query_envelope(
    sql: str,
    params: list[object],
    correlation_id: UUID,
) -> dict[str, object]:
    """Build HandlerDb query envelope with consistent shape.

    Always use 'db.query' for operations that return rows (SELECT, INSERT...RETURNING).

    Args:
        sql: The SQL query string with PostgreSQL parameter placeholders ($1, $2, etc.)
        params: List of parameter values in order matching placeholders
        correlation_id: UUID for request correlation and tracing

    Returns:
        Dict envelope suitable for HandlerDb.execute()
    """
    return {
        "operation": "db.query",
        "payload": {"sql": sql, "parameters": params},
        "correlation_id": correlation_id,
    }


class HandlerPatternStoragePostgres:
    """PostgreSQL implementation of ProtocolPatternPersistence.

    This handler provides persistent storage for learned patterns using PostgreSQL.
    It implements idempotent upsert via ON CONFLICT UPDATE and supports domain
    filtering with the include_general union.

    Attributes:
        handler_key: Backend identifier ('postgresql') used for handler routing.

    Thread Safety:
        Uses asyncio.Lock for thread-safe lazy initialization of HandlerDb.
        Multiple concurrent calls to query_patterns/upsert_pattern are safe.

    Example:
        handler = HandlerPatternStoragePostgres(container)
        query = ModelLearnedPatternQuery(domain="testing", min_confidence=0.7)
        result = await handler.query_patterns(query)
    """

    handler_key: str = "postgresql"

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize handler with container for lazy HandlerDb resolution.

        Args:
            container: ONEX container for service resolution. HandlerDb is
                      resolved lazily on first use to avoid blocking init.
        """
        self._container = container
        self._db: HandlerDb | None = None
        self._db_lock = asyncio.Lock()  # Prevent race on lazy init

    async def _get_db(self) -> HandlerDb:
        """Lazy initialization of HandlerDb with thread-safe locking.

        Returns:
            HandlerDb instance resolved from container.

        Note:
            Uses double-check locking pattern to minimize lock contention
            after initial initialization.
        """
        if self._db is not None:
            return self._db
        async with self._db_lock:
            if self._db is None:
                self._db = await self._container.get_service_async(HandlerDb)
        return self._db

    async def query_patterns(
        self,
        query: ModelLearnedPatternQuery,
        correlation_id: UUID | None = None,
    ) -> ModelLearnedPatternQueryResult:
        """Query patterns with optional filters.

        Execution order (per protocol spec):
            1. Apply filters (domain, min_confidence)
            2. Apply include_general union (if domain set and include_general=True)
            3. Sort by confidence DESC, usage_count DESC
            4. Apply offset
            5. Apply limit

        Args:
            query: Query parameters including domain filter, min_confidence,
                   include_general flag, limit, and offset.
            correlation_id: Optional correlation ID for request tracing.
                           Generates a new UUID if not provided.

        Returns:
            ModelLearnedPatternQueryResult with success status, matched records,
            total count for pagination, and operation metadata.
        """
        start = time.perf_counter()
        cid = correlation_id or uuid4()

        try:
            db = await self._get_db()

            # Build WHERE clause
            conditions: list[str] = []
            params: list[object] = []
            param_idx = 1

            if query.domain is not None:
                if query.include_general:
                    conditions.append(f"(domain = ${param_idx} OR domain = 'general')")
                else:
                    conditions.append(f"domain = ${param_idx}")
                params.append(query.domain)
                param_idx += 1

            if query.min_confidence > 0:
                conditions.append(f"confidence >= ${param_idx}")
                params.append(query.min_confidence)
                param_idx += 1

            where_clause = " AND ".join(conditions) if conditions else "TRUE"

            # Count query (total after union, before limit/offset)
            # nosec B608: where_clause uses parameterized values ($1, $2, etc.)
            count_sql = (
                f"SELECT COUNT(*) as cnt FROM learned_patterns WHERE {where_clause}"  # nosec B608
            )
            count_envelope = _build_db_query_envelope(count_sql, params.copy(), cid)
            count_output = await db.execute(count_envelope)

            if count_output.result is None:
                return ModelLearnedPatternQueryResult(
                    success=False,
                    error="Database count query returned no result",
                    duration_ms=(time.perf_counter() - start) * 1000,
                    correlation_id=cid,
                )

            total_count = int(count_output.result.payload.rows[0]["cnt"])

            # Data query: filters -> (union via WHERE) -> sort -> offset -> limit
            # nosec B608: where_clause uses parameterized values ($1, $2, etc.)
            data_sql = f"""
                SELECT pattern_id, domain, title, description, confidence,
                       usage_count, success_rate, example_reference
                FROM learned_patterns
                WHERE {where_clause}
                ORDER BY confidence DESC, usage_count DESC
                LIMIT ${param_idx} OFFSET ${param_idx + 1}
            """  # nosec B608
            params.extend([query.limit, query.offset])

            data_envelope = _build_db_query_envelope(data_sql, params, cid)
            data_output = await db.execute(data_envelope)

            if data_output.result is None:
                return ModelLearnedPatternQueryResult(
                    success=False,
                    error="Database data query returned no result",
                    duration_ms=(time.perf_counter() - start) * 1000,
                    correlation_id=cid,
                )

            if data_output.result.status != EnumResponseStatus.SUCCESS:
                return ModelLearnedPatternQueryResult(
                    success=False,
                    error="Database query failed",
                    duration_ms=(time.perf_counter() - start) * 1000,
                    correlation_id=cid,
                )

            records = tuple(
                ModelLearnedPatternRecord(
                    pattern_id=row["pattern_id"],
                    domain=row["domain"],
                    title=row["title"],
                    description=row["description"],
                    confidence=row["confidence"],
                    usage_count=row["usage_count"],
                    success_rate=row["success_rate"],
                    example_reference=row.get("example_reference"),
                )
                for row in data_output.result.payload.rows
            )

            return ModelLearnedPatternQueryResult(
                success=True,
                records=records,
                total_count=total_count,
                duration_ms=(time.perf_counter() - start) * 1000,
                backend_type=self.handler_key,
                correlation_id=cid,
            )

        except Exception as e:
            return ModelLearnedPatternQueryResult(
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
                correlation_id=cid,
            )

    async def upsert_pattern(
        self,
        pattern: ModelLearnedPatternRecord,
        correlation_id: UUID | None = None,
    ) -> ModelLearnedPatternUpsertResult:
        """Insert or update a pattern (idempotent via pattern_id).

        Uses PostgreSQL's ON CONFLICT UPDATE with RETURNING (xmax = 0) to
        determine whether the operation was an insert or update.

        Args:
            pattern: The pattern record to insert or update. The pattern_id
                     field serves as the unique key for idempotent behavior.
            correlation_id: Optional correlation ID for request tracing.
                           Generates a new UUID if not provided.

        Returns:
            ModelLearnedPatternUpsertResult with success status, operation type
            (insert/update), and operation metadata.
        """
        start = time.perf_counter()
        cid = correlation_id or uuid4()

        try:
            db = await self._get_db()

            sql = """
                INSERT INTO learned_patterns (
                    pattern_id, domain, title, description, confidence,
                    usage_count, success_rate, example_reference
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (pattern_id) DO UPDATE SET
                    domain = EXCLUDED.domain,
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    confidence = EXCLUDED.confidence,
                    usage_count = EXCLUDED.usage_count,
                    success_rate = EXCLUDED.success_rate,
                    example_reference = EXCLUDED.example_reference
                RETURNING (xmax = 0) as inserted
            """
            params: list[object] = [
                pattern.pattern_id,
                pattern.domain,
                pattern.title,
                pattern.description,
                pattern.confidence,
                pattern.usage_count,
                pattern.success_rate,
                pattern.example_reference,
            ]

            envelope = _build_db_query_envelope(sql, params, cid)
            output = await db.execute(envelope)

            if output.result is None:
                return ModelLearnedPatternUpsertResult(
                    success=False,
                    error="Database upsert returned no result",
                    duration_ms=(time.perf_counter() - start) * 1000,
                    correlation_id=cid,
                )

            if output.result.status != EnumResponseStatus.SUCCESS:
                return ModelLearnedPatternUpsertResult(
                    success=False,
                    error="Database upsert failed",
                    duration_ms=(time.perf_counter() - start) * 1000,
                    correlation_id=cid,
                )

            inserted = output.result.payload.rows[0]["inserted"]
            operation: Literal["insert", "update"] = "insert" if inserted else "update"

            return ModelLearnedPatternUpsertResult(
                success=True,
                pattern_id=pattern.pattern_id,
                operation=operation,
                duration_ms=(time.perf_counter() - start) * 1000,
                correlation_id=cid,
            )

        except Exception as e:
            return ModelLearnedPatternUpsertResult(
                success=False,
                error=str(e),
                duration_ms=(time.perf_counter() - start) * 1000,
                correlation_id=cid,
            )


__all__ = ["HandlerPatternStoragePostgres", "_build_db_query_envelope"]

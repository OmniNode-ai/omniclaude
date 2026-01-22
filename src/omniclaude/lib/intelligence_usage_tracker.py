#!/usr/bin/env python3
"""Intelligence Usage Tracker - Track effectiveness of patterns, intelligence, and debug data.

Monitors which intelligence is:
- Retrieved from Qdrant/Memgraph/PostgreSQL
- Applied to agent decision-making
- Effective (quality impact, success contributions)

Stores data in agent_intelligence_usage table for ROI analysis.

Key Features:
- Track retrieval of patterns, schemas, debug intelligence
- Track application (was it actually used?)
- Calculate effectiveness metrics
- Link to agent executions via correlation_id
- Non-blocking async logging with retry

Performance Targets:
- Logging time: <50ms per record
- Success rate: >95%
- Minimal overhead on manifest generation
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

from omniclaude.config import settings

logger = logging.getLogger(__name__)


@dataclass
class IntelligenceUsageRecord:
    """Record of intelligence usage during agent execution."""

    # Correlation and tracing
    correlation_id: UUID
    execution_id: UUID | None = None
    manifest_injection_id: UUID | None = None
    prompt_id: UUID | None = None

    # Agent context
    agent_name: str = "unknown"

    # Intelligence source
    intelligence_type: str = "pattern"  # pattern, schema, debug_intelligence, model, infrastructure
    intelligence_source: str = "qdrant"  # qdrant, memgraph, postgres, archon-intelligence

    # Intelligence identification
    intelligence_id: UUID | None = None
    intelligence_name: str | None = None
    collection_name: str | None = None

    # Usage details
    usage_context: str = "reference"  # reference, implementation, inspiration, validation
    usage_count: int = 1
    confidence_score: float | None = None

    # Intelligence content (snapshot)
    intelligence_snapshot: dict[str, Any] | None = None
    intelligence_summary: str | None = None

    # Query details
    query_used: str | None = None
    query_time_ms: int | None = None
    query_results_rank: int | None = None

    # Application tracking
    was_applied: bool = False
    application_details: dict[str, Any] | None = None
    file_operations_using_this: list[UUID] | None = None

    # Effectiveness tracking
    contributed_to_success: bool | None = None
    quality_impact: float | None = None

    # Metadata
    metadata: dict[str, Any] | None = None

    # Timestamps
    created_at: datetime | None = None
    applied_at: datetime | None = None

    def __post_init__(self) -> None:
        """Set default values after initialization."""
        if self.created_at is None:
            self.created_at = datetime.now(UTC)
        if self.metadata is None:
            self.metadata = {}


class IntelligenceUsageTracker:
    """
    Track intelligence usage and effectiveness.

    Provides:
    - Record when intelligence is retrieved
    - Record when intelligence is applied
    - Calculate effectiveness metrics
    - Store in agent_intelligence_usage table
    - Non-blocking async logging

    Example:
        tracker = IntelligenceUsageTracker()
        await tracker.track_retrieval(
            correlation_id=correlation_id,
            agent_name="test-agent",
            intelligence_type="pattern",
            intelligence_source="qdrant",
            intelligence_name="Node State Management Pattern",
            collection_name="execution_patterns",
            confidence_score=0.95,
            query_time_ms=450,
        )

        await tracker.track_application(
            correlation_id=correlation_id,
            intelligence_name="Node State Management Pattern",
            was_applied=True,
            quality_impact=0.85,
        )
    """

    def __init__(
        self,
        db_host: str | None = None,
        db_port: int | None = None,
        db_name: str | None = None,
        db_user: str | None = None,
        db_password: str | None = None,
        enable_tracking: bool = True,
    ):
        """
        Initialize intelligence usage tracker.

        Args:
            db_host: PostgreSQL host (default: from settings)
            db_port: PostgreSQL port (default: from settings)
            db_name: Database name (default: from settings)
            db_user: Database user (default: from settings)
            db_password: Database password (default: from settings)
            enable_tracking: Enable tracking (disable for testing)
        """
        # Use Pydantic settings for configuration
        self.db_host: str = db_host or settings.postgres_host
        self.db_port: int = db_port or settings.postgres_port
        self.db_name: str = db_name or settings.postgres_database
        self.db_user: str = db_user or settings.postgres_user
        self.db_password: str | None = db_password or settings.get_effective_postgres_password()

        # Connection pool for async database operations
        self._pool: asyncpg.Pool | None = None

        # Validate required configuration
        if not all([self.db_host, self.db_port, self.db_name, self.db_user]):
            logger.warning(
                "Database configuration incomplete. Required: POSTGRES_HOST, POSTGRES_PORT, "
                "POSTGRES_DATABASE, POSTGRES_USER. Intelligence usage tracking disabled."
            )
            self.enable_tracking = False
            return

        self.enable_tracking = enable_tracking

        if not self.db_password:
            logger.warning("POSTGRES_PASSWORD not set. Intelligence usage tracking disabled.")
            self.enable_tracking = False
            return

        # Pool configuration - use reasonable defaults
        self._pool_min_size = 2
        self._pool_max_size = 10

        # In-memory cache for pending records (for batch processing)
        self._pending_records: list[IntelligenceUsageRecord] = []
        self._max_pending = 100  # Flush after 100 records

    async def _get_pool(self) -> asyncpg.Pool:
        """
        Get or create connection pool.

        Returns:
            Connection pool instance

        Raises:
            Exception: If pool creation fails
        """
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(
                    host=self.db_host,
                    port=self.db_port,
                    database=self.db_name,
                    user=self.db_user,
                    password=self.db_password,
                    min_size=self._pool_min_size,
                    max_size=self._pool_max_size,
                )
                logger.debug(
                    f"Created asyncpg connection pool: min={self._pool_min_size}, max={self._pool_max_size}"
                )
            except Exception as e:
                logger.error(f"Failed to create connection pool: {e}")
                raise

        return self._pool

    async def close(self) -> None:
        """Close connection pool and cleanup resources."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.debug("Closed asyncpg connection pool")
            except Exception as e:
                logger.error(f"Error closing connection pool: {e}")
            finally:
                self._pool = None

    async def track_retrieval(
        self,
        correlation_id: UUID,
        agent_name: str,
        intelligence_type: str,
        intelligence_source: str,
        intelligence_name: str | None = None,
        collection_name: str | None = None,
        intelligence_id: UUID | None = None,
        confidence_score: float | None = None,
        query_time_ms: int | None = None,
        query_used: str | None = None,
        query_results_rank: int | None = None,
        intelligence_snapshot: dict[str, Any] | None = None,
        intelligence_summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Track intelligence retrieval.

        Args:
            correlation_id: Correlation ID linking to execution
            agent_name: Agent name
            intelligence_type: Type (pattern, schema, debug_intelligence, model, infrastructure)
            intelligence_source: Source (qdrant, memgraph, postgres, archon-intelligence)
            intelligence_name: Name of intelligence
            collection_name: Qdrant collection name
            intelligence_id: UUID of intelligence item
            confidence_score: Confidence/relevance score (0.0-1.0)
            query_time_ms: Query performance
            query_used: Query that retrieved this intelligence
            query_results_rank: Ranking in query results (1=top)
            intelligence_snapshot: Complete intelligence data structure
            intelligence_summary: Human-readable summary
            metadata: Additional metadata

        Returns:
            True if successful, False otherwise
        """
        if not self.enable_tracking:
            return False

        try:
            record = IntelligenceUsageRecord(
                correlation_id=correlation_id,
                agent_name=agent_name,
                intelligence_type=intelligence_type,
                intelligence_source=intelligence_source,
                intelligence_name=intelligence_name,
                collection_name=collection_name,
                intelligence_id=intelligence_id,
                confidence_score=confidence_score,
                query_time_ms=query_time_ms,
                query_used=query_used,
                query_results_rank=query_results_rank,
                intelligence_snapshot=intelligence_snapshot,
                intelligence_summary=intelligence_summary,
                metadata=metadata or {},
            )

            # Store record in database
            success = await self._store_record(record)
            if not success:
                logger.error(
                    f"Failed to store intelligence retrieval record: {intelligence_type} '{intelligence_name}' "
                    f"from {intelligence_source}"
                )
            else:
                logger.debug(
                    f"Tracked intelligence retrieval: {intelligence_type} '{intelligence_name}' "
                    f"from {intelligence_source} (confidence: {confidence_score})"
                )

            return success

        except Exception as e:
            logger.error(f"Failed to track intelligence retrieval: {e}", exc_info=True)
            return False

    async def track_application(
        self,
        correlation_id: UUID,
        intelligence_name: str,
        was_applied: bool = True,
        application_details: dict[str, Any] | None = None,
        file_operations_using_this: list[UUID] | None = None,
        contributed_to_success: bool | None = None,
        quality_impact: float | None = None,
    ) -> bool:
        """
        Track intelligence application (was it actually used?).

        Args:
            correlation_id: Correlation ID
            intelligence_name: Name of intelligence
            was_applied: Whether intelligence was actually used
            application_details: How it was applied
            file_operations_using_this: File operations that used this
            contributed_to_success: Whether this helped achieve success
            quality_impact: Estimated quality contribution (0.0-1.0)

        Returns:
            True if successful, False otherwise
        """
        if not self.enable_tracking:
            return False

        try:
            # Update existing record with application details
            success = await self._update_application(
                correlation_id=correlation_id,
                intelligence_name=intelligence_name,
                was_applied=was_applied,
                application_details=application_details,
                file_operations_using_this=file_operations_using_this,
                contributed_to_success=contributed_to_success,
                quality_impact=quality_impact,
            )
            if not success:
                logger.error(
                    f"Failed to update intelligence application record: '{intelligence_name}' "
                    f"for correlation_id {correlation_id}"
                )
            else:
                logger.debug(
                    f"Tracked intelligence application: '{intelligence_name}' "
                    f"(applied: {was_applied}, quality_impact: {quality_impact})"
                )

            return success

        except Exception as e:
            logger.error(f"Failed to track intelligence application: {e}", exc_info=True)
            return False

    async def _store_record(self, record: IntelligenceUsageRecord) -> bool:
        """Store intelligence usage record in database (fully async with connection pooling)."""
        if not self.enable_tracking:
            return True

        try:
            pool = await self._get_pool()

            # Prepare JSON data (asyncpg accepts json strings directly)
            intelligence_snapshot_json = (
                json.dumps(record.intelligence_snapshot) if record.intelligence_snapshot else None
            )
            application_details_json = (
                json.dumps(record.application_details) if record.application_details else None
            )
            metadata_json = json.dumps(record.metadata) if record.metadata else None

            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    INSERT INTO agent_intelligence_usage (
                        correlation_id,
                        execution_id,
                        manifest_injection_id,
                        prompt_id,
                        agent_name,
                        intelligence_type,
                        intelligence_source,
                        intelligence_id,
                        intelligence_name,
                        collection_name,
                        usage_context,
                        usage_count,
                        confidence_score,
                        intelligence_snapshot,
                        intelligence_summary,
                        query_used,
                        query_time_ms,
                        query_results_rank,
                        was_applied,
                        application_details,
                        file_operations_using_this,
                        contributed_to_success,
                        quality_impact,
                        metadata,
                        created_at,
                        applied_at
                    ) VALUES (
                        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
                    )
                    """,
                    str(record.correlation_id),
                    str(record.execution_id) if record.execution_id else None,
                    (str(record.manifest_injection_id) if record.manifest_injection_id else None),
                    str(record.prompt_id) if record.prompt_id else None,
                    record.agent_name,
                    record.intelligence_type,
                    record.intelligence_source,
                    str(record.intelligence_id) if record.intelligence_id else None,
                    record.intelligence_name,
                    record.collection_name,
                    record.usage_context,
                    record.usage_count,
                    record.confidence_score,
                    intelligence_snapshot_json,
                    record.intelligence_summary,
                    record.query_used,
                    record.query_time_ms,
                    record.query_results_rank,
                    record.was_applied,
                    application_details_json,
                    record.file_operations_using_this,
                    record.contributed_to_success,
                    record.quality_impact,
                    metadata_json,
                    record.created_at,
                    record.applied_at,
                )

                # Parse result to check if rows were inserted
                # asyncpg.execute returns string like "INSERT 0 0" or "INSERT 0 1"
                rows_inserted = int(result.split()[2])
                if rows_inserted == 0:
                    logger.error(
                        f"No rows inserted for intelligence usage record: "
                        f"correlation_id={record.correlation_id}, "
                        f"intelligence_name='{record.intelligence_name}'. "
                        f"This indicates a database constraint violation or other issue."
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Failed to store intelligence usage record: {e}")
            return False

    async def _update_application(
        self,
        correlation_id: UUID,
        intelligence_name: str,
        was_applied: bool,
        application_details: dict[str, Any] | None,
        file_operations_using_this: list[UUID] | None,
        contributed_to_success: bool | None,
        quality_impact: float | None,
    ) -> bool:
        """Update intelligence usage record with application details (fully async with connection pooling)."""
        if not self.enable_tracking:
            return True

        try:
            pool = await self._get_pool()

            # Prepare JSON data (asyncpg accepts json strings directly)
            application_details_json = (
                json.dumps(application_details) if application_details else None
            )

            async with pool.acquire() as conn:
                result = await conn.execute(
                    """
                    UPDATE agent_intelligence_usage
                    SET
                        was_applied = $1,
                        application_details = $2,
                        file_operations_using_this = $3,
                        contributed_to_success = $4,
                        quality_impact = $5,
                        applied_at = NOW()
                    WHERE correlation_id = $6
                        AND intelligence_name = $7
                    """,
                    was_applied,
                    application_details_json,
                    file_operations_using_this,
                    contributed_to_success,
                    quality_impact,
                    str(correlation_id),
                    intelligence_name,
                )

                # Parse result to check if rows were updated
                # asyncpg.execute returns string like "UPDATE 0" or "UPDATE 1"
                rows_updated = int(result.split()[1])
                if rows_updated == 0:
                    logger.warning(
                        f"No rows updated for intelligence application: '{intelligence_name}' "
                        f"with correlation_id {correlation_id}. Record may not exist."
                    )
                    return False

            return True

        except Exception as e:
            logger.error(f"Failed to update intelligence application: {e}")
            return False

    async def get_usage_stats(
        self,
        intelligence_name: str | None = None,
        intelligence_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Get intelligence usage statistics (fully async with connection pooling).

        Args:
            intelligence_name: Filter by intelligence name
            intelligence_type: Filter by intelligence type

        Returns:
            Dictionary with usage statistics
        """
        if not self.enable_tracking:
            return {"error": "Tracking disabled"}

        try:
            pool = await self._get_pool()

            # Build query with optional filters
            where_clauses: list[str] = []
            params: list[str] = []

            if intelligence_name:
                where_clauses.append(f"intelligence_name = ${len(params) + 1}")
                params.append(intelligence_name)

            if intelligence_type:
                where_clauses.append(f"intelligence_type = ${len(params) + 1}")
                params.append(intelligence_type)

            where_clause = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

            async with pool.acquire() as conn:
                # Query usage statistics
                result = await conn.fetchrow(  # nosec B608
                    f"""
                    SELECT
                        COUNT(*) as total_retrievals,
                        COUNT(*) FILTER (WHERE was_applied) as times_applied,
                        ROUND(
                            (COUNT(*) FILTER (WHERE was_applied)::numeric * 100) /
                            NULLIF(COUNT(*), 0),
                            2
                        ) as application_rate_percent,
                        AVG(confidence_score) as avg_confidence,
                        AVG(quality_impact) FILTER (WHERE was_applied) as avg_quality_impact,
                        COUNT(*) FILTER (WHERE contributed_to_success) as success_contributions,
                        AVG(query_time_ms) as avg_query_time_ms,
                        array_agg(DISTINCT agent_name) as agents_using_this,
                        array_agg(DISTINCT intelligence_source) as sources,
                        MIN(created_at) as first_used,
                        MAX(created_at) as last_used
                    FROM agent_intelligence_usage
                    {where_clause}
                    """,
                    *params,
                )

                return dict(result) if result else {}

        except Exception as e:
            logger.error(f"Failed to get usage stats: {e}")
            return {"error": str(e)}


# Singleton instance for convenience
_tracker_instance: IntelligenceUsageTracker | None = None


def get_tracker() -> IntelligenceUsageTracker:
    """Get singleton tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = IntelligenceUsageTracker()
    return _tracker_instance

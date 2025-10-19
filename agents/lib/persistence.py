#!/usr/bin/env python3
"""
Persistence helpers for code generation workflow.

Uses asyncpg to persist generation_sessions and generation_artifacts.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus
from uuid import UUID

import asyncpg

from .version_config import get_config


class CodegenPersistence:
    def __init__(self, dsn: Optional[str] = None) -> None:
        if dsn:
            self.dsn = dsn
        else:
            # Build DSN from configuration with URL encoding for credentials
            config = get_config()
            if not config.postgres_password:
                raise ValueError(
                    "POSTGRES_PASSWORD environment variable is required. "
                    "Please set it in your environment or .env file."
                )
            # URL-encode credentials to handle special characters
            user = quote_plus(config.postgres_user)
            password = quote_plus(config.postgres_password)
            self.dsn = f"postgresql://{user}:{password}@{config.postgres_host}:{config.postgres_port}/{config.postgres_db}"
        self._pool: Optional[asyncpg.Pool] = None

    async def _ensure_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
        return self._pool

    async def upsert_session(
        self,
        session_id: UUID,
        correlation_id: UUID,
        prd_content: str,
        status: str,
    ) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO generation_sessions(session_id, correlation_id, prd_content, status)
                VALUES($1, $2, $3, $4)
                ON CONFLICT (session_id) DO UPDATE SET
                  prd_content = EXCLUDED.prd_content,
                  status = EXCLUDED.status
                """,
                session_id,
                correlation_id,
                prd_content,
                status,
            )

    async def complete_session(self, session_id: UUID) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE generation_sessions SET completed_at = NOW(), status = 'completed'
                WHERE session_id = $1
                """,
                session_id,
            )

    async def insert_artifact(
        self,
        session_id: UUID,
        artifact_id: UUID,
        artifact_type: str,
        file_path: str,
        content: str,
        quality_score: Optional[float] = None,
        validation_status: Optional[str] = None,
        template_version: Optional[str] = None,
    ) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO generation_artifacts(
                    artifact_id, session_id, artifact_type, file_path, content, quality_score,
                    validation_status, template_version
                ) VALUES($1,$2,$3,$4,$5,$6,$7,$8)
                """,
                artifact_id,
                session_id,
                artifact_type,
                file_path,
                content,
                quality_score,
                validation_status,
                template_version,
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # =========================================================================
    # Agent Framework Schema Operations
    # =========================================================================

    # Mixin Compatibility Matrix Operations
    async def update_mixin_compatibility(
        self,
        mixin_a: str,
        mixin_b: str,
        node_type: str,
        success: bool,
        conflict_reason: Optional[str] = None,
        resolution_pattern: Optional[str] = None,
    ) -> UUID:
        """Update mixin compatibility matrix using stored function.

        Performance target: <50ms

        Args:
            mixin_a: First mixin name
            mixin_b: Second mixin name
            node_type: ONEX node type
            success: Whether combination was successful
            conflict_reason: Optional reason for conflict
            resolution_pattern: Optional resolution pattern

        Returns:
            UUID of the compatibility record
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT update_mixin_compatibility($1, $2, $3, $4, $5, $6)
                """,
                mixin_a,
                mixin_b,
                node_type,
                success,
                conflict_reason,
                resolution_pattern,
            )
            return result

    async def get_mixin_compatibility(
        self, mixin_a: str, mixin_b: str, node_type: str
    ) -> Optional[Dict[str, Any]]:
        """Get mixin compatibility record.

        Args:
            mixin_a: First mixin name
            mixin_b: Second mixin name
            node_type: ONEX node type

        Returns:
            Compatibility record or None
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM mixin_compatibility_matrix
                WHERE mixin_a = $1 AND mixin_b = $2 AND node_type = $3
                """,
                mixin_a,
                mixin_b,
                node_type,
            )
            return dict(row) if row else None

    async def get_mixin_compatibility_summary(self) -> List[Dict[str, Any]]:
        """Get aggregated mixin compatibility summary.

        Returns:
            List of summary records by node type
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM mixin_compatibility_summary")
            return [dict(row) for row in rows]

    # Pattern Feedback Log Operations
    async def record_pattern_feedback(
        self,
        session_id: UUID,
        pattern_name: str,
        detected_confidence: Optional[float],
        actual_pattern: str,
        feedback_type: str,
        user_provided: bool = False,
        contract_json: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """Record pattern matching feedback using stored function.

        Performance target: <50ms

        Args:
            session_id: Generation session ID
            pattern_name: Detected pattern name
            detected_confidence: Confidence score (0.0-1.0)
            actual_pattern: Actual pattern name
            feedback_type: Type of feedback (correct, incorrect, partial, adjusted)
            user_provided: Whether feedback is from user
            contract_json: Optional contract JSON

        Returns:
            UUID of the feedback record
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # Convert dict to JSONB string if provided
            contract_jsonb = json.dumps(contract_json) if contract_json else None

            result = await conn.fetchval(
                """
                SELECT record_pattern_feedback($1, $2, $3, $4, $5, $6, $7)
                """,
                session_id,
                pattern_name,
                detected_confidence,
                actual_pattern,
                feedback_type,
                user_provided,
                contract_jsonb,
            )
            return result

    async def get_pattern_feedback_analysis(
        self, pattern_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get pattern feedback analysis.

        Args:
            pattern_name: Optional pattern name to filter

        Returns:
            List of feedback analysis records
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if pattern_name:
                rows = await conn.fetch(
                    """
                    SELECT * FROM pattern_feedback_analysis
                    WHERE pattern_name = $1
                    """,
                    pattern_name,
                )
            else:
                rows = await conn.fetch("SELECT * FROM pattern_feedback_analysis")
            return [dict(row) for row in rows]

    # Generation Performance Metrics Operations
    async def insert_performance_metric(
        self,
        session_id: UUID,
        node_type: str,
        phase: str,
        duration_ms: int,
        memory_usage_mb: Optional[int] = None,
        cpu_percent: Optional[float] = None,
        cache_hit: bool = False,
        parallel_execution: bool = False,
        worker_count: int = 1,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert generation performance metric.

        Performance target: <50ms

        Args:
            session_id: Generation session ID
            node_type: ONEX node type
            phase: Generation phase
            duration_ms: Duration in milliseconds
            memory_usage_mb: Optional memory usage
            cpu_percent: Optional CPU usage percentage
            cache_hit: Whether this was a cache hit
            parallel_execution: Whether executed in parallel
            worker_count: Number of parallel workers
            metadata: Optional additional metadata
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            # Convert dict to JSONB string if provided
            metadata_jsonb = json.dumps(metadata) if metadata else None

            await conn.execute(
                """
                INSERT INTO generation_performance_metrics (
                    session_id, node_type, phase, duration_ms,
                    memory_usage_mb, cpu_percent, cache_hit,
                    parallel_execution, worker_count, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                """,
                session_id,
                node_type,
                phase,
                duration_ms,
                memory_usage_mb,
                cpu_percent,
                cache_hit,
                parallel_execution,
                worker_count,
                metadata_jsonb,
            )

    async def get_performance_metrics_summary(
        self, session_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """Get performance metrics summary.

        Args:
            session_id: Optional session ID to filter

        Returns:
            List of performance summary records
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if session_id:
                rows = await conn.fetch(
                    """
                    SELECT p.*
                    FROM performance_metrics_summary p
                    JOIN generation_performance_metrics g ON g.phase = p.phase
                    WHERE g.session_id = $1
                    GROUP BY p.phase, p.execution_count, p.avg_duration_ms,
                             p.p95_duration_ms, p.p99_duration_ms, p.cache_hits,
                             p.parallel_executions, p.avg_workers
                    """,
                    session_id,
                )
            else:
                rows = await conn.fetch("SELECT * FROM performance_metrics_summary")
            return [dict(row) for row in rows]

    # Template Cache Metadata Operations
    async def upsert_template_cache_metadata(
        self,
        template_name: str,
        template_type: str,
        cache_key: str,
        file_path: str,
        file_hash: str,
        size_bytes: Optional[int] = None,
        load_time_ms: Optional[int] = None,
    ) -> None:
        """Insert or update template cache metadata.

        Performance target: <50ms

        Args:
            template_name: Unique template name
            template_type: Type of template
            cache_key: Cache key
            file_path: Path to template file
            file_hash: SHA-256 hash of file
            size_bytes: Optional file size
            load_time_ms: Optional load time
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO template_cache_metadata (
                    template_name, template_type, cache_key, file_path,
                    file_hash, size_bytes, load_time_ms
                ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ON CONFLICT (template_name) DO UPDATE SET
                    cache_key = EXCLUDED.cache_key,
                    file_hash = EXCLUDED.file_hash,
                    size_bytes = EXCLUDED.size_bytes,
                    load_time_ms = EXCLUDED.load_time_ms,
                    updated_at = NOW()
                """,
                template_name,
                template_type,
                cache_key,
                file_path,
                file_hash,
                size_bytes,
                load_time_ms,
            )

    async def update_cache_metrics(
        self, template_name: str, cache_hit: bool, load_time_ms: Optional[int] = None
    ) -> None:
        """Update template cache hit/miss metrics.

        Performance target: <50ms

        Args:
            template_name: Template name
            cache_hit: Whether this was a cache hit
            load_time_ms: Optional load time (for misses)
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if cache_hit:
                await conn.execute(
                    """
                    UPDATE template_cache_metadata
                    SET cache_hits = cache_hits + 1,
                        access_count = access_count + 1,
                        last_accessed_at = NOW(),
                        updated_at = NOW()
                    WHERE template_name = $1
                    """,
                    template_name,
                )
            else:
                await conn.execute(
                    """
                    UPDATE template_cache_metadata
                    SET cache_misses = cache_misses + 1,
                        access_count = access_count + 1,
                        last_accessed_at = NOW(),
                        load_time_ms = COALESCE($2, load_time_ms),
                        updated_at = NOW()
                    WHERE template_name = $1
                    """,
                    template_name,
                    load_time_ms,
                )

    async def get_template_cache_efficiency(self) -> List[Dict[str, Any]]:
        """Get template cache efficiency metrics.

        Returns:
            List of cache efficiency records by type
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM template_cache_efficiency")
            return [dict(row) for row in rows]

    # Event Processing Metrics Operations
    async def insert_event_processing_metric(
        self,
        event_type: str,
        event_source: str,
        processing_duration_ms: int,
        success: bool,
        queue_wait_time_ms: Optional[int] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        retry_count: int = 0,
        batch_size: int = 1,
    ) -> None:
        """Insert event processing metric.

        Performance target: <50ms

        Args:
            event_type: Type of event
            event_source: Source of event
            processing_duration_ms: Processing duration
            success: Whether processing succeeded
            queue_wait_time_ms: Optional queue wait time
            error_type: Optional error type
            error_message: Optional error message
            retry_count: Number of retries
            batch_size: Batch size
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_processing_metrics (
                    event_type, event_source, processing_duration_ms,
                    success, queue_wait_time_ms, error_type,
                    error_message, retry_count, batch_size
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                event_type,
                event_source,
                processing_duration_ms,
                success,
                queue_wait_time_ms,
                error_type,
                error_message,
                retry_count,
                batch_size,
            )

    async def get_event_processing_health(
        self, event_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get event processing health metrics.

        Args:
            event_type: Optional event type to filter

        Returns:
            List of health metrics records
        """
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            if event_type:
                rows = await conn.fetch(
                    """
                    SELECT * FROM event_processing_health
                    WHERE event_type = $1
                    """,
                    event_type,
                )
            else:
                rows = await conn.fetch("SELECT * FROM event_processing_health")
            return [dict(row) for row in rows]

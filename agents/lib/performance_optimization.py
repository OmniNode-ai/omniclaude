"""
Performance Optimization for Debug Pipeline

Implements batch writes, query optimization, and memory management
for high-volume scenarios in the debug pipeline.
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List

from .db import get_pg_pool


@dataclass
class BatchOperation:
    """Represents a batch database operation."""

    operation_type: str  # 'insert', 'update', 'delete'
    table_name: str
    data: List[Dict[str, Any]]
    batch_size: int = 1000
    timeout_seconds: float = 30.0


class PerformanceOptimizer:
    """Optimizes performance for high-volume debug pipeline operations."""

    def __init__(self):
        self.pool = None
        self._batch_queue = []
        self._batch_size = 1000
        self._batch_timeout = 5.0  # seconds
        self._last_batch_time = time.time()
        self._connection_pool_size = 10
        self._write_queue = asyncio.Queue()
        self._background_writer = None
        self._shutdown = False

    async def _get_pool(self):
        """Get database pool."""
        if self.pool is None:
            self.pool = await get_pg_pool()
        return self.pool

    async def batch_insert_workflow_steps(
        self, steps: List[Dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """
        Batch insert workflow steps for better performance.

        Args:
            steps: List of workflow step dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not steps:
            return 0

        pool = await self._get_pool()
        if pool is None:
            return 0

        total_inserted = 0

        async with pool.acquire() as conn:
            # Process in batches
            for i in range(0, len(steps), batch_size):
                batch = steps[i : i + batch_size]

                # Prepare batch insert
                values = []
                for step in batch:
                    values.append(
                        (
                            step.get("id"),
                            step.get("run_id"),
                            step.get("step_index"),
                            step.get("phase"),
                            step.get("correlation_id"),
                            step.get("applied_tf_id"),
                            step.get("started_at"),
                            step.get("completed_at"),
                            step.get("duration_ms"),
                            step.get("success"),
                            step.get("error"),
                        )
                    )

                # Execute batch insert
                await conn.executemany(
                    """
                    INSERT INTO workflow_steps (
                        id, run_id, step_index, phase, correlation_id, applied_tf_id,
                        started_at, completed_at, duration_ms, success, error
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )

                total_inserted += len(batch)

        return total_inserted

    async def batch_insert_llm_calls(
        self, calls: List[Dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """
        Batch insert LLM calls for better performance.

        Args:
            calls: List of LLM call dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not calls:
            return 0

        pool = await self._get_pool()
        if pool is None:
            return 0

        total_inserted = 0

        async with pool.acquire() as conn:
            # Process in batches
            for i in range(0, len(calls), batch_size):
                batch = calls[i : i + batch_size]

                # Prepare batch insert
                values = []
                for call in batch:
                    values.append(
                        (
                            call.get("id"),
                            call.get("run_id"),
                            call.get("model"),
                            call.get("provider"),
                            call.get("request_tokens"),
                            call.get("response_tokens"),
                            call.get("input_tokens"),
                            call.get("output_tokens"),
                            call.get("computed_cost_usd"),
                            call.get("request_data"),
                            call.get("response_data"),
                            call.get("created_at"),
                        )
                    )

                # Execute batch insert
                await conn.executemany(
                    """
                    INSERT INTO llm_calls (
                        id, run_id, model, provider, request_tokens, response_tokens,
                        input_tokens, output_tokens, computed_cost_usd, request_data,
                        response_data, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )

                total_inserted += len(batch)

        return total_inserted

    async def batch_insert_error_events(
        self, events: List[Dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """
        Batch insert error events for better performance.

        Args:
            events: List of error event dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not events:
            return 0

        pool = await self._get_pool()
        if pool is None:
            return 0

        total_inserted = 0

        async with pool.acquire() as conn:
            # Process in batches
            for i in range(0, len(events), batch_size):
                batch = events[i : i + batch_size]

                # Prepare batch insert
                values = []
                for event in batch:
                    values.append(
                        (
                            event.get("id"),
                            event.get("run_id"),
                            event.get("correlation_id"),
                            event.get("error_type"),
                            event.get("message"),
                            json.dumps(event.get("details", {}), default=str),
                        )
                    )

                # Execute batch insert
                await conn.executemany(
                    """
                    INSERT INTO error_events (
                        id, run_id, correlation_id, error_type, message, details
                    ) VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )

                total_inserted += len(batch)

        return total_inserted

    async def batch_insert_success_events(
        self, events: List[Dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """
        Batch insert success events for better performance.

        Args:
            events: List of success event dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not events:
            return 0

        pool = await self._get_pool()
        if pool is None:
            return 0

        total_inserted = 0

        async with pool.acquire() as conn:
            # Process in batches
            for i in range(0, len(events), batch_size):
                batch = events[i : i + batch_size]

                # Prepare batch insert
                values = []
                for event in batch:
                    values.append(
                        (
                            event.get("id"),
                            event.get("run_id"),
                            event.get("task_id"),
                            event.get("correlation_id"),
                            event.get("approval_source", "auto"),
                            event.get("is_golden", False),
                        )
                    )

                # Execute batch insert
                await conn.executemany(
                    """
                    INSERT INTO success_events (
                        id, run_id, task_id, correlation_id, approval_source, is_golden
                    ) VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )

                total_inserted += len(batch)

        return total_inserted

    async def batch_insert_lineage_edges(
        self, edges: List[Dict[str, Any]], batch_size: int = 1000
    ) -> int:
        """
        Batch insert lineage edges for better performance.

        Args:
            edges: List of lineage edge dictionaries
            batch_size: Number of records per batch

        Returns:
            Number of records inserted
        """
        if not edges:
            return 0

        pool = await self._get_pool()
        if pool is None:
            return 0

        total_inserted = 0

        async with pool.acquire() as conn:
            # Process in batches
            for i in range(0, len(edges), batch_size):
                batch = edges[i : i + batch_size]

                # Prepare batch insert
                values = []
                for edge in batch:
                    values.append(
                        (
                            edge.get("id"),
                            edge.get("src_type"),
                            edge.get("src_id"),
                            edge.get("dst_type"),
                            edge.get("dst_id"),
                            edge.get("edge_type"),
                            json.dumps(edge.get("attributes", {}), default=str),
                            edge.get("created_at"),
                        )
                    )

                # Execute batch insert
                await conn.executemany(
                    """
                    INSERT INTO lineage_edges (
                        id, src_type, src_id, dst_type, dst_id, edge_type, attributes, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    values,
                )

                total_inserted += len(batch)

        return total_inserted

    async def optimize_queries(self) -> Dict[str, Any]:
        """
        Analyze and optimize database queries.

        Returns:
            Dictionary with optimization recommendations
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        optimizations = {}

        async with pool.acquire() as conn:
            # Check for missing indexes (simplified for PostgreSQL)
            missing_indexes = await conn.fetch(
                """
                SELECT
                    schemaname,
                    tablename,
                    attname,
                    n_distinct,
                    correlation
                FROM pg_stats
                WHERE schemaname = 'public'
                AND n_distinct > 100
                AND tablename IN ('workflow_steps', 'llm_calls', 'error_events', 'success_events', 'lineage_edges')
                """
            )

            if missing_indexes:
                optimizations["missing_indexes"] = [
                    {
                        "table": row["tablename"],
                        "column": row["attname"],
                        "distinct_values": row["n_distinct"],
                        "correlation": row["correlation"],
                    }
                    for row in missing_indexes
                ]

            # Check table sizes
            table_sizes = await conn.fetch(
                """
                SELECT
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size,
                    pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
                FROM pg_tables
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
                """
            )

            optimizations["table_sizes"] = [
                {
                    "table": row["tablename"],
                    "size": row["size"],
                    "size_bytes": row["size_bytes"],
                }
                for row in table_sizes
            ]

            # Check for long-running queries (simplified)
            try:
                long_queries = await conn.fetch(
                    """
                    SELECT
                        query,
                        calls,
                        total_exec_time,
                        mean_exec_time,
                        rows
                    FROM pg_stat_statements
                    WHERE mean_exec_time > 1000  -- queries taking more than 1 second on average
                    ORDER BY mean_exec_time DESC
                    LIMIT 10
                    """
                )
            except Exception:
                # pg_stat_statements might not be available
                long_queries = []

            if long_queries:
                optimizations["slow_queries"] = [
                    {
                        "query": (
                            row["query"][:200] + "..."
                            if len(row["query"]) > 200
                            else row["query"]
                        ),
                        "calls": row["calls"],
                        "total_time": row["total_exec_time"],
                        "mean_time": row["mean_exec_time"],
                        "rows": row["rows"],
                    }
                    for row in long_queries
                ]

        return optimizations

    async def create_performance_indexes(self) -> List[str]:
        """
        Create performance indexes for common queries.

        Returns:
            List of created index names
        """
        pool = await self._get_pool()
        if pool is None:
            return []

        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_workflow_steps_run_id ON workflow_steps(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_workflow_steps_phase ON workflow_steps(phase)",
            "CREATE INDEX IF NOT EXISTS idx_workflow_steps_created_at ON workflow_steps(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_run_id ON llm_calls(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_model ON llm_calls(model)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_created_at ON llm_calls(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_error_events_run_id ON error_events(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_error_events_error_type ON error_events(error_type)",
            "CREATE INDEX IF NOT EXISTS idx_error_events_created_at ON error_events(created_at)",
            "CREATE INDEX IF NOT EXISTS idx_success_events_run_id ON success_events(run_id)",
            "CREATE INDEX IF NOT EXISTS idx_success_events_is_golden ON success_events(is_golden)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_edges_src ON lineage_edges(src_type, src_id)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_edges_dst ON lineage_edges(dst_type, dst_id)",
            "CREATE INDEX IF NOT EXISTS idx_lineage_edges_type ON lineage_edges(edge_type)",
        ]

        created_indexes = []

        async with pool.acquire() as conn:
            for index_sql in indexes:
                try:
                    await conn.execute(index_sql)
                    index_name = index_sql.split("idx_")[1].split(" ")[0]
                    created_indexes.append(index_name)
                except Exception as e:
                    print(f"Warning: Failed to create index: {e}")

        return created_indexes

    async def batch_write_with_pooling(
        self, operations: List[BatchOperation]
    ) -> Dict[str, int]:
        """
        Optimized batch writes with connection pooling and smart batching.

        Args:
            operations: List of batch operations to execute

        Returns:
            Dictionary with operation results
        """
        if not operations:
            return {}

        pool = await self._get_pool()
        if pool is None:
            return {}

        results = {}
        start_time = time.time()

        # Group operations by type for better batching
        grouped_ops = {}
        for op in operations:
            key = f"{op.operation_type}_{op.table_name}"
            if key not in grouped_ops:
                grouped_ops[key] = []
            grouped_ops[key].append(op)

        # Execute grouped operations in parallel
        tasks = []
        for key, ops in grouped_ops.items():
            task = self._execute_grouped_operations(key, ops, pool)
            tasks.append(task)

        # Wait for all operations to complete
        operation_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for i, result in enumerate(operation_results):
            key = list(grouped_ops.keys())[i]
            if isinstance(result, Exception):
                print(f"Warning: Batch operation failed for {key}: {result}")
                results[key] = 0
            else:
                results[key] = result

        elapsed_ms = (time.time() - start_time) * 1000
        print(f"[PerformanceOptimizer] Batch write completed in {elapsed_ms:.0f}ms")

        return results

    async def _execute_grouped_operations(
        self, key: str, operations: List[BatchOperation], pool
    ) -> int:
        """Execute a group of similar operations."""
        total_affected = 0

        async with pool.acquire() as conn:
            for op in operations:
                try:
                    if op.operation_type == "insert":
                        affected = await self._batch_insert_operation(conn, op)
                    elif op.operation_type == "update":
                        affected = await self._batch_update_operation(conn, op)
                    elif op.operation_type == "delete":
                        affected = await self._batch_delete_operation(conn, op)
                    else:
                        print(f"Warning: Unknown operation type: {op.operation_type}")
                        continue

                    total_affected += affected
                except Exception as e:
                    print(f"Warning: Operation failed for {key}: {e}")

        return total_affected

    async def _batch_insert_operation(self, conn, op: BatchOperation) -> int:
        """Execute batch insert operation."""
        if not op.data:
            return 0

        # Get table schema for dynamic insert
        table_name = op.table_name
        columns = list(op.data[0].keys())

        # Build dynamic INSERT statement
        placeholders = ", ".join([f"${i+1}" for i in range(len(columns))])
        columns_str = ", ".join(columns)

        insert_sql = f"""
        INSERT INTO {table_name} ({columns_str})
        VALUES ({placeholders})
        ON CONFLICT DO NOTHING
        """

        # Prepare batch data
        values = []
        for record in op.data:
            row = tuple(record.get(col) for col in columns)
            values.append(row)

        # Execute batch insert
        await conn.executemany(insert_sql, values)
        return len(values)

    async def _batch_update_operation(self, conn, op: BatchOperation) -> int:
        """Execute batch update operation."""
        if not op.data:
            return 0

        # For updates, we need to know the primary key
        # This is a simplified implementation
        table_name = op.table_name

        # Assume 'id' is the primary key
        update_sql = f"""
        UPDATE {table_name}
        SET {', '.join([f'{col} = ${i+2}' for i, col in enumerate(op.data[0].keys()) if col != 'id'])}
        WHERE id = $1
        """

        # Prepare batch data
        values = []
        for record in op.data:
            row = [record.get("id")] + [
                record.get(col) for col in record.keys() if col != "id"
            ]
            values.append(tuple(row))

        # Execute batch update
        await conn.executemany(update_sql, values)
        return len(values)

    async def _batch_delete_operation(self, conn, op: BatchOperation) -> int:
        """Execute batch delete operation."""
        if not op.data:
            return 0

        # Assume 'id' is the primary key for deletion
        table_name = op.table_name
        delete_sql = f"DELETE FROM {table_name} WHERE id = ANY($1::uuid[])"

        # Extract IDs
        ids = [record.get("id") for record in op.data if record.get("id")]

        if ids:
            await conn.execute(delete_sql, ids)
            return len(ids)

        return 0

    async def async_database_write(self, table: str, data: Dict[str, Any]) -> str:
        """
        Non-blocking database writes for non-critical data.

        Args:
            table: Table name to write to
            data: Data to write

        Returns:
            Write operation ID
        """
        write_id = f"write_{int(time.time() * 1000)}"

        # Queue the write for background processing
        await self._write_queue.put(
            {"id": write_id, "table": table, "data": data, "timestamp": time.time()}
        )

        # Start background writer if not running
        if self._background_writer is None:
            self._background_writer = asyncio.create_task(
                self._background_write_worker()
            )

        return write_id

    async def _background_write_worker(self):
        """Background worker for async database writes."""
        batch = []
        batch_size = 100
        batch_timeout = 5.0

        while not self._shutdown:
            try:
                # Get item from queue with timeout
                item = await asyncio.wait_for(
                    self._write_queue.get(), timeout=batch_timeout
                )
                batch.append(item)

                # Process batch when full or timeout
                if len(batch) >= batch_size:
                    await self._process_write_batch(batch)
                    batch = []

            except asyncio.TimeoutError:
                # Process remaining batch on timeout
                if batch:
                    await self._process_write_batch(batch)
                    batch = []
            except asyncio.CancelledError:
                # Process remaining batch on cancellation
                if batch:
                    await self._process_write_batch(batch)
                break
            except Exception as e:
                print(f"Warning: Background write worker error: {e}")
                await asyncio.sleep(1)

    async def _process_write_batch(self, batch: List[Dict[str, Any]]):
        """Process a batch of async writes."""
        if not batch:
            return

        pool = await self._get_pool()
        if pool is None:
            return

        try:
            async with pool.acquire() as conn:
                # Group by table
                by_table = {}
                for item in batch:
                    table = item["table"]
                    if table not in by_table:
                        by_table[table] = []
                    by_table[table].append(item["data"])

                # Execute batch writes per table
                for table, records in by_table.items():
                    if records:
                        await self._batch_insert_operation(
                            conn,
                            BatchOperation(
                                operation_type="insert", table_name=table, data=records
                            ),
                        )
        except Exception as e:
            print(f"Warning: Failed to process write batch: {e}")

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get current performance metrics.

        Returns:
            Dictionary with performance metrics
        """
        pool = await self._get_pool()
        if pool is None:
            return {}

        metrics = {}

        async with pool.acquire() as conn:
            # Get table row counts
            tables = [
                "workflow_steps",
                "llm_calls",
                "error_events",
                "success_events",
                "lineage_edges",
            ]
            row_counts = {}

            for table in tables:
                try:
                    count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
                    row_counts[table] = count
                except Exception as e:
                    print(f"Warning: Failed to get count for {table}: {e}")
                    row_counts[table] = 0

            metrics["row_counts"] = row_counts

            # Get queue sizes
            metrics["write_queue_size"] = self._write_queue.qsize()
            metrics["batch_queue_size"] = len(self._batch_queue)

            # Get connection pool stats
            if hasattr(pool, "_pool"):
                metrics["pool_size"] = (
                    len(pool._pool) if hasattr(pool._pool, "__len__") else "unknown"
                )
            else:
                metrics["pool_size"] = "unknown"

        return metrics

    async def close(self):
        """
        Cleanup method to properly shutdown background tasks.

        Should be called when the optimizer is no longer needed.
        """
        # Set shutdown flag
        self._shutdown = True

        # Cancel background writer task if it exists
        if self._background_writer is not None:
            self._background_writer.cancel()
            try:
                await self._background_writer
            except asyncio.CancelledError:
                pass
            self._background_writer = None

        # Close database pool if it exists
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    async def __aenter__(self):
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - ensures cleanup."""
        await self.close()
        return False


# Global performance optimizer instance
performance_optimizer = PerformanceOptimizer()


async def batch_insert_workflow_steps(steps: List[Dict[str, Any]]) -> int:
    """Batch insert workflow steps for better performance."""
    return await performance_optimizer.batch_insert_workflow_steps(steps)


async def batch_insert_llm_calls(calls: List[Dict[str, Any]]) -> int:
    """Batch insert LLM calls for better performance."""
    return await performance_optimizer.batch_insert_llm_calls(calls)


async def batch_insert_error_events(events: List[Dict[str, Any]]) -> int:
    """Batch insert error events for better performance."""
    return await performance_optimizer.batch_insert_error_events(events)


async def batch_insert_success_events(events: List[Dict[str, Any]]) -> int:
    """Batch insert success events for better performance."""
    return await performance_optimizer.batch_insert_success_events(events)


async def batch_insert_lineage_edges(edges: List[Dict[str, Any]]) -> int:
    """Batch insert lineage edges for better performance."""
    return await performance_optimizer.batch_insert_lineage_edges(edges)


async def optimize_database_performance() -> Dict[str, Any]:
    """Analyze and optimize database performance."""
    return await performance_optimizer.optimize_queries()


async def create_performance_indexes() -> List[str]:
    """Create performance indexes for common queries."""
    return await performance_optimizer.create_performance_indexes()


async def batch_write_with_pooling(operations: List[BatchOperation]) -> Dict[str, int]:
    """Optimized batch writes with connection pooling and smart batching."""
    return await performance_optimizer.batch_write_with_pooling(operations)


async def async_database_write(table: str, data: Dict[str, Any]) -> str:
    """Non-blocking database writes for non-critical data."""
    return await performance_optimizer.async_database_write(table, data)


async def get_performance_metrics() -> Dict[str, Any]:
    """Get current performance metrics."""
    return await performance_optimizer.get_performance_metrics()

"""
PostgreSQL client for tracing data persistence.

Provides async connection pooling and efficient trace logging with
minimal performance overhead (<2ms target).

Matches the Intelligence Hook System database schema:
- execution_traces: Master record for all execution traces
- hook_executions: Individual hook execution records
"""

import asyncio
import os
import logging
from typing import Dict, Optional, Any, List
from datetime import datetime
from contextlib import asynccontextmanager
from uuid import UUID
import json

try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False


logger = logging.getLogger(__name__)


class PostgresTracingClient:
    """
    Async PostgreSQL client for tracing data with connection pooling.

    Designed for fire-and-forget trace logging with minimal overhead.
    Gracefully degrades if database is unavailable.

    Supports:
    - Execution trace creation and completion
    - Hook execution recording
    - Context-aware tracing with correlation IDs
    - Silent failure mode (never breaks hook execution)
    """

    def __init__(
        self,
        connection_url: Optional[str] = None,
        min_pool_size: int = 5,
        max_pool_size: int = 20,
        command_timeout: float = 10.0,
        max_retry_attempts: int = 3,
        retry_base_delay: float = 0.5,
    ):
        """
        Initialize PostgreSQL tracing client.

        Args:
            connection_url: PostgreSQL connection URL. If None, uses env var.
            min_pool_size: Minimum number of connections in pool (default: 5)
            max_pool_size: Maximum number of connections in pool (default: 20)
            command_timeout: Query timeout in seconds (default: 10.0)
            max_retry_attempts: Maximum retry attempts for failed operations (default: 3)
            retry_base_delay: Base delay in seconds for exponential backoff (default: 0.5)
        """
        self.connection_url = connection_url or self._get_connection_url()
        self.pool: Optional["asyncpg.Pool"] = None
        self._pool_lock = asyncio.Lock()
        self._initialized = False
        self._connection_failed = False

        # Pool configuration
        self.min_pool_size = min_pool_size
        self.max_pool_size = max_pool_size
        self.command_timeout = command_timeout

        # Retry configuration
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_delay = retry_base_delay

    def _get_connection_url(self) -> str:
        """Construct connection URL from environment variables."""
        # Prioritize TRACEABILITY_DB_URL_EXTERNAL for Intelligence Hook System
        traceability_url = os.getenv("TRACEABILITY_DB_URL_EXTERNAL")
        if traceability_url:
            return traceability_url

        # Fallback to Supabase connection format
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

        if supabase_url and supabase_key:
            # Extract host from Supabase URL
            # Format: https://PROJECT.supabase.co
            import re

            match = re.search(r"https://([^.]+)\.supabase\.co", supabase_url)
            if match:
                project_id = match.group(1)
                # Supabase PostgreSQL connection
                host = f"{project_id}.supabase.co"
                return f"postgresql://postgres.{project_id}:{supabase_key}@{host}:5432/postgres"

        # Fallback to direct PostgreSQL connection
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5436")
        db = os.getenv("POSTGRES_DB", "archon")
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "")

        return f"postgresql://{user}:{password}@{host}:{port}/{db}"

    async def initialize(self) -> bool:
        """
        Initialize connection pool with retry logic.

        Returns:
            True if successful, False otherwise
        """
        if not ASYNCPG_AVAILABLE:
            return False

        if self._initialized or self._connection_failed:
            return self._initialized

        async with self._pool_lock:
            if self._initialized:
                return True

            attempt = 0
            last_error = None

            while attempt < self.max_retry_attempts:
                try:
                    logger.info(f"Initializing connection pool (attempt {attempt + 1}/{self.max_retry_attempts})")

                    self.pool = await asyncpg.create_pool(
                        self.connection_url,
                        min_size=self.min_pool_size,
                        max_size=self.max_pool_size,
                        command_timeout=self.command_timeout,
                        server_settings={
                            "application_name": "archon_intelligence_tracing",
                            "jit": "off",  # Disable JIT for short queries
                        },
                    )

                    # Verify connection with simple query
                    async with self.pool.acquire() as conn:
                        await conn.fetchval("SELECT 1")

                    self._initialized = True
                    logger.info(
                        "PostgreSQL connection pool initialized successfully",
                        extra={"pool_size": f"{self.min_pool_size}-{self.max_pool_size}"},
                    )
                    return True

                except Exception as e:
                    last_error = e
                    attempt += 1

                    if attempt < self.max_retry_attempts:
                        # Exponential backoff
                        delay = self.retry_base_delay * (2 ** (attempt - 1))
                        logger.warning(
                            f"Connection attempt {attempt} failed, retrying in {delay}s",
                            extra={"error": str(e), "attempt": attempt},
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            "Failed to initialize connection pool after all retries",
                            extra={"error": str(e), "attempts": attempt},
                        )

            # Silent failure - don't break hook execution
            self._connection_failed = True
            import sys

            print(
                f"[Tracing] Failed to initialize database pool after {self.max_retry_attempts} attempts: {last_error}",
                file=sys.stderr,
            )
            return False

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            self._initialized = False

    @asynccontextmanager
    async def acquire(self):
        """Acquire connection from pool with error handling."""
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            # Return dummy connection that does nothing
            yield None
            return

        try:
            async with self.pool.acquire() as conn:
                yield conn
        except Exception as e:
            import sys

            print(f"[Tracing] Connection error: {e}", file=sys.stderr)
            yield None

    async def log_hook_execution(
        self,
        correlation_id: str,
        hook_name: str,
        tool_name: str,
        duration_ms: int,
        success: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log hook execution to database (non-blocking).

        Args:
            correlation_id: Correlation ID for tracing
            hook_name: Name of hook (e.g., "pre-tool-use-quality")
            tool_name: Tool being intercepted
            duration_ms: Execution duration in milliseconds
            success: Whether hook succeeded
            metadata: Additional metadata (violations, corrections, etc.)

        Returns:
            True if logged successfully, False otherwise
        """
        if not self._initialized and not await self.initialize():
            return False

        try:
            async with self.acquire() as conn:
                if not conn:
                    return False

                # Insert into hook_executions table
                await conn.execute(
                    """
                    INSERT INTO hook_executions (
                        execution_id,
                        correlation_id,
                        hook_type,
                        tool_name,
                        hook_script,
                        started_at,
                        completed_at,
                        duration_ms,
                        status,
                        success,
                        context
                    ) VALUES (
                        gen_random_uuid(),
                        $1::uuid,
                        $2,
                        $3,
                        $4,
                        NOW() - ($5::integer * INTERVAL '1 millisecond'),
                        NOW(),
                        $5,
                        $6,
                        $7,
                        $8::jsonb
                    )
                """,
                    correlation_id,
                    hook_name,
                    tool_name,
                    hook_name,  # hook_script same as hook_name for now
                    duration_ms,
                    "success" if success else "error",
                    success,
                    json.dumps(metadata or {}),
                )
                return True
        except Exception as e:
            # Silent failure - never break hook execution
            import sys

            print(f"[Tracing] Failed to log hook execution: {e}", file=sys.stderr)
            return False

    async def log_quality_metrics(
        self,
        correlation_id: str,
        file_path: str,
        language: str,
        violations_found: int,
        corrections_applied: int,
        quality_score: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Log quality metrics to database.

        Args:
            correlation_id: Correlation ID for tracing
            file_path: File being analyzed
            language: Programming language
            violations_found: Number of violations detected
            corrections_applied: Number of corrections auto-applied
            quality_score: Optional quality score (0.0-1.0)
            metadata: Additional metadata

        Returns:
            True if logged successfully, False otherwise
        """
        if not self._initialized and not await self.initialize():
            return False

        try:
            async with self.acquire() as conn:
                if not conn:
                    return False

                # Log to quality_metrics table (create if doesn't exist)
                # For now, store in hook_executions context
                extended_metadata = metadata or {}
                extended_metadata.update(
                    {
                        "file_path": file_path,
                        "language": language,
                        "violations_found": violations_found,
                        "corrections_applied": corrections_applied,
                        "quality_score": quality_score,
                    }
                )

                await conn.execute(
                    """
                    UPDATE hook_executions
                    SET context = context || $2::jsonb
                    WHERE correlation_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT 1
                """,
                    correlation_id,
                    json.dumps(extended_metadata),
                )
                return True
        except Exception as e:
            import sys

            print(f"[Tracing] Failed to log quality metrics: {e}", file=sys.stderr)
            return False

    # ===== New methods matching the actual schema =====

    async def create_execution_trace(
        self,
        correlation_id: UUID,
        root_id: UUID,
        parent_id: Optional[UUID],
        session_id: UUID,
        source: str,
        prompt_text: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[UUID]:
        """
        Create a new execution trace record.

        Args:
            correlation_id: Unique identifier for this execution chain
            root_id: Root trace ID in nested execution
            parent_id: Parent execution ID (None for root traces)
            session_id: Claude Code session identifier
            source: Source of execution (e.g., "pre-tool-use", "user-prompt-submit")
            prompt_text: User's prompt text
            user_id: Optional user identifier
            context: Additional context as JSON
            tags: Optional tags for categorization

        Returns:
            UUID of the created trace record, or None if failed
        """
        if not self._initialized and not await self.initialize():
            return None

        query = """
            INSERT INTO execution_traces (
                correlation_id, root_id, parent_id, session_id, user_id,
                source, prompt_text, context, tags, status, started_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, 'in_progress', NOW())
            RETURNING id
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    return None

                row = await conn.fetchrow(
                    query,
                    correlation_id,
                    root_id,
                    parent_id,
                    session_id,
                    user_id,
                    source,
                    prompt_text,
                    json.dumps(context) if context else None,
                    tags,
                )
                trace_id = row["id"]
                logger.debug(f"Created execution trace: {trace_id} (correlation: {correlation_id})")
                return trace_id
        except Exception as e:
            logger.error(f"Failed to create execution trace: {e}")
            import sys

            print(f"[Tracing] Failed to create execution trace: {e}", file=sys.stderr)
            return None

    async def complete_execution_trace(
        self, correlation_id: UUID, success: bool, error_message: Optional[str] = None, error_type: Optional[str] = None
    ) -> bool:
        """
        Mark an execution trace as completed.

        Args:
            correlation_id: Correlation ID of the trace to complete
            success: Whether the execution succeeded
            error_message: Error message if failed
            error_type: Type of error if failed

        Returns:
            True if successful, False otherwise
        """
        if not self._initialized and not await self.initialize():
            return False

        query = """
            UPDATE execution_traces
            SET
                completed_at = NOW(),
                duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
                status = CASE WHEN $2 THEN 'completed' ELSE 'failed' END,
                success = $2,
                error_message = $3,
                error_type = $4,
                updated_at = NOW()
            WHERE correlation_id = $1
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    return False

                await conn.execute(query, correlation_id, success, error_message, error_type)
                logger.debug(f"Completed execution trace: {correlation_id} (success: {success})")
                return True
        except Exception as e:
            logger.error(f"Failed to complete execution trace: {e}")
            import sys

            print(f"[Tracing] Failed to complete execution trace: {e}", file=sys.stderr)
            return False

    async def record_hook_execution(
        self,
        trace_id: UUID,
        hook_type: str,
        hook_name: str,
        execution_order: int,
        tool_name: Optional[str] = None,
        file_path: Optional[str] = None,
        duration_ms: Optional[float] = None,
        status: str = "completed",
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        modifications_made: Optional[Dict[str, Any]] = None,
        rag_query_performed: bool = False,
        rag_results: Optional[Dict[str, Any]] = None,
        quality_check_performed: bool = False,
        quality_results: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        error_stack: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[UUID]:
        """
        Record a hook execution.

        Args:
            trace_id: ID of the parent execution trace
            hook_type: Type of hook (e.g., "PreToolUse", "PostToolUse")
            hook_name: Name of the hook (e.g., "quality-enforcer")
            execution_order: Order of execution within the trace
            tool_name: Name of the tool being used
            file_path: File path if applicable
            duration_ms: Execution duration in milliseconds
            status: Execution status ("in_progress", "completed", "failed")
            input_data: Input data to the hook
            output_data: Output data from the hook
            modifications_made: Any modifications made by the hook
            rag_query_performed: Whether RAG query was performed
            rag_results: Results from RAG query
            quality_check_performed: Whether quality check was performed
            quality_results: Results from quality check
            error_message: Error message if failed
            error_type: Type of error if failed
            error_stack: Stack trace if failed
            metadata: Additional metadata

        Returns:
            UUID of the created hook execution record, or None if failed
        """
        if not self._initialized and not await self.initialize():
            return None

        query = """
            INSERT INTO hook_executions (
                trace_id, hook_type, hook_name, execution_order,
                tool_name, file_path, duration_ms, status,
                input_data, output_data, modifications_made,
                rag_query_performed, rag_results,
                quality_check_performed, quality_results,
                error_message, error_type, error_stack, metadata,
                started_at, completed_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11::jsonb,
                $12, $13::jsonb, $14, $15::jsonb,
                $16, $17, $18, $19::jsonb, NOW(),
                CASE WHEN $8 = 'completed' OR $8 = 'failed' THEN NOW() ELSE NULL END
            )
            RETURNING id
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    return None

                row = await conn.fetchrow(
                    query,
                    trace_id,
                    hook_type,
                    hook_name,
                    execution_order,
                    tool_name,
                    file_path,
                    duration_ms,
                    status,
                    json.dumps(input_data) if input_data else None,
                    json.dumps(output_data) if output_data else None,
                    json.dumps(modifications_made) if modifications_made else None,
                    rag_query_performed,
                    json.dumps(rag_results) if rag_results else None,
                    quality_check_performed,
                    json.dumps(quality_results) if quality_results else None,
                    error_message,
                    error_type,
                    error_stack,
                    json.dumps(metadata) if metadata else None,
                )
                hook_id = row["id"]
                logger.debug(f"Recorded hook execution: {hook_id} ({hook_name})")
                return hook_id
        except Exception as e:
            logger.error(f"Failed to record hook execution: {e}")
            import sys

            print(f"[Tracing] Failed to record hook execution: {e}", file=sys.stderr)
            return None

    async def get_trace_by_correlation_id(self, correlation_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get execution trace by correlation ID.

        Args:
            correlation_id: Correlation ID to look up

        Returns:
            Dict containing trace data, or None if not found
        """
        if not self._initialized and not await self.initialize():
            return None

        query = """
            SELECT * FROM execution_traces
            WHERE correlation_id = $1
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    return None

                row = await conn.fetchrow(query, correlation_id)
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error(f"Failed to get trace by correlation ID: {e}")
            return None

    async def get_hook_executions_for_trace(self, trace_id: UUID) -> List[Dict[str, Any]]:
        """
        Get all hook executions for a trace.

        Args:
            trace_id: Trace ID to get hooks for

        Returns:
            List of hook execution records
        """
        if not self._initialized and not await self.initialize():
            return []

        query = """
            SELECT * FROM hook_executions
            WHERE trace_id = $1
            ORDER BY execution_order ASC
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    return []

                rows = await conn.fetch(query, trace_id)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get hook executions: {e}")
            return []

    # ===== Pydantic Model Integration Methods =====

    async def insert_trace(self, trace: "ExecutionTrace") -> Optional[UUID]:
        """
        Insert an ExecutionTrace Pydantic model into the database.

        Args:
            trace: ExecutionTrace model instance

        Returns:
            UUID of the created trace record, or None if failed

        Example:
            >>> from hooks.lib.tracing import create_new_trace
            >>> trace = create_new_trace(source="claude_code", session_id=uuid4())
            >>> trace_id = await client.insert_trace(trace)
        """
        return await self.create_execution_trace(
            correlation_id=trace.correlation_id,
            root_id=trace.root_id,
            parent_id=trace.parent_id,
            session_id=trace.session_id,
            source=trace.source,
            prompt_text=trace.prompt_text,
            user_id=trace.user_id,
            context=trace.context,
            tags=trace.tags,
        )

    async def update_trace(self, trace: "ExecutionTrace") -> bool:
        """
        Update an ExecutionTrace in the database.

        Args:
            trace: ExecutionTrace model instance with updated fields

        Returns:
            True if successful, False otherwise

        Example:
            >>> trace.mark_completed(success=True)
            >>> await client.update_trace(trace)
        """
        if trace.completed_at is None:
            # Trace is still in progress, just update metadata
            return True

        return await self.complete_execution_trace(
            correlation_id=trace.correlation_id,
            success=trace.success or False,
            error_message=trace.error_message,
            error_type=trace.error_type,
        )

    async def insert_hook(self, hook: "HookExecution") -> Optional[UUID]:
        """
        Insert a HookExecution Pydantic model into the database.

        Args:
            hook: HookExecution model instance

        Returns:
            UUID of the created hook execution record, or None if failed

        Example:
            >>> from hooks.lib.tracing import create_new_hook_execution
            >>> hook = create_new_hook_execution(
            ...     trace_id=trace.correlation_id,
            ...     hook_type="PreToolUse",
            ...     hook_name="quality_check",
            ...     execution_order=1
            ... )
            >>> hook_id = await client.insert_hook(hook)
        """
        return await self.record_hook_execution(
            trace_id=hook.trace_id,
            hook_type=hook.hook_type,
            hook_name=hook.hook_name,
            execution_order=hook.execution_order,
            tool_name=hook.tool_name,
            file_path=hook.file_path,
            duration_ms=hook.duration_ms,
            status=hook.status,
            input_data=hook.input_data,
            output_data=hook.output_data,
            modifications_made=hook.modifications_made,
            rag_query_performed=hook.rag_query_performed,
            rag_results=hook.rag_results,
            quality_check_performed=hook.quality_check_performed,
            quality_results=hook.quality_results,
            error_message=hook.error_message,
            error_type=hook.error_type,
            error_stack=hook.error_stack,
            metadata=hook.metadata,
        )

    async def get_trace_model(self, correlation_id: UUID) -> Optional["ExecutionTrace"]:
        """
        Get an ExecutionTrace as a Pydantic model.

        Args:
            correlation_id: Correlation ID to look up

        Returns:
            ExecutionTrace model instance, or None if not found

        Example:
            >>> trace = await client.get_trace_model(correlation_id)
            >>> if trace:
            ...     print(f"Status: {trace.status}, Duration: {trace.duration_ms}ms")
        """
        from .models import parse_trace_from_row

        row = await self.get_trace_by_correlation_id(correlation_id)
        if row:
            return parse_trace_from_row(row)
        return None

    async def get_hook_models(self, trace_id: UUID) -> List["HookExecution"]:
        """
        Get all hook executions for a trace as Pydantic models.

        Args:
            trace_id: Trace ID to get hooks for

        Returns:
            List of HookExecution model instances

        Example:
            >>> hooks = await client.get_hook_models(trace_id)
            >>> for hook in hooks:
            ...     print(f"{hook.hook_name}: {hook.duration_ms}ms")
        """
        from .models import parse_hook_from_row

        rows = await self.get_hook_executions_for_trace(trace_id)
        return [parse_hook_from_row(row) for row in rows]

    # ===== Required API Methods (Spec-Compliant) =====

    async def health_check(self) -> bool:
        """
        Perform health check on database connection.

        Returns:
            bool: True if database is healthy and responsive, False otherwise

        Example:
            >>> is_healthy = await client.health_check()
            >>> if is_healthy:
            ...     print("Database connection is healthy")
        """
        if not self._initialized or not self.pool:
            logger.warning("Health check failed: Client not initialized")
            return False

        try:
            async with self.pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")

                if result == 1:
                    logger.debug("Health check passed")
                    return True
                else:
                    logger.warning(f"Health check failed: Unexpected result {result}")
                    return False

        except Exception as e:
            logger.error(f"Health check failed with error: {e}", exc_info=True)
            return False

    async def insert_execution_trace(self, data: Dict[str, Any]) -> str:
        """
        Insert new execution trace record (spec-compliant API).

        Args:
            data: Trace data dictionary with required fields:
                - correlation_id (UUID|str): Unique execution identifier
                - root_id (UUID|str): Root trace identifier
                - session_id (UUID|str): Session identifier
                - source (str): Execution source (e.g., "claude_code")
                Optional fields:
                - parent_id (UUID|str): Parent execution ID for nested traces
                - user_id (str): User identifier
                - prompt_text (str): User prompt text
                - status (str): Execution status (default: "in_progress")
                - context (dict): Additional context as JSON
                - tags (list[str]): Tags for categorization

        Returns:
            str: Generated trace UUID as string

        Raises:
            ValueError: If required fields are missing
            RuntimeError: If database operation fails

        Performance:
            Target: <10ms for insert operation

        Example:
            >>> trace_data = {
            ...     "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
            ...     "root_id": "550e8400-e29b-41d4-a716-446655440000",
            ...     "session_id": "abc-123-def-456",
            ...     "source": "claude_code",
            ...     "prompt_text": "Implement authentication"
            ... }
            >>> trace_id = await client.insert_execution_trace(trace_data)
            >>> print(f"Created trace: {trace_id}")
        """
        # Validate required fields
        required_fields = ["correlation_id", "root_id", "session_id", "source"]
        missing_fields = [f for f in required_fields if f not in data]

        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # Convert string UUIDs to UUID objects if necessary
        correlation_id = (
            UUID(data["correlation_id"]) if isinstance(data["correlation_id"], str) else data["correlation_id"]
        )
        root_id = UUID(data["root_id"]) if isinstance(data["root_id"], str) else data["root_id"]
        session_id = UUID(data["session_id"]) if isinstance(data["session_id"], str) else data["session_id"]
        parent_id = (
            UUID(data["parent_id"])
            if data.get("parent_id") and isinstance(data["parent_id"], str)
            else data.get("parent_id")
        )

        # Call underlying method
        trace_id = await self.create_execution_trace(
            correlation_id=correlation_id,
            root_id=root_id,
            parent_id=parent_id,
            session_id=session_id,
            source=data["source"],
            prompt_text=data.get("prompt_text"),
            user_id=data.get("user_id"),
            context=data.get("context"),
            tags=data.get("tags"),
        )

        if trace_id is None:
            raise RuntimeError("Failed to insert execution trace")

        return str(trace_id)

    async def insert_hook_execution(self, data: Dict[str, Any]) -> str:
        """
        Insert new hook execution record (spec-compliant API).

        Args:
            data: Hook execution data with required fields:
                - trace_id (UUID|str): Parent trace ID (foreign key)
                - hook_type (str): Type of hook (e.g., "PreToolUse")
                - hook_name (str): Hook name/identifier
                - execution_order (int): Execution sequence number
                Optional fields:
                - input_data (dict): Hook input as JSON
                - output_data (dict): Hook output as JSON
                - modifications_made (dict): File modifications as JSON
                - rag_query_performed (bool): Whether RAG query was performed
                - rag_results (dict): RAG query results as JSON
                - quality_check_performed (bool): Whether quality check ran
                - quality_results (dict): Quality check results as JSON
                - tool_name (str): Tool being used
                - file_path (str): File being modified
                - metadata (dict): Additional metadata as JSON
                - status (str): Execution status (default: "in_progress")
                - duration_ms (float): Execution duration in milliseconds

        Returns:
            str: Generated hook execution UUID as string

        Raises:
            ValueError: If required fields are missing
            RuntimeError: If database operation fails

        Performance:
            Target: <10ms for insert operation

        Example:
            >>> hook_data = {
            ...     "trace_id": trace_id,
            ...     "hook_type": "PreToolUse",
            ...     "hook_name": "quality_check",
            ...     "execution_order": 1,
            ...     "tool_name": "Edit",
            ...     "file_path": "/path/to/file.py"
            ... }
            >>> hook_id = await client.insert_hook_execution(hook_data)
            >>> print(f"Created hook execution: {hook_id}")
        """
        # Validate required fields
        required_fields = ["trace_id", "hook_type", "hook_name", "execution_order"]
        missing_fields = [f for f in required_fields if f not in data]

        if missing_fields:
            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

        # Convert string UUID to UUID object if necessary
        trace_id = UUID(data["trace_id"]) if isinstance(data["trace_id"], str) else data["trace_id"]

        # Call underlying method
        hook_id = await self.record_hook_execution(
            trace_id=trace_id,
            hook_type=data["hook_type"],
            hook_name=data["hook_name"],
            execution_order=data["execution_order"],
            tool_name=data.get("tool_name"),
            file_path=data.get("file_path"),
            duration_ms=data.get("duration_ms"),
            status=data.get("status", "completed"),
            input_data=data.get("input_data"),
            output_data=data.get("output_data"),
            modifications_made=data.get("modifications_made"),
            rag_query_performed=data.get("rag_query_performed", False),
            rag_results=data.get("rag_results"),
            quality_check_performed=data.get("quality_check_performed", False),
            quality_results=data.get("quality_results"),
            error_message=data.get("error_message"),
            error_type=data.get("error_type"),
            error_stack=data.get("error_stack"),
            metadata=data.get("metadata"),
        )

        if hook_id is None:
            raise RuntimeError("Failed to insert hook execution")

        return str(hook_id)

    async def update_execution_trace(self, correlation_id: str, updates: Dict[str, Any]) -> None:
        """
        Update existing execution trace with completion data (spec-compliant API).

        Args:
            correlation_id: Correlation ID of trace to update (string or UUID)
            updates: Dictionary of fields to update. Common fields:
                - status (str): "completed", "failed", "cancelled"
                - completed_at (datetime): Completion timestamp
                - duration_ms (int): Execution duration in milliseconds
                - success (bool): Whether execution succeeded
                - error_message (str): Error message if failed
                - error_type (str): Error type/category
                - context (dict): Additional context
                - tags (list[str]): Updated tags

        Raises:
            ValueError: If no updates provided or correlation_id invalid
            RuntimeError: If database operation fails

        Example:
            >>> await client.update_execution_trace(
            ...     "550e8400-e29b-41d4-a716-446655440000",
            ...     {
            ...         "status": "completed",
            ...         "success": True,
            ...         "duration_ms": 1250
            ...     }
            ... )
        """
        if not updates:
            raise ValueError("No updates provided")

        # Convert string to UUID if necessary
        corr_id = UUID(correlation_id) if isinstance(correlation_id, str) else correlation_id

        # Special handling for simple completion updates
        if set(updates.keys()) <= {"status", "success", "error_message", "error_type"}:
            # Use complete_execution_trace for simple status updates
            success = await self.complete_execution_trace(
                correlation_id=corr_id,
                success=updates.get("success", True),
                error_message=updates.get("error_message"),
                error_type=updates.get("error_type"),
            )
            if not success:
                raise RuntimeError("Failed to update execution trace")
            return

        # For complex updates, build dynamic UPDATE query
        if not self._initialized and not await self.initialize():
            raise RuntimeError("Client not initialized")

        set_clauses = []
        values = [corr_id]

        for idx, (key, value) in enumerate(updates.items(), start=2):
            set_clauses.append(f"{key} = ${idx}")
            # Handle JSONB fields
            if key == "context" and isinstance(value, dict):
                values.append(json.dumps(value))
            else:
                values.append(value)

        # Always update updated_at timestamp
        set_clauses.append(f"updated_at = ${len(values) + 1}")
        values.append(datetime.utcnow())

        query = f"""
            UPDATE execution_traces
            SET {', '.join(set_clauses)}
            WHERE correlation_id = $1
        """

        try:
            async with self.acquire() as conn:
                if not conn:
                    raise RuntimeError("Failed to acquire database connection")

                result = await conn.execute(query, *values)

                # Check if row was updated
                rows_updated = int(result.split()[-1]) if result else 0

                if rows_updated == 0:
                    logger.warning(
                        "No trace found to update",
                        extra={"correlation_id": str(correlation_id)},
                    )
                else:
                    logger.info(
                        "Execution trace updated",
                        extra={
                            "correlation_id": str(correlation_id),
                            "fields_updated": list(updates.keys()),
                        },
                    )

        except Exception as e:
            logger.error(
                f"Failed to update execution trace: {e}",
                extra={"correlation_id": str(correlation_id)},
                exc_info=True,
            )
            raise RuntimeError(f"Failed to update execution trace: {e}")

    async def get_trace_with_hooks(self, correlation_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve execution trace with all associated hook executions.

        Args:
            correlation_id: Correlation ID to lookup (string or UUID)

        Returns:
            Dict containing trace and hooks, or None if not found:
            {
                "trace": {...},  # Execution trace record
                "hooks": [...]   # List of hook execution records ordered by execution_order
            }

        Raises:
            RuntimeError: If database operation fails

        Example:
            >>> result = await client.get_trace_with_hooks(
            ...     "550e8400-e29b-41d4-a716-446655440000"
            ... )
            >>> if result:
            ...     print(f"Trace status: {result['trace']['status']}")
            ...     print(f"Hook count: {len(result['hooks'])}")
        """
        # Convert string to UUID if necessary
        corr_id = UUID(correlation_id) if isinstance(correlation_id, str) else correlation_id

        # Get trace
        trace = await self.get_trace_by_correlation_id(corr_id)

        if not trace:
            return None

        # Get associated hooks
        hooks = await self.get_hook_executions_for_trace(trace["id"])

        logger.debug(
            "Trace with hooks retrieved",
            extra={
                "correlation_id": str(correlation_id),
                "hook_count": len(hooks),
            },
        )

        return {
            "trace": trace,
            "hooks": hooks,
        }

    def __repr__(self) -> str:
        """String representation of client."""
        status = "initialized" if self._initialized else "not initialized"
        return f"PostgresTracingClient(status={status}, pool_size={self.min_pool_size}-{self.max_pool_size})"

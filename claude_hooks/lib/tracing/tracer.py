"""
High-level Execution Tracer Interface for Intelligence Hook System

Provides a simple, context-aware tracing interface that handles:
- Automatic correlation ID management from environment
- Timing and performance tracking
- Graceful degradation (never breaks hooks on errors)
- Context managers for automatic trace lifecycle management
"""

import os
import time
import logging
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4
from contextlib import asynccontextmanager

from .postgres_client import PostgresTracingClient


logger = logging.getLogger(__name__)


class ExecutionTracer:
    """
    High-level interface for execution tracing in the Intelligence Hook System.

    Features:
    - Context-aware: Automatically reads correlation IDs from environment
    - Auto-timing: Built-in performance measurement
    - Silent failure: Never breaks hook execution on database errors
    - Context managers: Automatic trace start/complete lifecycle

    Example:
        ```python
        tracer = ExecutionTracer(postgres_client)

        # Start trace
        corr_id = await tracer.start_trace(
            source="pre-tool-use",
            prompt_text=user_input,
            session_id=session_id
        )

        # Track hook execution
        await tracer.track_hook_execution(
            correlation_id=corr_id,
            hook_name="quality-enforcer",
            tool_name="Write",
            duration_ms=45.2,
            success=True
        )

        # Complete trace
        await tracer.complete_trace(corr_id, success=True)
        ```

    Using context manager for automatic lifecycle:
        ```python
        async with tracer.trace_execution(
            source="pre-tool-use",
            prompt_text=user_input,
            session_id=session_id
        ) as trace_ctx:
            # Do work...
            await trace_ctx.track_hook(
                hook_name="quality-enforcer",
                tool_name="Write",
                duration_ms=45.2
            )
        # Automatically completes on exit
        ```
    """

    def __init__(
        self,
        postgres_client: Optional[PostgresTracingClient] = None,
        auto_initialize: bool = True
    ):
        """
        Initialize the execution tracer.

        Args:
            postgres_client: PostgreSQL tracing client. If None, creates new one.
            auto_initialize: Whether to auto-initialize database connection
        """
        self.client = postgres_client or PostgresTracingClient()
        self._auto_initialize = auto_initialize
        self._trace_contexts: Dict[UUID, 'TraceContext'] = {}

    async def _ensure_initialized(self) -> bool:
        """Ensure database client is initialized."""
        if self._auto_initialize and not self.client._initialized:
            return await self.client.initialize()
        return self.client._initialized

    def _get_env_correlation_ids(self) -> Dict[str, Optional[UUID]]:
        """
        Get correlation IDs from environment variables.

        Reads from:
        - CORRELATION_ID: Current execution correlation ID
        - ROOT_ID: Root trace ID in nested execution
        - PARENT_ID: Parent execution ID

        Returns:
            Dict with correlation_id, root_id, parent_id (None if not set)
        """
        def parse_uuid(value: Optional[str]) -> Optional[UUID]:
            if not value:
                return None
            try:
                return UUID(value)
            except (ValueError, AttributeError):
                logger.warning(f"Invalid UUID in environment: {value}")
                return None

        return {
            'correlation_id': parse_uuid(os.getenv('CORRELATION_ID')),
            'root_id': parse_uuid(os.getenv('ROOT_ID')),
            'parent_id': parse_uuid(os.getenv('PARENT_ID'))
        }

    async def start_trace(
        self,
        source: str,
        prompt_text: str,
        session_id: str,
        correlation_id: Optional[str] = None,
        root_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> str:
        """
        Start a new execution trace.

        Args:
            source: Source of execution (e.g., "pre-tool-use", "user-prompt-submit")
            prompt_text: User's prompt/input text
            session_id: Claude Code session identifier
            correlation_id: Optional correlation ID (generates if None)
            root_id: Optional root trace ID (uses correlation_id if None)
            parent_id: Optional parent trace ID
            context: Additional context data
            user_id: Optional user identifier
            tags: Optional tags for categorization

        Returns:
            Correlation ID as string (for environment propagation)

        Raises:
            Never raises - logs errors and returns generated/provided correlation_id
        """
        await self._ensure_initialized()

        # Get IDs from environment if not provided
        env_ids = self._get_env_correlation_ids()

        # Parse or generate correlation_id
        if correlation_id:
            try:
                corr_uuid = UUID(correlation_id)
            except ValueError:
                logger.warning(f"Invalid correlation_id: {correlation_id}, generating new one")
                corr_uuid = uuid4()
        elif env_ids['correlation_id']:
            corr_uuid = env_ids['correlation_id']
        else:
            corr_uuid = uuid4()

        # Parse or use root_id (defaults to correlation_id for root traces)
        if root_id:
            try:
                root_uuid = UUID(root_id)
            except ValueError:
                root_uuid = corr_uuid
        elif env_ids['root_id']:
            root_uuid = env_ids['root_id']
        else:
            root_uuid = corr_uuid  # This is a root trace

        # Parse parent_id if provided
        if parent_id:
            try:
                parent_uuid = UUID(parent_id)
            except ValueError:
                parent_uuid = None
        elif env_ids['parent_id']:
            parent_uuid = env_ids['parent_id']
        else:
            parent_uuid = None

        # Parse session_id
        try:
            session_uuid = UUID(session_id)
        except ValueError:
            logger.warning(f"Invalid session_id: {session_id}, generating new one")
            session_uuid = uuid4()

        try:
            # Create execution trace in database
            trace_id = await self.client.create_execution_trace(
                correlation_id=corr_uuid,
                root_id=root_uuid,
                parent_id=parent_uuid,
                session_id=session_uuid,
                source=source,
                prompt_text=prompt_text,
                user_id=user_id,
                context=context,
                tags=tags
            )

            if trace_id:
                # Store trace context for hook tracking
                self._trace_contexts[corr_uuid] = TraceContext(
                    correlation_id=corr_uuid,
                    trace_id=trace_id,
                    started_at=time.time(),
                    execution_order=0
                )
                logger.debug(f"Started trace: {corr_uuid} (trace_id: {trace_id})")
            else:
                logger.warning(f"Failed to create trace in database for {corr_uuid}")

        except Exception as e:
            # Silent failure - never break hook execution
            logger.error(f"Error starting trace: {e}", exc_info=True)

        # Always return correlation_id for environment propagation
        return str(corr_uuid)

    async def track_hook_execution(
        self,
        correlation_id: str,
        hook_name: str,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        hook_type: Optional[str] = None,
        file_path: Optional[str] = None,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        modifications_made: Optional[Dict[str, Any]] = None,
        rag_query_performed: bool = False,
        rag_results: Optional[Dict[str, Any]] = None,
        quality_check_performed: bool = False,
        quality_results: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track a hook execution within a trace.

        Args:
            correlation_id: Correlation ID of the parent trace
            hook_name: Name of the hook (e.g., "quality-enforcer")
            tool_name: Name of the tool being used
            duration_ms: Execution duration in milliseconds
            success: Whether the hook executed successfully
            hook_type: Type of hook (e.g., "PreToolUse", "PostToolUse")
            file_path: File path if applicable
            input_data: Input data to the hook
            output_data: Output data from the hook
            modifications_made: Any modifications made by the hook
            rag_query_performed: Whether RAG query was performed
            rag_results: Results from RAG query
            quality_check_performed: Whether quality check was performed
            quality_results: Results from quality check
            error: Exception if hook failed
            metadata: Additional metadata

        Raises:
            Never raises - logs errors silently
        """
        await self._ensure_initialized()

        try:
            corr_uuid = UUID(correlation_id)
        except ValueError:
            logger.warning(f"Invalid correlation_id for hook tracking: {correlation_id}")
            return

        # Get trace context
        trace_ctx = self._trace_contexts.get(corr_uuid)
        if not trace_ctx:
            logger.warning(f"No trace context found for {correlation_id}, attempting lookup")
            # Try to get trace from database
            trace_data = await self.client.get_trace_by_correlation_id(corr_uuid)
            if trace_data:
                trace_ctx = TraceContext(
                    correlation_id=corr_uuid,
                    trace_id=trace_data['id'],
                    started_at=time.time(),
                    execution_order=0
                )
                self._trace_contexts[corr_uuid] = trace_ctx
            else:
                logger.error(f"Cannot track hook: no trace found for {correlation_id}")
                return

        # Increment execution order
        trace_ctx.execution_order += 1

        # Prepare error details
        error_message = None
        error_type = None
        error_stack = None
        if error:
            error_message = str(error)
            error_type = type(error).__name__
            import traceback
            error_stack = traceback.format_exc()

        # Determine hook type if not provided
        if not hook_type:
            hook_type = self._infer_hook_type(hook_name)

        try:
            # Record hook execution
            await self.client.record_hook_execution(
                trace_id=trace_ctx.trace_id,
                hook_type=hook_type,
                hook_name=hook_name,
                execution_order=trace_ctx.execution_order,
                tool_name=tool_name,
                file_path=file_path,
                duration_ms=duration_ms,
                status="completed" if success else "failed",
                input_data=input_data,
                output_data=output_data,
                modifications_made=modifications_made,
                rag_query_performed=rag_query_performed,
                rag_results=rag_results,
                quality_check_performed=quality_check_performed,
                quality_results=quality_results,
                error_message=error_message,
                error_type=error_type,
                error_stack=error_stack,
                metadata=metadata
            )
            logger.debug(f"Tracked hook: {hook_name} for {correlation_id}")

        except Exception as e:
            # Silent failure
            logger.error(f"Error tracking hook execution: {e}", exc_info=True)

    async def complete_trace(
        self,
        correlation_id: str,
        success: bool,
        error: Optional[Exception] = None
    ) -> None:
        """
        Mark a trace as completed.

        Args:
            correlation_id: Correlation ID of the trace to complete
            success: Whether the execution succeeded overall
            error: Exception if execution failed

        Raises:
            Never raises - logs errors silently
        """
        await self._ensure_initialized()

        try:
            corr_uuid = UUID(correlation_id)
        except ValueError:
            logger.warning(f"Invalid correlation_id for completion: {correlation_id}")
            return

        # Prepare error details
        error_message = None
        error_type = None
        if error:
            error_message = str(error)
            error_type = type(error).__name__

        try:
            # Complete trace in database
            await self.client.complete_execution_trace(
                correlation_id=corr_uuid,
                success=success,
                error_message=error_message,
                error_type=error_type
            )

            # Clean up trace context
            if corr_uuid in self._trace_contexts:
                del self._trace_contexts[corr_uuid]

            logger.debug(f"Completed trace: {correlation_id} (success: {success})")

        except Exception as e:
            # Silent failure
            logger.error(f"Error completing trace: {e}", exc_info=True)

    def _infer_hook_type(self, hook_name: str) -> str:
        """
        Infer hook type from hook name.

        Args:
            hook_name: Name of the hook

        Returns:
            Inferred hook type
        """
        hook_name_lower = hook_name.lower()

        if 'pre-tool-use' in hook_name_lower or 'pretooluse' in hook_name_lower:
            return "PreToolUse"
        elif 'post-tool-use' in hook_name_lower or 'posttooluse' in hook_name_lower:
            return "PostToolUse"
        elif 'user-prompt' in hook_name_lower or 'userprompt' in hook_name_lower:
            return "UserPromptSubmit"
        elif 'session-start' in hook_name_lower:
            return "SessionStart"
        elif 'session-end' in hook_name_lower:
            return "SessionEnd"
        elif 'stop' in hook_name_lower:
            return "Stop"
        else:
            return "Unknown"

    @asynccontextmanager
    async def trace_execution(
        self,
        source: str,
        prompt_text: str,
        session_id: str,
        correlation_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
        tags: Optional[List[str]] = None
    ):
        """
        Context manager for automatic trace lifecycle management.

        Args:
            source: Source of execution
            prompt_text: User's prompt text
            session_id: Session identifier
            correlation_id: Optional correlation ID
            context: Additional context
            user_id: Optional user ID
            tags: Optional tags

        Yields:
            TraceContext object with helper methods

        Example:
            ```python
            async with tracer.trace_execution(
                source="pre-tool-use",
                prompt_text="Write a file",
                session_id=session_id
            ) as trace_ctx:
                # Do work...
                await trace_ctx.track_hook(
                    hook_name="quality-enforcer",
                    tool_name="Write",
                    duration_ms=45.2
                )
            # Automatically completes on exit
            ```
        """
        # Start trace
        corr_id = await self.start_trace(
            source=source,
            prompt_text=prompt_text,
            session_id=session_id,
            correlation_id=correlation_id,
            context=context,
            user_id=user_id,
            tags=tags
        )

        success = True
        error = None

        try:
            # Get trace context
            corr_uuid = UUID(corr_id)
            trace_ctx = self._trace_contexts.get(corr_uuid)

            # Enhance context with tracer reference
            if trace_ctx:
                trace_ctx.tracer = self
                trace_ctx.correlation_id_str = corr_id

            yield trace_ctx

        except Exception as e:
            success = False
            error = e
            raise

        finally:
            # Complete trace
            await self.complete_trace(corr_id, success=success, error=error)

    async def close(self):
        """Close the database client."""
        await self.client.close()


class TraceContext:
    """
    Context object for a trace execution.

    Provides helper methods for tracking hooks within a trace.
    """

    def __init__(
        self,
        correlation_id: UUID,
        trace_id: UUID,
        started_at: float,
        execution_order: int
    ):
        """
        Initialize trace context.

        Args:
            correlation_id: Correlation ID
            trace_id: Database trace ID
            started_at: Start timestamp
            execution_order: Current execution order
        """
        self.correlation_id = correlation_id
        self.correlation_id_str: Optional[str] = None
        self.trace_id = trace_id
        self.started_at = started_at
        self.execution_order = execution_order
        self.tracer: Optional[ExecutionTracer] = None

    async def track_hook(
        self,
        hook_name: str,
        tool_name: str,
        duration_ms: float,
        success: bool = True,
        **kwargs
    ) -> None:
        """
        Convenience method to track a hook execution.

        Args:
            hook_name: Name of the hook
            tool_name: Tool name
            duration_ms: Duration in milliseconds
            success: Whether successful
            **kwargs: Additional arguments passed to track_hook_execution
        """
        if not self.tracer or not self.correlation_id_str:
            logger.warning("TraceContext not properly initialized with tracer")
            return

        await self.tracer.track_hook_execution(
            correlation_id=self.correlation_id_str,
            hook_name=hook_name,
            tool_name=tool_name,
            duration_ms=duration_ms,
            success=success,
            **kwargs
        )

    def get_elapsed_ms(self) -> float:
        """Get elapsed time since trace start in milliseconds."""
        return (time.time() - self.started_at) * 1000

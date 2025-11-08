"""
Agent Execution Logging Mixin

Provides automatic execution logging for polymorphic agents to track
all agent executions in the agent_execution_logs database table.

Usage:
    class MyAgent(AgentExecutionMixin):
        def __init__(self):
            super().__init__(agent_name="my-agent")
            # ... rest of init

        async def execute(self, task: AgentTask) -> AgentResult:
            # Execution logging is automatically handled
            return await self.execute_with_logging(
                task=task,
                execute_fn=self._execute_impl
            )

        async def _execute_impl(self, task: AgentTask) -> AgentResult:
            # Actual implementation here
            pass
"""

import asyncio
import os
import time
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from omnibase_core.enums.enum_operation_status import EnumOperationStatus

from .agent_execution_logger import AgentExecutionLogger, log_agent_execution


class AgentExecutionMixin:
    """
    Mixin to provide automatic execution logging for polymorphic agents.

    Tracks:
    - Execution start/complete in agent_execution_logs table
    - Progress updates during long-running operations
    - Quality scores and error details
    - Correlation ID linking to routing decisions
    """

    def __init__(
        self,
        agent_name: str,
        project_path: Optional[str] = None,
        project_name: Optional[str] = None,
    ):
        """
        Initialize execution logging mixin.

        Args:
            agent_name: Name of the agent (e.g., "debug-intelligence", "polymorphic-agent")
            project_path: Path to the project being worked on
            project_name: Name of the project
        """
        self._agent_name = agent_name
        self._project_path = project_path or os.getcwd()
        self._project_name = project_name or os.path.basename(self._project_path)
        self._execution_logger: Optional[AgentExecutionLogger] = None

    async def execute_with_logging(
        self,
        task: Any,
        execute_fn: Callable,
        correlation_id: Optional[UUID | str] = None,
        session_id: Optional[UUID | str] = None,
        user_prompt: Optional[str] = None,
    ) -> Any:
        """
        Execute agent with automatic execution logging.

        Args:
            task: Task to execute (AgentTask or similar)
            execute_fn: Function to execute (should return AgentResult or similar)
            correlation_id: Correlation ID for tracing (extracted from task if not provided)
            session_id: Session ID (extracted from task if not provided)
            user_prompt: User prompt (extracted from task if not provided)

        Returns:
            Result from execute_fn
        """
        # Extract IDs from task if available
        if not correlation_id and hasattr(task, "correlation_id"):
            correlation_id = task.correlation_id
        if not session_id and hasattr(task, "session_id"):
            session_id = task.session_id
        if not user_prompt and hasattr(task, "description"):
            user_prompt = task.description

        # Create execution logger
        self._execution_logger = await log_agent_execution(
            agent_name=self._agent_name,
            user_prompt=user_prompt,
            correlation_id=correlation_id,
            session_id=session_id,
            project_path=self._project_path,
            project_name=self._project_name,
        )

        start_time = time.time()

        try:
            # Execute the actual agent logic
            result = await execute_fn(task)

            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Determine success status
            success = getattr(result, "success", True)

            # Extract quality score if available
            quality_score = None
            if hasattr(result, "output_data") and isinstance(result.output_data, dict):
                # Try common quality score locations
                quality_score = (
                    result.output_data.get("quality_score")
                    or result.output_data.get("root_cause_confidence")
                    or result.output_data.get("confidence")
                )

            # Log completion
            status = (
                EnumOperationStatus.SUCCESS if success else EnumOperationStatus.FAILED
            )
            error_message = getattr(result, "error", None) if not success else None

            await self._execution_logger.complete(
                status=status,
                quality_score=quality_score,
                error_message=error_message,
                metadata={
                    "execution_time_ms": execution_time_ms,
                    "task_id": getattr(task, "task_id", None),
                },
            )

            return result

        except Exception as e:
            # Calculate execution time
            execution_time_ms = (time.time() - start_time) * 1000

            # Log failure
            await self._execution_logger.complete(
                status=EnumOperationStatus.FAILED,
                error_message=str(e),
                error_type=type(e).__name__,
                metadata={
                    "execution_time_ms": execution_time_ms,
                    "task_id": getattr(task, "task_id", None),
                },
            )

            # Re-raise the exception
            raise

    async def log_progress(
        self,
        stage: str,
        percent: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log execution progress.

        Args:
            stage: Current stage name (e.g., "gathering_intelligence", "analyzing")
            percent: Progress percentage 0-100 (optional)
            metadata: Additional progress metadata (optional)

        Example:
            await self.log_progress("gathering_intelligence", 25)
            await self.log_progress("analyzing", 75, {"source": "rag"})
        """
        if self._execution_logger:
            await self._execution_logger.progress(
                stage=stage, percent=percent, metadata=metadata
            )

    @property
    def execution_id(self) -> Optional[str]:
        """Get current execution ID."""
        return self._execution_logger.execution_id if self._execution_logger else None

    @property
    def correlation_id(self) -> Optional[str]:
        """Get current correlation ID."""
        return self._execution_logger.correlation_id if self._execution_logger else None

"""
Debug State Management Integration Example

Demonstrates how to use the debug loop schema for state tracking,
error/success analysis, and workflow debugging.

Usage:
    from debug_state_integration_example import DebugStateManager

    debug_mgr = DebugStateManager(db_layer)

    # Capture state at error
    snapshot_id = await debug_mgr.capture_error_state(
        correlation_id, agent_name, error, agent_state
    )

    # Track workflow step
    step_id = await debug_mgr.start_workflow_step(
        correlation_id, step_num, agent_name, operation
    )
    await debug_mgr.complete_workflow_step(step_id, success=True)

    # Analyze recovery patterns
    patterns = await debug_mgr.get_recovery_patterns()
"""

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class DebugStateManager:
    """
    Manager for debug state tracking and analysis.

    Provides high-level API for:
    - State snapshot capture
    - Error/success event tracking
    - Workflow step management
    - Recovery pattern analysis
    """

    def __init__(self, db_layer):
        """
        Initialize debug state manager.

        Args:
            db_layer: DatabaseIntegrationLayer instance
        """
        self.db = db_layer

    # =========================================================================
    # State Snapshot Management
    # =========================================================================

    async def capture_state_snapshot(
        self,
        snapshot_type: str,
        correlation_id: UUID,
        agent_name: str,
        agent_state: Dict[str, Any],
        task_description: Optional[str] = None,
        session_id: Optional[UUID] = None,
        execution_step: Optional[int] = None,
    ) -> UUID:
        """
        Capture agent state snapshot.

        Args:
            snapshot_type: Type of snapshot (error, success, checkpoint, etc.)
            correlation_id: Workflow correlation ID
            agent_name: Name of agent
            agent_state: Full agent state dictionary
            task_description: What agent was trying to do
            session_id: Optional session ID
            execution_step: Optional step number

        Returns:
            UUID of created snapshot
        """
        query = """
            SELECT capture_state_snapshot($1, $2, $3, $4::JSONB, $5, $6, $7)
        """

        snapshot_id = await self.db.execute_query(
            query,
            snapshot_type,
            correlation_id,
            agent_name,
            json.dumps(agent_state),
            task_description,
            session_id,
            execution_step,
            fetch="val",
        )

        logger.debug(
            f"Captured {snapshot_type} snapshot {snapshot_id} "
            f"for {agent_name} (correlation: {correlation_id})"
        )

        return snapshot_id

    async def get_state_snapshot(self, snapshot_id: UUID) -> Optional[Dict[str, Any]]:
        """Get state snapshot by ID."""
        query = """
            SELECT * FROM debug_state_snapshots WHERE id = $1
        """

        row = await self.db.execute_query(query, snapshot_id, fetch="one")
        return dict(row) if row else None

    async def get_workflow_snapshots(
        self, correlation_id: UUID, snapshot_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get all snapshots for a workflow."""
        if snapshot_type:
            query = """
                SELECT * FROM debug_state_snapshots
                WHERE correlation_id = $1 AND snapshot_type = $2
                ORDER BY captured_at
            """
            rows = await self.db.execute_query(
                query, correlation_id, snapshot_type, fetch="all"
            )
        else:
            query = """
                SELECT * FROM debug_state_snapshots
                WHERE correlation_id = $1
                ORDER BY captured_at
            """
            rows = await self.db.execute_query(query, correlation_id, fetch="all")

        return [dict(row) for row in rows]

    # =========================================================================
    # Error Event Management
    # =========================================================================

    async def capture_error_state(
        self,
        correlation_id: UUID,
        agent_name: str,
        error: Exception,
        agent_state: Dict[str, Any],
        error_category: str = "agent",
        error_severity: str = "high",
        operation_name: Optional[str] = None,
        execution_step: Optional[int] = None,
        session_id: Optional[UUID] = None,
        task_description: Optional[str] = None,
        is_recoverable: bool = False,
    ) -> UUID:
        """
        Capture error with state snapshot.

        Args:
            correlation_id: Workflow correlation ID
            agent_name: Name of agent where error occurred
            error: Exception that occurred
            agent_state: Agent state at time of error
            error_category: Category of error (agent, framework, external, user)
            error_severity: Severity (low, medium, high, critical)
            operation_name: Operation that failed
            execution_step: Step number where error occurred
            session_id: Optional session ID
            task_description: What agent was trying to do
            is_recoverable: Whether error is recoverable

        Returns:
            UUID of created error event
        """
        # First, capture state snapshot
        snapshot_id = await self.capture_state_snapshot(
            snapshot_type="error",
            correlation_id=correlation_id,
            agent_name=agent_name,
            agent_state=agent_state,
            task_description=task_description,
            session_id=session_id,
            execution_step=execution_step,
        )

        # Then, create error event
        query = """
            INSERT INTO debug_error_events (
                correlation_id, session_id, error_type, error_category,
                error_severity, error_message, error_stack_trace,
                agent_name, operation_name, execution_step,
                state_snapshot_id, is_recoverable
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12
            )
            RETURNING id
        """

        import traceback

        error_id = await self.db.execute_query(
            query,
            correlation_id,
            session_id,
            type(error).__name__,
            error_category,
            error_severity,
            str(error),
            traceback.format_exc(),
            agent_name,
            operation_name,
            execution_step,
            snapshot_id,
            is_recoverable,
            fetch="val",
        )

        logger.error(
            f"Captured error {error_id} for {agent_name}: {str(error)} "
            f"(correlation: {correlation_id}, snapshot: {snapshot_id})"
        )

        return error_id

    async def mark_error_recovered(
        self, error_id: UUID, recovery_strategy: str, recovery_successful: bool = True
    ):
        """Mark error as recovered."""
        query = """
            UPDATE debug_error_events
            SET recovery_attempted = TRUE,
                recovery_successful = $2,
                recovery_strategy = $3,
                resolved_at = NOW()
            WHERE id = $1
        """

        await self.db.execute_query(
            query, error_id, recovery_successful, recovery_strategy
        )

        logger.info(
            f"Marked error {error_id} as recovered "
            f"(strategy: {recovery_strategy}, success: {recovery_successful})"
        )

    # =========================================================================
    # Success Event Management
    # =========================================================================

    async def capture_success_state(
        self,
        correlation_id: UUID,
        agent_name: str,
        operation_name: str,
        agent_state: Dict[str, Any],
        success_type: str = "task_completion",
        quality_score: Optional[float] = None,
        execution_time_ms: Optional[int] = None,
        session_id: Optional[UUID] = None,
        execution_step: Optional[int] = None,
        task_description: Optional[str] = None,
        success_factors: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """
        Capture success with state snapshot.

        Args:
            correlation_id: Workflow correlation ID
            agent_name: Name of agent
            operation_name: Operation that succeeded
            agent_state: Agent state at success
            success_type: Type of success (task_completion, validation_pass, etc.)
            quality_score: Quality score (0-1)
            execution_time_ms: Execution time in milliseconds
            session_id: Optional session ID
            execution_step: Step number
            task_description: What was accomplished
            success_factors: What contributed to success

        Returns:
            UUID of created success event
        """
        # Capture state snapshot
        snapshot_id = await self.capture_state_snapshot(
            snapshot_type="success",
            correlation_id=correlation_id,
            agent_name=agent_name,
            agent_state=agent_state,
            task_description=task_description,
            session_id=session_id,
            execution_step=execution_step,
        )

        # Create success event
        query = """
            INSERT INTO debug_success_events (
                correlation_id, session_id, success_type, operation_name,
                agent_name, execution_step, state_snapshot_id,
                quality_score, execution_time_ms, success_factors
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10::JSONB
            )
            RETURNING id
        """

        success_id = await self.db.execute_query(
            query,
            correlation_id,
            session_id,
            success_type,
            operation_name,
            agent_name,
            execution_step,
            snapshot_id,
            quality_score,
            execution_time_ms,
            json.dumps(success_factors or {}),
            fetch="val",
        )

        logger.info(
            f"Captured success {success_id} for {agent_name}: {operation_name} "
            f"(correlation: {correlation_id}, quality: {quality_score})"
        )

        return success_id

    # =========================================================================
    # Workflow Step Management
    # =========================================================================

    async def start_workflow_step(
        self,
        correlation_id: UUID,
        step_number: int,
        agent_name: str,
        operation_name: str,
        step_type: str = "execution",
        step_description: Optional[str] = None,
        session_id: Optional[UUID] = None,
        parent_step_id: Optional[UUID] = None,
        input_data: Optional[Dict[str, Any]] = None,
    ) -> UUID:
        """
        Start tracking a workflow step.

        Args:
            correlation_id: Workflow correlation ID
            step_number: Step number in workflow
            agent_name: Agent executing this step
            operation_name: Operation being performed
            step_type: Type of step (initialization, routing, execution, etc.)
            step_description: Description of step
            session_id: Optional session ID
            parent_step_id: Parent step if nested
            input_data: Input data for this step

        Returns:
            UUID of created workflow step
        """
        query = """
            INSERT INTO debug_workflow_steps (
                correlation_id, session_id, step_number, step_type,
                agent_name, operation_name, step_description,
                parent_step_id, status, started_at, input_data
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, 'started', NOW(), $9::JSONB
            )
            RETURNING id
        """

        step_id = await self.db.execute_query(
            query,
            correlation_id,
            session_id,
            step_number,
            step_type,
            agent_name,
            operation_name,
            step_description,
            parent_step_id,
            json.dumps(input_data or {}),
            fetch="val",
        )

        logger.debug(
            f"Started workflow step {step_id} (step {step_number}): "
            f"{agent_name}.{operation_name}"
        )

        return step_id

    async def complete_workflow_step(
        self,
        step_id: UUID,
        success: bool = True,
        error_event_id: Optional[UUID] = None,
        success_event_id: Optional[UUID] = None,
        output_data: Optional[Dict[str, Any]] = None,
    ):
        """
        Mark workflow step as completed.

        Args:
            step_id: Step ID to complete
            success: Whether step succeeded
            error_event_id: Optional error event if failed
            success_event_id: Optional success event if succeeded
            output_data: Output data from this step
        """
        status = "completed" if success else "failed"

        query = """
            UPDATE debug_workflow_steps
            SET status = $2,
                completed_at = NOW(),
                duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
                error_event_id = $3,
                success_event_id = $4,
                output_data = $5::JSONB
            WHERE id = $1
        """

        await self.db.execute_query(
            query,
            step_id,
            status,
            error_event_id,
            success_event_id,
            json.dumps(output_data or {}),
        )

        logger.debug(f"Completed workflow step {step_id} with status: {status}")

    # =========================================================================
    # Error-Success Correlation
    # =========================================================================

    async def correlate_error_to_success(
        self,
        error_event_id: UUID,
        success_event_id: UUID,
        correlation_id: UUID,
        recovery_strategy: str,
        recovery_path: Optional[str] = None,
        confidence_score: float = 1.0,
    ) -> UUID:
        """
        Link an error to eventual success for recovery pattern learning.

        Args:
            error_event_id: Error event ID
            success_event_id: Success event ID
            correlation_id: Workflow correlation ID
            recovery_strategy: Strategy that led to recovery
            recovery_path: Description of recovery steps
            confidence_score: Confidence in correlation (0-1)

        Returns:
            UUID of correlation record
        """
        query = """
            INSERT INTO debug_error_success_correlation (
                error_event_id, success_event_id, correlation_id,
                recovery_strategy, recovery_path, confidence_score
            ) VALUES (
                $1, $2, $3, $4, $5, $6
            )
            RETURNING id
        """

        corr_id = await self.db.execute_query(
            query,
            error_event_id,
            success_event_id,
            correlation_id,
            recovery_strategy,
            recovery_path,
            confidence_score,
            fetch="val",
        )

        logger.info(
            f"Correlated error {error_event_id} to success {success_event_id} "
            f"via {recovery_strategy}"
        )

        return corr_id

    # =========================================================================
    # Analysis and Reporting
    # =========================================================================

    async def get_workflow_debug_summary(
        self, correlation_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """Get comprehensive debug summary for a workflow."""
        query = """
            SELECT * FROM get_workflow_debug_summary($1)
        """

        row = await self.db.execute_query(query, correlation_id, fetch="one")
        return dict(row) if row else None

    async def get_recovery_patterns(
        self, error_type: Optional[str] = None, min_confidence: float = 0.5
    ) -> List[Dict[str, Any]]:
        """
        Get error recovery patterns for learning.

        Args:
            error_type: Optional filter by error type
            min_confidence: Minimum confidence score

        Returns:
            List of recovery patterns with statistics
        """
        if error_type:
            query = """
                SELECT * FROM debug_error_recovery_patterns
                WHERE error_type = $1
                AND avg_confidence >= $2
            """
            rows = await self.db.execute_query(
                query, error_type, min_confidence, fetch="all"
            )
        else:
            query = """
                SELECT * FROM debug_error_recovery_patterns
                WHERE avg_confidence >= $1
            """
            rows = await self.db.execute_query(query, min_confidence, fetch="all")

        return [dict(row) for row in rows]

    async def get_workflow_errors(
        self, correlation_id: UUID, include_recovered: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all errors for a workflow."""
        if include_recovered:
            query = """
                SELECT * FROM debug_error_events
                WHERE correlation_id = $1
                ORDER BY occurred_at
            """
        else:
            query = """
                SELECT * FROM debug_error_events
                WHERE correlation_id = $1
                AND (recovery_successful = FALSE OR recovery_attempted = FALSE)
                ORDER BY occurred_at
            """

        rows = await self.db.execute_query(query, correlation_id, fetch="all")
        return [dict(row) for row in rows]

    async def get_llm_calls(self, correlation_id: UUID) -> List[Dict[str, Any]]:
        """Get LLM calls for a workflow from hook_events."""
        query = """
            SELECT * FROM debug_llm_call_summary
            WHERE correlation_id = $1
            ORDER BY call_timestamp
        """

        rows = await self.db.execute_query(query, str(correlation_id), fetch="all")
        return [dict(row) for row in rows]


# =============================================================================
# Example Usage
# =============================================================================


async def example_usage():
    """Example of using DebugStateManager."""
    from database_integration import DatabaseConfig, DatabaseIntegrationLayer

    # Initialize database layer
    config = DatabaseConfig.from_env()
    db = DatabaseIntegrationLayer(config)
    await db.initialize()

    # Create debug manager
    debug_mgr = DebugStateManager(db)

    # Generate IDs for example
    correlation_id = uuid4()
    session_id = uuid4()

    try:
        # Example: Start workflow step
        step_id = await debug_mgr.start_workflow_step(
            correlation_id=correlation_id,
            step_number=1,
            agent_name="agent-workflow-coordinator",
            operation_name="initialize_workflow",
            step_type="initialization",
            session_id=session_id,
        )

        # Simulate some work that might fail
        try:
            # ... do work ...
            raise ValueError("Simulated error")
        except Exception as e:
            # Capture error with state
            agent_state = {"context": "example", "step": 1}
            error_id = await debug_mgr.capture_error_state(
                correlation_id=correlation_id,
                agent_name="agent-workflow-coordinator",
                error=e,
                agent_state=agent_state,
                error_category="agent",
                error_severity="medium",
                operation_name="initialize_workflow",
                execution_step=1,
                session_id=session_id,
                is_recoverable=True,
            )

            # Mark step as failed
            await debug_mgr.complete_workflow_step(
                step_id=step_id, success=False, error_event_id=error_id
            )

            # Attempt recovery
            await debug_mgr.mark_error_recovered(
                error_id=error_id,
                recovery_strategy="retry_with_fallback",
                recovery_successful=True,
            )

            # Capture success after recovery
            success_id = await debug_mgr.capture_success_state(
                correlation_id=correlation_id,
                agent_name="agent-workflow-coordinator",
                operation_name="initialize_workflow",
                agent_state=agent_state,
                success_type="recovery_success",
                quality_score=0.85,
                execution_time_ms=1500,
                session_id=session_id,
                execution_step=1,
            )

            # Link error to success
            await debug_mgr.correlate_error_to_success(
                error_event_id=error_id,
                success_event_id=success_id,
                correlation_id=correlation_id,
                recovery_strategy="retry_with_fallback",
                confidence_score=0.9,
            )

        # Get debug summary
        summary = await debug_mgr.get_workflow_debug_summary(correlation_id)
        print(f"Workflow summary: {summary}")

        # Get recovery patterns
        patterns = await debug_mgr.get_recovery_patterns()
        print(f"Recovery patterns: {patterns}")

    finally:
        # Cleanup
        await db.shutdown()


if __name__ == "__main__":
    import asyncio

    asyncio.run(example_usage())

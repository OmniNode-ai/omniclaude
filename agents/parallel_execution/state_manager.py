"""
State Manager for Debug Loop System - ONEX Architecture

Provides state snapshot capture, error/success tracking, and similarity-based recall
for the debug loop intelligence system.

Features:
- State snapshot capture at critical points
- Error→success transformation tracking
- Code pointer storage for STFs (State Transformation Functions)
- Similarity-based state recall
- Verbose/silent mode for token optimization
- ONEX-compliant node implementations (Effect/Compute patterns)

ONEX Compliance:
- Effect Nodes: Database I/O operations
- Compute Nodes: Pure transformations (diffing, similarity matching)
- Pydantic Models: Strong typing for all contracts
- Naming: Node<Name><Type> pattern

Integration:
- Database: Uses DEBUG_LOOP_SCHEMA.md tables
- Agents: Integrates with agent-debug-intelligence workflow
- Context: Maintains correlation_id throughout lifecycle
"""

import asyncio
import hashlib
import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from database_integration import DatabaseIntegrationLayer, get_database_layer

logger = logging.getLogger(__name__)


# =============================================================================
# ENUMS AND CONSTANTS
# =============================================================================

class VerboseMode(str, Enum):
    """Verbose mode for state manager operations."""
    VERBOSE = "VERBOSE"  # Full logging and details
    SILENT = "SILENT"    # Minimal logging, optimized for tokens


class SnapshotType(str, Enum):
    """Types of state snapshots."""
    ERROR = "error"
    SUCCESS = "success"
    CHECKPOINT = "checkpoint"
    PRE_TRANSFORM = "pre_transform"
    POST_TRANSFORM = "post_transform"


class ErrorCategory(str, Enum):
    """Error categories for classification."""
    AGENT = "agent"
    FRAMEWORK = "framework"
    EXTERNAL = "external"
    USER = "user"


class ErrorSeverity(str, Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# =============================================================================
# PYDANTIC MODELS (CONTRACTS)
# =============================================================================

class ModelCodePointer(BaseModel):
    """Code pointer for STF (State Transformation Function) location."""
    file_path: str = Field(..., description="Absolute path to source file")
    function_name: str = Field(..., description="Function name")
    line_number: Optional[int] = Field(None, description="Starting line number")
    class_name: Optional[str] = Field(None, description="Class name if method")
    module_path: str = Field(..., description="Python module path")


class ModelStateSnapshot(BaseModel):
    """State snapshot contract for agent state capture."""
    snapshot_id: UUID = Field(default_factory=uuid4)
    snapshot_type: SnapshotType
    correlation_id: UUID
    session_id: Optional[UUID] = None
    agent_name: str
    agent_state: Dict[str, Any]
    state_hash: str = Field(..., description="SHA-256 hash for deduplication")
    execution_step: Optional[int] = None
    task_description: Optional[str] = None
    user_request: Optional[str] = None
    state_size_bytes: Optional[int] = None
    variables_count: Optional[int] = None
    context_depth: Optional[int] = None
    memory_usage_mb: Optional[float] = None
    cpu_time_ms: Optional[int] = None
    wall_time_ms: Optional[int] = None
    parent_snapshot_id: Optional[UUID] = None
    captured_at: datetime = Field(default_factory=datetime.now)


class ModelErrorEvent(BaseModel):
    """Error event contract for error tracking."""
    error_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID
    session_id: Optional[UUID] = None
    error_type: str
    error_category: ErrorCategory
    error_severity: ErrorSeverity
    error_message: str
    error_stack_trace: Optional[str] = None
    error_code: Optional[str] = None
    agent_name: str
    operation_name: Optional[str] = None
    execution_step: Optional[int] = None
    state_snapshot_id: Optional[UUID] = None
    is_recoverable: bool = False
    recovery_attempted: bool = False
    recovery_successful: Optional[bool] = None
    recovery_strategy: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.now)
    resolved_at: Optional[datetime] = None


class ModelSuccessEvent(BaseModel):
    """Success event contract for successful operation tracking."""
    success_id: UUID = Field(default_factory=uuid4)
    correlation_id: UUID
    session_id: Optional[UUID] = None
    success_type: str
    operation_name: str
    agent_name: str
    execution_step: Optional[int] = None
    state_snapshot_id: Optional[UUID] = None
    quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    completion_status: str = "full"  # full, partial, degraded
    validation_passed: bool = True
    execution_time_ms: Optional[int] = None
    retry_count: int = 0
    success_factors: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=datetime.now)


class ModelErrorSuccessLink(BaseModel):
    """Link between error and eventual success for pattern learning."""
    link_id: UUID = Field(default_factory=uuid4)
    error_event_id: UUID
    success_event_id: UUID
    correlation_id: UUID
    recovery_path: Optional[str] = None
    recovery_duration_ms: Optional[int] = None
    intermediate_steps: Optional[int] = None
    recovery_strategy: Optional[str] = None
    stf_name: Optional[str] = None  # State Transformation Function name
    stf_pointer: Optional[ModelCodePointer] = None
    confidence_score: float = Field(1.0, ge=0.0, le=1.0)
    correlated_at: datetime = Field(default_factory=datetime.now)


# =============================================================================
# ONEX NODE IMPLEMENTATIONS
# =============================================================================

class NodeStateSnapshotEffect:
    """
    ONEX Effect Node: Database persistence for state snapshots.

    Handles all database I/O operations for state snapshot storage.
    """

    def __init__(self, db_layer: Optional[DatabaseIntegrationLayer] = None):
        """Initialize snapshot effect node with database layer."""
        self.db = db_layer or get_database_layer()

    async def persist_snapshot(self, snapshot: ModelStateSnapshot) -> UUID:
        """
        Persist state snapshot to database.

        Args:
            snapshot: State snapshot to persist

        Returns:
            UUID of persisted snapshot
        """
        query = """
            INSERT INTO agent_observability.debug_state_snapshots (
                id, snapshot_type, correlation_id, session_id, agent_name,
                agent_state, state_hash, execution_step, task_description,
                user_request, state_size_bytes, variables_count, context_depth,
                memory_usage_mb, cpu_time_ms, wall_time_ms, parent_snapshot_id,
                captured_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18
            )
            ON CONFLICT (state_hash) DO NOTHING
            RETURNING id
        """

        params = [
            snapshot.snapshot_id,
            snapshot.snapshot_type.value,
            snapshot.correlation_id,
            snapshot.session_id,
            snapshot.agent_name,
            json.dumps(snapshot.agent_state),
            snapshot.state_hash,
            snapshot.execution_step,
            snapshot.task_description,
            snapshot.user_request,
            snapshot.state_size_bytes,
            snapshot.variables_count,
            snapshot.context_depth,
            snapshot.memory_usage_mb,
            snapshot.cpu_time_ms,
            snapshot.wall_time_ms,
            snapshot.parent_snapshot_id,
            snapshot.captured_at
        ]

        try:
            result = await self.db.execute_query(query, *params, fetch="val")
            return result if result else snapshot.snapshot_id
        except Exception as e:
            logger.error(f"Failed to persist snapshot: {e}")
            raise

    async def persist_error(self, error: ModelErrorEvent) -> UUID:
        """Persist error event to database."""
        query = """
            INSERT INTO agent_observability.debug_error_events (
                id, correlation_id, session_id, error_type, error_category,
                error_severity, error_message, error_stack_trace, error_code,
                agent_name, operation_name, execution_step, state_snapshot_id,
                is_recoverable, recovery_attempted, recovery_successful,
                recovery_strategy, metadata, occurred_at, resolved_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18, $19, $20
            )
            RETURNING id
        """

        params = [
            error.error_id,
            error.correlation_id,
            error.session_id,
            error.error_type,
            error.error_category.value,
            error.error_severity.value,
            error.error_message,
            error.error_stack_trace,
            error.error_code,
            error.agent_name,
            error.operation_name,
            error.execution_step,
            error.state_snapshot_id,
            error.is_recoverable,
            error.recovery_attempted,
            error.recovery_successful,
            error.recovery_strategy,
            json.dumps(error.metadata),
            error.occurred_at,
            error.resolved_at
        ]

        try:
            result = await self.db.execute_query(query, *params, fetch="val")
            return result if result else error.error_id
        except Exception as e:
            logger.error(f"Failed to persist error: {e}")
            raise

    async def persist_success(self, success: ModelSuccessEvent) -> UUID:
        """Persist success event to database."""
        query = """
            INSERT INTO agent_observability.debug_success_events (
                id, correlation_id, session_id, success_type, operation_name,
                agent_name, execution_step, state_snapshot_id, quality_score,
                completion_status, validation_passed, execution_time_ms,
                retry_count, success_factors, metadata, occurred_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16
            )
            RETURNING id
        """

        params = [
            success.success_id,
            success.correlation_id,
            success.session_id,
            success.success_type,
            success.operation_name,
            success.agent_name,
            success.execution_step,
            success.state_snapshot_id,
            success.quality_score,
            success.completion_status,
            success.validation_passed,
            success.execution_time_ms,
            success.retry_count,
            json.dumps(success.success_factors),
            json.dumps(success.metadata),
            success.occurred_at
        ]

        try:
            result = await self.db.execute_query(query, *params, fetch="val")
            return result if result else success.success_id
        except Exception as e:
            logger.error(f"Failed to persist success: {e}")
            raise

    async def link_error_to_success(self, link: ModelErrorSuccessLink) -> UUID:
        """Create link between error and success events."""
        query = """
            INSERT INTO agent_observability.debug_error_success_correlation (
                id, error_event_id, success_event_id, correlation_id,
                recovery_path, recovery_duration_ms, intermediate_steps,
                recovery_strategy, confidence_score, correlated_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10
            )
            ON CONFLICT (error_event_id, success_event_id) DO NOTHING
            RETURNING id
        """

        params = [
            link.link_id,
            link.error_event_id,
            link.success_event_id,
            link.correlation_id,
            link.recovery_path,
            link.recovery_duration_ms,
            link.intermediate_steps,
            link.recovery_strategy,
            link.confidence_score,
            link.correlated_at
        ]

        try:
            result = await self.db.execute_query(query, *params, fetch="val")
            return result if result else link.link_id
        except Exception as e:
            logger.error(f"Failed to link error to success: {e}")
            raise

    async def query_similar_snapshots(
        self,
        task_signature: str,
        limit: int = 5
    ) -> List[ModelStateSnapshot]:
        """Query snapshots with similar task signatures."""
        query = """
            SELECT
                id as snapshot_id, snapshot_type, correlation_id, session_id,
                agent_name, agent_state, state_hash, execution_step,
                task_description, user_request, state_size_bytes,
                variables_count, context_depth, memory_usage_mb, cpu_time_ms,
                wall_time_ms, parent_snapshot_id, captured_at
            FROM agent_observability.debug_state_snapshots
            WHERE task_description ILIKE $1
               OR user_request ILIKE $1
            ORDER BY captured_at DESC
            LIMIT $2
        """

        try:
            rows = await self.db.execute_query(
                query,
                f"%{task_signature}%",
                limit,
                fetch="all"
            )

            snapshots = []
            for row in rows:
                row_dict = dict(row)
                # Parse JSON fields
                row_dict['agent_state'] = json.loads(row_dict['agent_state'])
                snapshots.append(ModelStateSnapshot(**row_dict))

            return snapshots
        except Exception as e:
            logger.error(f"Failed to query similar snapshots: {e}")
            return []


class NodeStateDiffCompute:
    """
    ONEX Compute Node: Pure state difference computation.

    Compares two state objects and produces diff.
    """

    @staticmethod
    def compute_diff(
        before_state: Dict[str, Any],
        after_state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Compute difference between two states.

        Args:
            before_state: State before transformation
            after_state: State after transformation

        Returns:
            Dictionary with added, removed, modified keys
        """
        diff = {
            "added": {},
            "removed": {},
            "modified": {}
        }

        # Find added and modified keys
        for key, after_value in after_state.items():
            if key not in before_state:
                diff["added"][key] = after_value
            elif before_state[key] != after_value:
                diff["modified"][key] = {
                    "before": before_state[key],
                    "after": after_value
                }

        # Find removed keys
        for key in before_state:
            if key not in after_state:
                diff["removed"][key] = before_state[key]

        return diff


class NodeSimilarityMatchCompute:
    """
    ONEX Compute Node: Similarity matching for task signatures.

    Pure computation for finding similar states based on task characteristics.
    """

    @staticmethod
    def compute_task_signature(task_description: str, context: Dict[str, Any]) -> str:
        """
        Compute normalized task signature for similarity matching.

        Args:
            task_description: Task description text
            context: Additional context dictionary

        Returns:
            Normalized task signature
        """
        # Normalize description
        signature_parts = [task_description.lower().strip()]

        # Add relevant context keys
        relevant_keys = ["agent_name", "operation_name", "domain"]
        for key in relevant_keys:
            if key in context:
                signature_parts.append(str(context[key]).lower())

        return " ".join(signature_parts)

    @staticmethod
    def compute_similarity_score(
        signature1: str,
        signature2: str
    ) -> float:
        """
        Compute similarity score between two task signatures.

        Uses simple token overlap for MVP. Can be enhanced with embeddings later.

        Args:
            signature1: First task signature
            signature2: Second task signature

        Returns:
            Similarity score between 0.0 and 1.0
        """
        tokens1 = set(signature1.lower().split())
        tokens2 = set(signature2.lower().split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1 & tokens2
        union = tokens1 | tokens2

        return len(intersection) / len(union) if union else 0.0


# =============================================================================
# STATE MANAGER ORCHESTRATOR
# =============================================================================

class StateManager:
    """
    State Manager Orchestrator for Debug Loop System.

    Coordinates ONEX nodes to provide state management capabilities:
    - Capture state snapshots at critical points
    - Track error→success transformations
    - Store code pointers to STFs
    - Enable similarity-based state recall
    - Support verbose/silent mode

    Usage:
        manager = StateManager()
        await manager.initialize()

        # Capture snapshot
        snapshot_id = await manager.capture_snapshot(
            agent_state={"context": "...", "variables": {...}},
            correlation_id=uuid4()
        )

        # Record error
        error_id = await manager.record_error(
            exception=ValueError("Test error"),
            snapshot_id=snapshot_id
        )

        # Record success
        success_id = await manager.record_success(snapshot_id)

        # Link error to success
        await manager.link_error_to_success(
            error_id=error_id,
            success_id=success_id,
            stf_name="fix_validation_error"
        )

        # Recall similar states
        similar = await manager.recall_similar_states("validation error")
    """

    def __init__(
        self,
        db_layer: Optional[DatabaseIntegrationLayer] = None,
        verbose_mode: VerboseMode = VerboseMode.VERBOSE
    ):
        """
        Initialize state manager.

        Args:
            db_layer: Database integration layer (uses global if not provided)
            verbose_mode: Verbose or silent mode for logging
        """
        self.db = db_layer or get_database_layer()
        self.verbose_mode = verbose_mode

        # Initialize ONEX nodes
        self.snapshot_effect = NodeStateSnapshotEffect(self.db)
        self.diff_compute = NodeStateDiffCompute()
        self.similarity_compute = NodeSimilarityMatchCompute()

        # State tracking
        self._current_context: Dict[str, Any] = {}
        self._lock = asyncio.Lock()

        logger.info(f"StateManager initialized in {verbose_mode.value} mode")

    async def initialize(self) -> bool:
        """
        Initialize state manager and verify database connectivity.

        Returns:
            True if initialization successful
        """
        try:
            # Verify database connection
            if not self.db.pool:
                logger.warning("Database pool not initialized, attempting initialization...")
                success = await self.db.initialize()
                if not success:
                    logger.error("Failed to initialize database pool")
                    return False

            if self.verbose_mode == VerboseMode.VERBOSE:
                logger.info("StateManager initialized successfully")

            return True
        except Exception as e:
            logger.error(f"StateManager initialization failed: {e}")
            return False

    async def capture_snapshot(
        self,
        agent_state: Dict[str, Any],
        correlation_id: UUID,
        snapshot_type: SnapshotType = SnapshotType.CHECKPOINT,
        agent_name: str = "unknown",
        session_id: Optional[UUID] = None,
        task_description: Optional[str] = None,
        execution_step: Optional[int] = None,
        parent_snapshot_id: Optional[UUID] = None
    ) -> UUID:
        """
        Capture state snapshot at critical point.

        Args:
            agent_state: Current agent state dictionary
            correlation_id: Workflow correlation ID
            snapshot_type: Type of snapshot
            agent_name: Name of agent
            session_id: Session ID if available
            task_description: Description of current task
            execution_step: Step number in workflow
            parent_snapshot_id: Previous snapshot ID

        Returns:
            UUID of captured snapshot
        """
        # Calculate state hash for deduplication
        state_json = json.dumps(agent_state, sort_keys=True)
        state_hash = hashlib.sha256(state_json.encode()).hexdigest()

        # Create snapshot model
        snapshot = ModelStateSnapshot(
            snapshot_type=snapshot_type,
            correlation_id=correlation_id,
            session_id=session_id,
            agent_name=agent_name,
            agent_state=agent_state,
            state_hash=state_hash,
            execution_step=execution_step,
            task_description=task_description,
            state_size_bytes=len(state_json),
            variables_count=len(agent_state),
            parent_snapshot_id=parent_snapshot_id
        )

        # Persist snapshot
        snapshot_id = await self.snapshot_effect.persist_snapshot(snapshot)

        if self.verbose_mode == VerboseMode.VERBOSE:
            logger.info(
                f"Captured {snapshot_type.value} snapshot: {snapshot_id} "
                f"(size: {snapshot.state_size_bytes} bytes, "
                f"vars: {snapshot.variables_count})"
            )

        return snapshot_id

    async def record_error(
        self,
        exception: Exception,
        snapshot_id: Optional[UUID] = None,
        correlation_id: Optional[UUID] = None,
        agent_name: str = "unknown",
        error_category: ErrorCategory = ErrorCategory.AGENT,
        error_severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        is_recoverable: bool = True,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Record error event with context.

        Args:
            exception: Exception that occurred
            snapshot_id: Associated state snapshot ID
            correlation_id: Workflow correlation ID
            agent_name: Name of agent where error occurred
            error_category: Error category
            error_severity: Error severity
            is_recoverable: Whether error is recoverable
            metadata: Additional error metadata

        Returns:
            UUID of error event
        """
        import traceback

        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = uuid4()

        # Create error model
        error = ModelErrorEvent(
            correlation_id=correlation_id,
            error_type=type(exception).__name__,
            error_category=error_category,
            error_severity=error_severity,
            error_message=str(exception),
            error_stack_trace=traceback.format_exc(),
            agent_name=agent_name,
            state_snapshot_id=snapshot_id,
            is_recoverable=is_recoverable,
            metadata=metadata or {}
        )

        # Persist error
        error_id = await self.snapshot_effect.persist_error(error)

        if self.verbose_mode == VerboseMode.VERBOSE:
            logger.error(
                f"Recorded {error_severity.value} error: {error_id} "
                f"({error.error_type}: {error.error_message})"
            )

        return error_id

    async def record_success(
        self,
        snapshot_id: Optional[UUID] = None,
        correlation_id: Optional[UUID] = None,
        agent_name: str = "unknown",
        operation_name: str = "unknown_operation",
        success_type: str = "task_completion",
        quality_score: Optional[float] = None,
        execution_time_ms: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UUID:
        """
        Record successful operation.

        Args:
            snapshot_id: Associated state snapshot ID
            correlation_id: Workflow correlation ID
            agent_name: Name of agent
            operation_name: Name of successful operation
            success_type: Type of success event
            quality_score: Quality score (0.0-1.0)
            execution_time_ms: Execution time in milliseconds
            metadata: Additional success metadata

        Returns:
            UUID of success event
        """
        # Generate correlation_id if not provided
        if correlation_id is None:
            correlation_id = uuid4()

        # Create success model
        success = ModelSuccessEvent(
            correlation_id=correlation_id,
            success_type=success_type,
            operation_name=operation_name,
            agent_name=agent_name,
            state_snapshot_id=snapshot_id,
            quality_score=quality_score,
            execution_time_ms=execution_time_ms,
            metadata=metadata or {}
        )

        # Persist success
        success_id = await self.snapshot_effect.persist_success(success)

        if self.verbose_mode == VerboseMode.VERBOSE:
            logger.info(
                f"Recorded success: {success_id} "
                f"(operation: {operation_name}, "
                f"quality: {quality_score if quality_score else 'N/A'})"
            )

        return success_id

    async def link_error_to_success(
        self,
        error_id: UUID,
        success_id: UUID,
        stf_name: Optional[str] = None,
        stf_pointer: Optional[ModelCodePointer] = None,
        recovery_strategy: Optional[str] = None,
        recovery_duration_ms: Optional[int] = None,
        intermediate_steps: Optional[int] = None,
        confidence_score: float = 1.0
    ) -> UUID:
        """
        Link error event to eventual success for pattern learning.

        Args:
            error_id: Error event ID
            success_id: Success event ID
            stf_name: Name of State Transformation Function
            stf_pointer: Code pointer to STF
            recovery_strategy: Strategy used for recovery
            recovery_duration_ms: Time from error to success
            intermediate_steps: Number of steps between error and success
            confidence_score: Confidence in correlation (0.0-1.0)

        Returns:
            UUID of correlation link
        """
        # Generate correlation_id (will match workflow)
        correlation_id = uuid4()

        # Create link model
        link = ModelErrorSuccessLink(
            error_event_id=error_id,
            success_event_id=success_id,
            correlation_id=correlation_id,
            recovery_strategy=recovery_strategy,
            stf_name=stf_name,
            stf_pointer=stf_pointer,
            recovery_duration_ms=recovery_duration_ms,
            intermediate_steps=intermediate_steps,
            confidence_score=confidence_score
        )

        # Persist link
        link_id = await self.snapshot_effect.link_error_to_success(link)

        if self.verbose_mode == VerboseMode.VERBOSE:
            logger.info(
                f"Linked error→success: {link_id} "
                f"(STF: {stf_name if stf_name else 'unknown'}, "
                f"confidence: {confidence_score:.2f})"
            )

        return link_id

    async def recall_similar_states(
        self,
        task_signature: str,
        limit: int = 5
    ) -> List[ModelStateSnapshot]:
        """
        Recall states similar to given task signature.

        Args:
            task_signature: Task description or signature to match
            limit: Maximum number of results

        Returns:
            List of similar state snapshots
        """
        # Query similar snapshots
        snapshots = await self.snapshot_effect.query_similar_snapshots(
            task_signature=task_signature,
            limit=limit
        )

        if self.verbose_mode == VerboseMode.VERBOSE:
            logger.info(
                f"Recalled {len(snapshots)} similar states "
                f"for signature: '{task_signature[:50]}...'"
            )

        return snapshots

    @asynccontextmanager
    async def silent_mode(self):
        """
        Context manager for temporary silent mode.

        Usage:
            async with manager.silent_mode():
                # Operations here use silent mode
                pass
        """
        original_mode = self.verbose_mode
        self.verbose_mode = VerboseMode.SILENT
        try:
            yield
        finally:
            self.verbose_mode = original_mode

    def set_verbose_mode(self, mode: VerboseMode):
        """Set verbose mode."""
        self.verbose_mode = mode
        if mode == VerboseMode.VERBOSE:
            logger.info("Switched to VERBOSE mode")


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_state_manager: Optional[StateManager] = None


def get_state_manager() -> StateManager:
    """Get or create global state manager instance."""
    global _state_manager
    if _state_manager is None:
        _state_manager = StateManager()
    return _state_manager


async def initialize_state_manager() -> bool:
    """Initialize global state manager."""
    manager = get_state_manager()
    return await manager.initialize()

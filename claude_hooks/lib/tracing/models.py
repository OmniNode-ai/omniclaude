"""
Pydantic models for Intelligence Hook System tracing and execution tracking.

These models match the PostgreSQL schema for execution_traces and hook_executions tables,
providing type-safe data validation and serialization for the tracing system.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# Core Trace Models
# ============================================================================


class ExecutionTrace(BaseModel):
    """
    Master record for all execution traces.

    Tracks every user prompt and its execution flow through the system,
    including session context, execution metadata, and outcome tracking.

    Maps to: execution_traces table
    """

    # Primary identification
    id: Optional[UUID] = Field(default=None, description="Primary key, auto-generated")
    correlation_id: UUID = Field(
        description="Unique identifier for this execution chain"
    )
    root_id: UUID = Field(description="Points to the root trace in a nested execution")
    parent_id: Optional[UUID] = Field(
        default=None, description="Parent execution for nested/delegated executions"
    )

    # Session context
    session_id: UUID = Field(description="Session identifier for this execution")
    user_id: Optional[str] = Field(
        default=None, description="User identifier if available"
    )

    # Source information
    source: str = Field(
        description="Source of the execution (e.g., 'claude_code', 'api', 'webhook')"
    )
    prompt_text: Optional[str] = Field(
        default=None, description="Original user prompt or request text"
    )

    # Execution metadata
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When execution started",
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="When execution completed"
    )
    duration_ms: Optional[int] = Field(
        default=None, ge=0, description="Execution duration in milliseconds"
    )
    status: str = Field(
        default="in_progress", description="in_progress, completed, failed, cancelled"
    )

    # Outcome tracking
    success: Optional[bool] = Field(
        default=None, description="Whether execution was successful"
    )
    error_message: Optional[str] = Field(
        default=None, description="Error message if execution failed"
    )
    error_type: Optional[str] = Field(
        default=None, description="Type/category of error"
    )

    # Context and metadata
    context: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional context as JSON"
    )
    tags: Optional[List[str]] = Field(
        default=None, description="Tags for categorization and filtering"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Record creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Record update timestamp",
    )

    class Config:
        """Pydantic configuration"""

        json_schema_extra = {
            "example": {
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                "root_id": "550e8400-e29b-41d4-a716-446655440000",
                "session_id": "660e8400-e29b-41d4-a716-446655440001",
                "source": "claude_code",
                "prompt_text": "Implement user authentication",
                "status": "in_progress",
                "tags": ["authentication", "security"],
            }
        }

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is one of the allowed values"""
        allowed = {"in_progress", "completed", "failed", "cancelled"}
        if v not in allowed:
            raise ValueError(f"Status must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_completion(self) -> "ExecutionTrace":
        """Validate completion state consistency"""
        if self.completed_at is not None and self.started_at is not None:
            # Calculate duration if not set
            if self.duration_ms is None:
                delta = self.completed_at - self.started_at
                self.duration_ms = int(delta.total_seconds() * 1000)

        # Set success based on status if not explicitly set
        if self.success is None and self.status in {"completed", "failed"}:
            self.success = self.status == "completed"

        return self

    def to_db_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database insertion.

        Handles UUID and datetime serialization appropriately.
        """
        data = self.model_dump(exclude_none=False)

        # Convert UUIDs to strings for PostgreSQL
        for key in ["id", "correlation_id", "root_id", "parent_id", "session_id"]:
            if data.get(key) is not None:
                data[key] = str(data[key])

        return data

    def mark_completed(
        self, success: bool = True, error_message: Optional[str] = None
    ) -> None:
        """
        Mark the trace as completed.

        Args:
            success: Whether the execution was successful
            error_message: Error message if failed
        """
        self.completed_at = datetime.now(timezone.utc)
        self.status = "completed" if success else "failed"
        self.success = success
        if error_message:
            self.error_message = error_message

        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

        self.updated_at = datetime.now(timezone.utc)


class HookExecution(BaseModel):
    """
    Track all Claude Code hook executions.

    Records detailed information about each hook that executes during a trace,
    including timing, input/output, intelligence integration, and errors.

    Maps to: hook_executions table
    """

    # Primary identification
    id: Optional[UUID] = Field(default=None, description="Primary key, auto-generated")
    trace_id: UUID = Field(description="Foreign key to execution_traces")

    # Hook identification
    hook_type: str = Field(
        description="UserPromptSubmit, PreToolUse, PostToolUse, Stop, SessionStart, SessionEnd"
    )
    hook_name: str = Field(description="Specific hook name/identifier")
    execution_order: int = Field(
        ge=1, description="Order of execution within the trace (1, 2, 3...)"
    )

    # Execution details
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When hook started",
    )
    completed_at: Optional[datetime] = Field(
        default=None, description="When hook completed"
    )
    duration_ms: Optional[int] = Field(
        default=None, ge=0, description="Hook execution duration in milliseconds"
    )
    status: str = Field(
        default="in_progress", description="in_progress, completed, failed"
    )

    # Input/Output
    input_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Hook input data as JSON"
    )
    output_data: Optional[Dict[str, Any]] = Field(
        default=None, description="Hook output data as JSON"
    )
    modifications_made: Optional[Dict[str, Any]] = Field(
        default=None, description="Any file modifications or actions taken"
    )

    # Intelligence integration
    rag_query_performed: bool = Field(
        default=False, description="Whether RAG query was performed"
    )
    rag_results: Optional[Dict[str, Any]] = Field(
        default=None, description="RAG query results as JSON"
    )
    quality_check_performed: bool = Field(
        default=False, description="Whether quality check was performed"
    )
    quality_results: Optional[Dict[str, Any]] = Field(
        default=None, description="Quality check results as JSON"
    )

    # Error tracking
    error_message: Optional[str] = Field(
        default=None, description="Error message if hook failed"
    )
    error_type: Optional[str] = Field(
        default=None, description="Type/category of error"
    )
    error_stack: Optional[str] = Field(
        default=None, description="Full error stack trace"
    )

    # Metadata
    tool_name: Optional[str] = Field(
        default=None, description="Tool being used (e.g., 'Write', 'Edit', 'Read')"
    )
    file_path: Optional[str] = Field(
        default=None, description="File path being operated on"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="Additional metadata as JSON"
    )

    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Record creation timestamp",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Record update timestamp",
    )

    class Config:
        """Pydantic configuration"""

        json_schema_extra = {
            "example": {
                "trace_id": "550e8400-e29b-41d4-a716-446655440000",
                "hook_type": "PreToolUse",
                "hook_name": "quality_validation_hook",
                "execution_order": 1,
                "tool_name": "Write",
                "file_path": "/path/to/file.py",
                "rag_query_performed": True,
                "quality_check_performed": True,
            }
        }

    @field_validator("hook_type")
    @classmethod
    def validate_hook_type(cls, v: str) -> str:
        """Validate hook type is one of the allowed values"""
        allowed = {
            "UserPromptSubmit",
            "PreToolUse",
            "PostToolUse",
            "Stop",
            "SessionStart",
            "SessionEnd",
        }
        if v not in allowed:
            raise ValueError(f"Hook type must be one of {allowed}, got '{v}'")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Validate status is one of the allowed values"""
        allowed = {"in_progress", "completed", "failed"}
        if v not in allowed:
            raise ValueError(f"Status must be one of {allowed}, got '{v}'")
        return v

    @model_validator(mode="after")
    def validate_completion(self) -> "HookExecution":
        """Validate completion state consistency"""
        if self.completed_at is not None and self.started_at is not None:
            # Calculate duration if not set
            if self.duration_ms is None:
                delta = self.completed_at - self.started_at
                self.duration_ms = int(delta.total_seconds() * 1000)

        return self

    def to_db_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary for database insertion.

        Handles UUID and datetime serialization appropriately.
        """
        data = self.model_dump(exclude_none=False)

        # Convert UUIDs to strings for PostgreSQL
        for key in ["id", "trace_id"]:
            if data.get(key) is not None:
                data[key] = str(data[key])

        return data

    def mark_completed(
        self, success: bool = True, error_message: Optional[str] = None
    ) -> None:
        """
        Mark the hook execution as completed.

        Args:
            success: Whether the hook execution was successful
            error_message: Error message if failed
        """
        self.completed_at = datetime.now(timezone.utc)
        self.status = "completed" if success else "failed"
        if error_message:
            self.error_message = error_message

        if self.started_at:
            delta = self.completed_at - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)

        self.updated_at = datetime.now(timezone.utc)


# ============================================================================
# Helper Models
# ============================================================================


class TraceContext(BaseModel):
    """
    Context information for trace propagation.

    Lightweight model for passing trace context between components
    without carrying the full ExecutionTrace model.
    """

    correlation_id: UUID = Field(
        description="Unique identifier for this execution chain"
    )
    root_id: UUID = Field(description="Root trace identifier")
    parent_id: Optional[UUID] = Field(
        default=None, description="Parent trace identifier"
    )
    session_id: UUID = Field(description="Session identifier")

    class Config:
        """Pydantic configuration"""

        json_schema_extra = {
            "example": {
                "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
                "root_id": "550e8400-e29b-41d4-a716-446655440000",
                "session_id": "660e8400-e29b-41d4-a716-446655440001",
            }
        }

    @classmethod
    def from_trace(cls, trace: ExecutionTrace) -> "TraceContext":
        """Create TraceContext from an ExecutionTrace"""
        return cls(
            correlation_id=trace.correlation_id,
            root_id=trace.root_id,
            parent_id=trace.parent_id,
            session_id=trace.session_id,
        )

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary with string values for headers/metadata"""
        return {
            "correlation_id": str(self.correlation_id),
            "root_id": str(self.root_id),
            "parent_id": str(self.parent_id) if self.parent_id else None,
            "session_id": str(self.session_id),
        }


class HookMetadata(BaseModel):
    """
    Metadata for hook execution results.

    Structured metadata for common hook execution outcomes including
    quality checks, violations, and intelligence results.
    """

    # Quality and compliance
    violations_found: Optional[int] = Field(
        default=None, ge=0, description="Number of violations found"
    )
    corrections_applied: Optional[int] = Field(
        default=None, ge=0, description="Number of corrections applied"
    )
    quality_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Quality score (0.0-1.0)"
    )

    # Tool and execution info
    tool_info: Optional[Dict[str, Any]] = Field(
        default=None, description="Tool-specific information"
    )

    # Intelligence results
    rag_matches: Optional[int] = Field(
        default=None, ge=0, description="Number of RAG matches found"
    )
    rag_confidence: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="RAG confidence score"
    )

    # Performance metrics
    processing_time_ms: Optional[int] = Field(
        default=None, ge=0, description="Processing time in milliseconds"
    )

    # Additional context
    notes: Optional[str] = Field(
        default=None, description="Additional notes or context"
    )

    class Config:
        """Pydantic configuration"""

        json_schema_extra = {
            "example": {
                "violations_found": 3,
                "corrections_applied": 2,
                "quality_score": 0.85,
                "rag_matches": 5,
                "rag_confidence": 0.92,
                "processing_time_ms": 150,
            }
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON storage"""
        return self.model_dump(exclude_none=True)


class HookExecutionSummary(BaseModel):
    """
    Summary of hook execution for reporting.

    Lightweight model for displaying hook execution results without
    all the detailed fields.
    """

    hook_name: str
    hook_type: str
    duration_ms: Optional[int]
    status: str
    success: bool
    rag_query_performed: bool
    quality_check_performed: bool
    error_message: Optional[str] = None

    class Config:
        """Pydantic configuration"""

        json_schema_extra = {
            "example": {
                "hook_name": "quality_validation_hook",
                "hook_type": "PreToolUse",
                "duration_ms": 150,
                "status": "completed",
                "success": True,
                "rag_query_performed": True,
                "quality_check_performed": True,
            }
        }

    @classmethod
    def from_hook_execution(cls, hook: HookExecution) -> "HookExecutionSummary":
        """Create summary from full HookExecution"""
        return cls(
            hook_name=hook.hook_name,
            hook_type=hook.hook_type,
            duration_ms=hook.duration_ms,
            status=hook.status,
            success=hook.status == "completed" and hook.error_message is None,
            rag_query_performed=hook.rag_query_performed,
            quality_check_performed=hook.quality_check_performed,
            error_message=hook.error_message,
        )


# ============================================================================
# Utility Functions
# ============================================================================


def generate_correlation_id() -> UUID:
    """
    Generate a new correlation ID.

    Returns:
        A new UUID v4 for use as a correlation ID
    """
    return uuid4()


def generate_session_id() -> UUID:
    """
    Generate a new session ID.

    Returns:
        A new UUID v4 for use as a session ID
    """
    return uuid4()


def parse_trace_from_row(row: Dict[str, Any]) -> ExecutionTrace:
    """
    Parse an ExecutionTrace from a database row.

    Handles type conversion and None values appropriately.

    Args:
        row: Dictionary from database query result

    Returns:
        ExecutionTrace instance

    Example:
        >>> row = {
        ...     "id": "550e8400-e29b-41d4-a716-446655440000",
        ...     "correlation_id": "660e8400-e29b-41d4-a716-446655440001",
        ...     "root_id": "660e8400-e29b-41d4-a716-446655440001",
        ...     "session_id": "770e8400-e29b-41d4-a716-446655440002",
        ...     "source": "claude_code",
        ...     "started_at": datetime.now(timezone.utc),
        ...     "status": "in_progress"
        ... }
        >>> trace = parse_trace_from_row(row)
    """
    # Convert string UUIDs to UUID objects if needed
    for key in ["id", "correlation_id", "root_id", "parent_id", "session_id"]:
        if key in row and row[key] is not None and isinstance(row[key], str):
            row[key] = UUID(row[key])

    return ExecutionTrace(**row)


def parse_hook_from_row(row: Dict[str, Any]) -> HookExecution:
    """
    Parse a HookExecution from a database row.

    Handles type conversion and None values appropriately.

    Args:
        row: Dictionary from database query result

    Returns:
        HookExecution instance

    Example:
        >>> row = {
        ...     "id": "550e8400-e29b-41d4-a716-446655440000",
        ...     "trace_id": "660e8400-e29b-41d4-a716-446655440001",
        ...     "hook_type": "PreToolUse",
        ...     "hook_name": "quality_check",
        ...     "execution_order": 1,
        ...     "started_at": datetime.now(timezone.utc),
        ...     "status": "in_progress"
        ... }
        >>> hook = parse_hook_from_row(row)
    """
    # Convert string UUIDs to UUID objects if needed
    for key in ["id", "trace_id"]:
        if key in row and row[key] is not None and isinstance(row[key], str):
            row[key] = UUID(row[key])

    return HookExecution(**row)


def create_trace_context(
    correlation_id: Optional[UUID] = None,
    root_id: Optional[UUID] = None,
    parent_id: Optional[UUID] = None,
    session_id: Optional[UUID] = None,
) -> TraceContext:
    """
    Create a new TraceContext with optional parameters.

    If correlation_id is not provided, generates a new one.
    If root_id is not provided, uses correlation_id.
    If session_id is not provided, generates a new one.

    Args:
        correlation_id: Optional correlation ID
        root_id: Optional root ID
        parent_id: Optional parent ID
        session_id: Optional session ID

    Returns:
        TraceContext instance

    Example:
        >>> context = create_trace_context()  # All new IDs
        >>> context2 = create_trace_context(correlation_id=uuid4())  # Specific correlation
    """
    if correlation_id is None:
        correlation_id = generate_correlation_id()

    if root_id is None:
        root_id = correlation_id

    if session_id is None:
        session_id = generate_session_id()

    return TraceContext(
        correlation_id=correlation_id,
        root_id=root_id,
        parent_id=parent_id,
        session_id=session_id,
    )


def create_new_trace(
    source: str,
    session_id: UUID,
    prompt_text: Optional[str] = None,
    user_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    parent_trace: Optional[ExecutionTrace] = None,
) -> ExecutionTrace:
    """
    Create a new ExecutionTrace with proper defaults.

    Handles correlation ID generation and parent/root relationships.

    Args:
        source: Source of the execution
        session_id: Session identifier
        prompt_text: Optional prompt text
        user_id: Optional user identifier
        context: Optional context dictionary
        tags: Optional tags list
        parent_trace: Optional parent trace for nested executions

    Returns:
        New ExecutionTrace instance

    Example:
        >>> trace = create_new_trace(
        ...     source="claude_code",
        ...     session_id=uuid4(),
        ...     prompt_text="Implement authentication",
        ...     tags=["auth", "security"]
        ... )
    """
    correlation_id = generate_correlation_id()

    if parent_trace:
        root_id = parent_trace.root_id
        parent_id = parent_trace.correlation_id
    else:
        root_id = correlation_id
        parent_id = None

    return ExecutionTrace(
        correlation_id=correlation_id,
        root_id=root_id,
        parent_id=parent_id,
        session_id=session_id,
        user_id=user_id,
        source=source,
        prompt_text=prompt_text,
        context=context,
        tags=tags,
    )


def create_new_hook_execution(
    trace_id: UUID,
    hook_type: str,
    hook_name: str,
    execution_order: int,
    tool_name: Optional[str] = None,
    file_path: Optional[str] = None,
    input_data: Optional[Dict[str, Any]] = None,
) -> HookExecution:
    """
    Create a new HookExecution with proper defaults.

    Args:
        trace_id: Parent trace ID
        hook_type: Type of hook
        hook_name: Name of the hook
        execution_order: Order in the execution sequence
        tool_name: Optional tool name
        file_path: Optional file path
        input_data: Optional input data

    Returns:
        New HookExecution instance

    Example:
        >>> hook = create_new_hook_execution(
        ...     trace_id=trace.correlation_id,
        ...     hook_type="PreToolUse",
        ...     hook_name="quality_check",
        ...     execution_order=1,
        ...     tool_name="Write",
        ...     file_path="/path/to/file.py"
        ... )
    """
    return HookExecution(
        trace_id=trace_id,
        hook_type=hook_type,
        hook_name=hook_name,
        execution_order=execution_order,
        tool_name=tool_name,
        file_path=file_path,
        input_data=input_data,
    )

"""
Agent Execution Logger - Comprehensive Logging with Fallback

Logs ALL agent executions to PostgreSQL agent_execution_logs table with
automatic fallback to file logging if database is unavailable.

Logs:
- Execution start (agent_name, user_prompt, correlation_id, session_id)
- Progress updates (stage, percent, metadata)
- Completion (status, quality_score, duration_ms, error details)

Features:
- Dual-path logging: PostgreSQL primary, file fallback
- Non-blocking: Never fails agent execution due to logging issues
- Platform-aware: Uses tempfile.gettempdir() for cross-platform compatibility
- Structured JSON file logs in {temp}/omniclaude_logs/ or .omniclaude_logs/
- Correlation ID tracking for request tracing
- Quality score capture for trend analysis
"""

import json
import os
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from omnibase_core.enums.enum_operation_status import EnumOperationStatus

from .db import get_pg_pool
from .kafka_rpk_client import RpkKafkaClient
from .structured_logger import StructuredLogger

# Lazy initialization for fallback log directory (platform-appropriate)
_FALLBACK_LOG_DIR = None

# DB retry configuration
_DB_RETRY_BACKOFF_SECONDS = [60, 120, 300, 600]  # Exponential backoff: 1m, 2m, 5m, 10m
_MAX_RETRY_ATTEMPTS = len(_DB_RETRY_BACKOFF_SECONDS)


def get_fallback_log_dir() -> Path:
    """Get platform-appropriate fallback log directory with lazy initialization."""
    global _FALLBACK_LOG_DIR
    if _FALLBACK_LOG_DIR is None:
        _FALLBACK_LOG_DIR = _get_fallback_log_dir()
    return _FALLBACK_LOG_DIR


def _get_fallback_log_dir() -> Path:
    """
    Create and verify platform-appropriate fallback log directory.

    Returns:
        Path: Writable log directory (tempdir/omniclaude_logs or .omniclaude_logs)
    """
    # Try platform-appropriate temp directory first
    base_dir = Path(tempfile.gettempdir()) / "omniclaude_logs"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        # Verify writable
        test_file = base_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return base_dir
    except (PermissionError, OSError):
        # Fallback to current directory if temp is not writable
        fallback = Path.cwd() / ".omniclaude_logs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class AgentExecutionLogger:
    """
    Comprehensive agent execution logger with database and file fallback.

    Usage:
        logger = AgentExecutionLogger(
            agent_name="agent-researcher",
            user_prompt="Research ONEX patterns",
            correlation_id=correlation_id
        )

        # Start execution
        execution_id = await logger.start()

        # Log progress
        await logger.progress(stage="gathering_intelligence", percent=25)
        await logger.progress(stage="analyzing_results", percent=75)

        # Complete with success
        await logger.complete(status="success", quality_score=0.92)

        # Or complete with error
        await logger.complete(status="error", error_message=str(error))
    """

    def __init__(
        self,
        agent_name: str,
        user_prompt: Optional[str] = None,
        correlation_id: Optional[UUID | str] = None,
        session_id: Optional[UUID | str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        project_path: Optional[str] = None,
        project_name: Optional[str] = None,
        claude_session_id: Optional[str] = None,
        terminal_id: Optional[str] = None,
    ):
        """
        Initialize agent execution logger.

        Args:
            agent_name: Name of the agent (e.g., "agent-researcher")
            user_prompt: User's original request/prompt
            correlation_id: Correlation ID for request tracing
            session_id: Session ID for grouping related executions
            metadata: Additional metadata to log
            project_path: Path to the project being worked on
            project_name: Name of the project
            claude_session_id: Claude session identifier
            terminal_id: Terminal identifier
        """
        self.agent_name = agent_name
        self.user_prompt = user_prompt
        self.correlation_id = str(correlation_id) if correlation_id else str(uuid4())
        self.session_id = str(session_id) if session_id else str(uuid4())
        self.metadata = metadata or {}
        self.project_path = project_path
        self.project_name = project_name
        self.claude_session_id = claude_session_id
        self.terminal_id = terminal_id

        self.execution_id: Optional[str] = None
        self.started_at: Optional[datetime] = None

        # Structured logger for stderr output
        self.logger = StructuredLogger(
            f"agent_execution.{agent_name}", component=agent_name
        )
        self.logger.set_correlation_id(self.correlation_id)
        self.logger.set_session_id(self.session_id)

        # Track DB availability with retry logic
        self._db_available = True
        self._db_retry_count = 0
        self._last_retry_time = 0.0  # Unix timestamp of last retry attempt

        # Kafka event publishing (optional - graceful degradation if unavailable)
        self._kafka_enabled = (
            os.getenv("KAFKA_ENABLE_LOGGING", "true").lower() == "true"
        )
        self._kafka_client = None
        if self._kafka_enabled:
            try:
                self._kafka_client = RpkKafkaClient()
                self.logger.debug("Kafka event publishing enabled")
            except Exception as e:
                self.logger.warning(
                    "Kafka client initialization failed, disabling event publishing",
                    metadata={"error": str(e)},
                )
                self._kafka_enabled = False

    def _should_retry_db(self) -> bool:
        """
        Check if enough time has passed to retry database connection.

        Returns:
            True if retry should be attempted, False otherwise
        """
        if self._db_available:
            return True

        if self._db_retry_count >= _MAX_RETRY_ATTEMPTS:
            # Max retries reached, stay in fallback mode
            return False

        current_time = time.time()
        backoff_seconds = _DB_RETRY_BACKOFF_SECONDS[self._db_retry_count]
        time_since_last_retry = current_time - self._last_retry_time

        should_retry = time_since_last_retry >= backoff_seconds

        if should_retry:
            retry_msg = (
                f"Retrying database connection "
                f"(attempt {self._db_retry_count + 1}/{_MAX_RETRY_ATTEMPTS})"
            )
            self.logger.info(
                retry_msg,
                metadata={
                    "backoff_seconds": backoff_seconds,
                    "time_since_last_retry": int(time_since_last_retry),
                },
            )

        return should_retry

    def _handle_db_failure(self, error: Exception, operation: str):
        """
        Handle database operation failure with retry tracking.

        Args:
            error: Exception that caused the failure
            operation: Operation name (for logging)
        """
        self._db_available = False
        self._last_retry_time = time.time()
        self._db_retry_count = min(self._db_retry_count + 1, _MAX_RETRY_ATTEMPTS)

        # Calculate next retry delay
        if self._db_retry_count < _MAX_RETRY_ATTEMPTS:
            retry_idx = min(self._db_retry_count, _MAX_RETRY_ATTEMPTS - 1)
            next_retry_in = _DB_RETRY_BACKOFF_SECONDS[retry_idx]
        else:
            next_retry_in = None

        # Format next retry time
        next_retry_str = f"{next_retry_in}s" if next_retry_in else "max_retries_reached"

        self.logger.warning(
            f"Database {operation} failed, using file fallback",
            metadata={
                "error": str(error),
                "retry_count": self._db_retry_count,
                "next_retry_in": next_retry_str,
                "execution_id": self.execution_id,
            },
        )

    def _handle_db_success(self):
        """Reset retry counters on successful database operation."""
        if not self._db_available or self._db_retry_count > 0:
            self.logger.info(
                "Database connection restored",
                metadata={
                    "previous_retry_count": self._db_retry_count,
                    "execution_id": self.execution_id,
                },
            )
        self._db_available = True
        self._db_retry_count = 0
        self._last_retry_time = 0.0

    def _publish_kafka_event(self, event_data: Dict[str, Any]):
        """
        Publish event to Kafka topic 'agent-execution-logs'.

        Args:
            event_data: Event payload to publish

        Note:
            Non-blocking - failures are logged but don't affect execution
        """
        if not self._kafka_enabled or not self._kafka_client:
            return

        try:
            # Add correlation tracking to all events
            event_payload = {
                "correlation_id": self.correlation_id,
                "session_id": self.session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **event_data,
            }

            self._kafka_client.publish("agent-execution-logs", event_payload)
            self.logger.debug(
                "Published event to Kafka",
                metadata={
                    "topic": "agent-execution-logs",
                    "execution_id": self.execution_id,
                },
            )

        except Exception as e:
            # Non-blocking - log but don't fail the execution
            self.logger.warning(
                "Failed to publish event to Kafka",
                metadata={
                    "error": str(e),
                    "execution_id": self.execution_id,
                },
            )

    async def start(self) -> str:
        """
        Log execution start.

        Returns:
            Execution ID (UUID as string)

        Raises:
            Exception: If database logging fails (falls back to file logging)

        Example:
            >>> logger = AgentExecutionLogger(agent_name="agent-researcher")
            >>> execution_id = await logger.start()
        """
        self.execution_id = str(uuid4())
        self.started_at = datetime.now(timezone.utc)

        log_data = {
            "execution_id": self.execution_id,
            "correlation_id": self.correlation_id,
            "session_id": self.session_id,
            "agent_name": self.agent_name,
            "user_prompt": self.user_prompt,
            "started_at": self.started_at.isoformat(),
            "status": "in_progress",
            "metadata": self.metadata,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "claude_session_id": self.claude_session_id,
            "terminal_id": self.terminal_id,
        }

        # Try database logging with retry logic
        if self._should_retry_db():
            try:
                pool = await get_pg_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            INSERT INTO agent_execution_logs (
                                execution_id, correlation_id, session_id,
                                agent_name, user_prompt, status, metadata,
                                project_path, project_name, claude_session_id, terminal_id
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11)
                            """,
                            self.execution_id,
                            self.correlation_id,
                            self.session_id,
                            self.agent_name,
                            self.user_prompt,
                            "in_progress",
                            json.dumps(self.metadata),
                            self.project_path,
                            self.project_name,
                            self.claude_session_id,
                            self.terminal_id,
                        )
                    self._handle_db_success()
                    self.logger.info(
                        "Agent execution started",
                        metadata={
                            "execution_id": self.execution_id,
                            "agent": self.agent_name,
                        },
                    )
                else:
                    raise Exception("Database pool unavailable")

            except Exception as e:
                self._handle_db_failure(e, "start")
                self._write_fallback_log("start", log_data)
        else:
            self._write_fallback_log("start", log_data)

        # Publish to Kafka (async, non-blocking)
        self._publish_kafka_event(
            {
                "execution_id": self.execution_id,
                "agent_name": self.agent_name,
                "user_prompt": self.user_prompt,
                "status": "in_progress",
                "started_at": self.started_at.isoformat(),
                "metadata": self.metadata,
                "project_path": self.project_path,
                "project_name": self.project_name,
                "claude_session_id": self.claude_session_id,
                "terminal_id": self.terminal_id,
            }
        )

        return self.execution_id

    async def progress(
        self,
        stage: str,
        percent: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log execution progress.

        Args:
            stage: Current stage name (e.g., "gathering_intelligence")
            percent: Progress percentage 0-100 (optional)
            metadata: Additional progress metadata (optional)

        Raises:
            Exception: If database logging fails (falls back to file logging)

        Example:
            >>> await logger.progress(stage="gathering_intelligence", percent=25)
            >>> await logger.progress(stage="analyzing", percent=75, metadata={"source": "rag"})
        """
        if not self.execution_id:
            self.logger.warning("Progress logged before start() called")
            return

        # Validate progress percent range (0-100)
        if percent is not None and not (0 <= percent <= 100):
            self.logger.warning(
                "Progress percent out of range (must be 0-100)",
                metadata={"percent": percent, "execution_id": self.execution_id},
            )
            return

        progress_data = {
            "stage": stage,
            "percent": percent,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **(metadata or {}),
        }

        log_data = {
            "execution_id": self.execution_id,
            "progress": progress_data,
        }

        # Try database logging with retry logic
        if self._should_retry_db():
            try:
                pool = await get_pg_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE agent_execution_logs
                            SET metadata = COALESCE(metadata, '{}'::jsonb) || $1::jsonb
                            WHERE execution_id = $2
                            """,
                            json.dumps({"progress": progress_data}),
                            self.execution_id,
                        )
                    self._handle_db_success()
                    self.logger.info(
                        f"Agent progress: {stage}",
                        metadata={
                            "execution_id": self.execution_id,
                            "percent": percent,
                        },
                    )
                else:
                    raise Exception("Database pool unavailable")

            except Exception as e:
                self._handle_db_failure(e, "progress")
                self._write_fallback_log("progress", log_data)
        else:
            self._write_fallback_log("progress", log_data)

        # Publish to Kafka (async, non-blocking)
        self._publish_kafka_event(
            {
                "execution_id": self.execution_id,
                "agent_name": self.agent_name,
                "status": "in_progress",
                "metadata": {"progress": progress_data},
            }
        )

    async def complete(
        self,
        status: EnumOperationStatus = EnumOperationStatus.SUCCESS,
        quality_score: Optional[float] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log execution completion.

        Args:
            status: Execution status (EnumOperationStatus.SUCCESS/FAILED/CANCELLED)
            quality_score: Quality score 0.0-1.0 (optional)
            error_message: Error description if status=FAILED (optional)
            error_type: Error type/class name (optional)
            metadata: Final execution metadata (optional)

        Raises:
            Exception: If database logging fails (falls back to file logging)

        Example:
            >>> await logger.complete(status=EnumOperationStatus.SUCCESS, quality_score=0.92)
            >>> await logger.complete(status=EnumOperationStatus.FAILED, error_message="Timeout")
        """
        if not self.execution_id:
            self.logger.warning("Complete logged before start() called")
            return

        completed_at = datetime.now(timezone.utc)
        duration_ms = None
        if self.started_at:
            duration_ms = int((completed_at - self.started_at).total_seconds() * 1000)

        final_metadata = {
            "completed_at": completed_at.isoformat(),
            **(metadata or {}),
        }

        # Convert enum to string value for storage
        status_value = status.value

        log_data = {
            "execution_id": self.execution_id,
            "status": status_value,
            "quality_score": quality_score,
            "error_message": error_message,
            "error_type": error_type,
            "duration_ms": duration_ms,
            "completed_at": completed_at.isoformat(),
            "metadata": final_metadata,
        }

        # Try database logging with retry logic
        if self._should_retry_db():
            try:
                pool = await get_pg_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE agent_execution_logs
                            SET
                                completed_at = $1,
                                status = $2,
                                quality_score = $3,
                                error_message = $4,
                                error_type = $5,
                                duration_ms = $6,
                                metadata = COALESCE(metadata, '{}'::jsonb) || $7::jsonb
                            WHERE execution_id = $8
                            """,
                            completed_at,
                            status_value,
                            quality_score,
                            error_message,
                            error_type,
                            duration_ms,
                            json.dumps(final_metadata),
                            self.execution_id,
                        )

                    self._handle_db_success()
                    log_method = (
                        self.logger.info
                        if status == EnumOperationStatus.SUCCESS
                        else self.logger.error
                    )
                    log_method(
                        f"Agent execution {status_value}",
                        metadata={
                            "execution_id": self.execution_id,
                            "duration_ms": duration_ms,
                            "quality_score": quality_score,
                        },
                    )
                else:
                    raise Exception("Database pool unavailable")

            except Exception as e:
                self._handle_db_failure(e, "complete")
                self._write_fallback_log("complete", log_data)
        else:
            self._write_fallback_log("complete", log_data)

        # Publish to Kafka (async, non-blocking)
        self._publish_kafka_event(
            {
                "execution_id": self.execution_id,
                "agent_name": self.agent_name,
                "status": status_value,
                "completed_at": completed_at.isoformat(),
                "duration_ms": duration_ms,
                "quality_score": quality_score,
                "error_message": error_message,
                "error_type": error_type,
                "metadata": final_metadata,
            }
        )

    def _write_fallback_log(self, event_type: str, data: Dict[str, Any]):
        """
        Write log to fallback file when database is unavailable.

        Creates structured JSON log files in platform-appropriate temp directory organized by date.

        Args:
            event_type: Type of event (start/progress/complete)
            data: Event data to log

        Raises:
            Exception: If file logging also fails (logs to stderr)

        Example:
            >>> self._write_fallback_log("start", {"execution_id": "abc123"})
        """
        try:
            # Create date-based subdirectory
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_dir = get_fallback_log_dir() / date_str
            log_dir.mkdir(exist_ok=True)

            # Create log file named by execution_id
            log_file = log_dir / f"{self.execution_id}.jsonl"

            # Append log entry (JSONL format - one JSON object per line)
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "agent_name": self.agent_name,
                "correlation_id": self.correlation_id,
                **data,
            }

            # Write with explicit UTF-8 encoding
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")

            # Set secure file permissions (owner read/write only)
            os.chmod(log_file, 0o600)

        except Exception as e:
            # If even file logging fails, log to stderr
            self.logger.error(
                "Fallback file logging failed",
                metadata={"error": str(e), "traceback": traceback.format_exc()},
            )


async def log_agent_execution(
    agent_name: str,
    user_prompt: Optional[str] = None,
    correlation_id: Optional[UUID | str] = None,
    session_id: Optional[UUID | str] = None,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    claude_session_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
) -> AgentExecutionLogger:
    """
    Factory function to create and start agent execution logger.

    Args:
        agent_name: Name of the agent
        user_prompt: User's original request
        correlation_id: Correlation ID for tracing
        session_id: Session ID for grouping
        project_path: Path to the project being worked on
        project_name: Name of the project
        claude_session_id: Claude session identifier
        terminal_id: Terminal identifier

    Returns:
        AgentExecutionLogger instance with execution already started

    Example:
        logger = await log_agent_execution(
            agent_name="agent-researcher",
            user_prompt="Research ONEX patterns",
            correlation_id=correlation_id,
            project_path="/path/to/project"
        )

        await logger.progress(stage="gathering", percent=50)
        await logger.complete(status="success", quality_score=0.92)
    """
    logger = AgentExecutionLogger(
        agent_name=agent_name,
        user_prompt=user_prompt,
        correlation_id=correlation_id,
        session_id=session_id,
        project_path=project_path,
        project_name=project_name,
        claude_session_id=claude_session_id,
        terminal_id=terminal_id,
    )
    await logger.start()
    return logger

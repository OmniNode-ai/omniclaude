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
- Structured JSON file logs in /tmp/omniclaude_logs/
- Correlation ID tracking for request tracing
- Quality score capture for trend analysis
"""

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from .db import get_pg_pool
from .structured_logger import StructuredLogger

# Fallback log directory
FALLBACK_LOG_DIR = Path("/tmp/omniclaude_logs")
FALLBACK_LOG_DIR.mkdir(exist_ok=True)


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
    ):
        """
        Initialize agent execution logger.

        Args:
            agent_name: Name of the agent (e.g., "agent-researcher")
            user_prompt: User's original request/prompt
            correlation_id: Correlation ID for request tracing
            session_id: Session ID for grouping related executions
            metadata: Additional metadata to log
        """
        self.agent_name = agent_name
        self.user_prompt = user_prompt
        self.correlation_id = str(correlation_id) if correlation_id else str(uuid4())
        self.session_id = str(session_id) if session_id else str(uuid4())
        self.metadata = metadata or {}

        self.execution_id: Optional[str] = None
        self.started_at: Optional[datetime] = None

        # Structured logger for stderr output
        self.logger = StructuredLogger(
            f"agent_execution.{agent_name}", component=agent_name
        )
        self.logger.set_correlation_id(self.correlation_id)
        self.logger.set_session_id(self.session_id)

        # Track if DB is available
        self._db_available = True

    async def start(self) -> str:
        """
        Log execution start.

        Returns:
            Execution ID (UUID as string)
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
        }

        # Try database logging first
        try:
            pool = await get_pg_pool()
            if pool:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO agent_execution_logs (
                            execution_id, correlation_id, session_id,
                            agent_name, user_prompt, status, metadata
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                        """,
                        self.execution_id,
                        self.correlation_id,
                        self.session_id,
                        self.agent_name,
                        self.user_prompt,
                        "in_progress",
                        json.dumps(self.metadata),
                    )
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
            self._db_available = False
            self.logger.warning(
                "Database logging failed, using file fallback",
                metadata={"error": str(e), "execution_id": self.execution_id},
            )
            self._write_fallback_log("start", log_data)

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
        """
        if not self.execution_id:
            self.logger.warning("Progress logged before start() called")
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

        # Try database logging
        if self._db_available:
            try:
                pool = await get_pg_pool()
                if pool:
                    async with pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE agent_execution_logs
                            SET metadata = metadata || $1::jsonb
                            WHERE execution_id = $2
                            """,
                            json.dumps({"progress": progress_data}),
                            self.execution_id,
                        )
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
                self._db_available = False
                self.logger.warning(
                    "Database progress logging failed, using file fallback",
                    metadata={"error": str(e)},
                )
                self._write_fallback_log("progress", log_data)
        else:
            self._write_fallback_log("progress", log_data)

    async def complete(
        self,
        status: str = "success",
        quality_score: Optional[float] = None,
        error_message: Optional[str] = None,
        error_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """
        Log execution completion.

        Args:
            status: Execution status (success/error/cancelled)
            quality_score: Quality score 0.0-1.0 (optional)
            error_message: Error description if status=error (optional)
            error_type: Error type/class name (optional)
            metadata: Final execution metadata (optional)
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

        log_data = {
            "execution_id": self.execution_id,
            "status": status,
            "quality_score": quality_score,
            "error_message": error_message,
            "error_type": error_type,
            "duration_ms": duration_ms,
            "completed_at": completed_at.isoformat(),
            "metadata": final_metadata,
        }

        # Try database logging
        if self._db_available:
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
                                metadata = metadata || $6::jsonb
                            WHERE execution_id = $7
                            """,
                            completed_at,
                            status,
                            quality_score,
                            error_message,
                            error_type,
                            json.dumps(final_metadata),
                            self.execution_id,
                        )

                    log_method = (
                        self.logger.info if status == "success" else self.logger.error
                    )
                    log_method(
                        f"Agent execution {status}",
                        metadata={
                            "execution_id": self.execution_id,
                            "duration_ms": duration_ms,
                            "quality_score": quality_score,
                        },
                    )
                else:
                    raise Exception("Database pool unavailable")

            except Exception as e:
                self._db_available = False
                self.logger.warning(
                    "Database completion logging failed, using file fallback",
                    metadata={"error": str(e)},
                )
                self._write_fallback_log("complete", log_data)
        else:
            self._write_fallback_log("complete", log_data)

    def _write_fallback_log(self, event_type: str, data: Dict[str, Any]):
        """
        Write log to fallback file when database is unavailable.

        Creates structured JSON log files in /tmp/omniclaude_logs/ organized by date.

        Args:
            event_type: Type of event (start/progress/complete)
            data: Event data to log
        """
        try:
            # Create date-based subdirectory
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            log_dir = FALLBACK_LOG_DIR / date_str
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

            with open(log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")

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
) -> AgentExecutionLogger:
    """
    Factory function to create and start agent execution logger.

    Args:
        agent_name: Name of the agent
        user_prompt: User's original request
        correlation_id: Correlation ID for tracing
        session_id: Session ID for grouping

    Returns:
        AgentExecutionLogger instance with execution already started

    Example:
        logger = await log_agent_execution(
            agent_name="agent-researcher",
            user_prompt="Research ONEX patterns",
            correlation_id=correlation_id
        )

        await logger.progress(stage="gathering", percent=50)
        await logger.complete(status="success", quality_score=0.92)
    """
    logger = AgentExecutionLogger(
        agent_name=agent_name,
        user_prompt=user_prompt,
        correlation_id=correlation_id,
        session_id=session_id,
    )
    await logger.start()
    return logger

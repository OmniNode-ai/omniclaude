#!/usr/bin/env python3
"""
Hook Event Logger - Fast synchronous database logging for Claude Code hooks

Writes hook events to PostgreSQL hook_events table with minimal overhead.
Target: < 50ms per event for production use.

Graceful Degradation:
- If config/settings is unavailable, logs warning and returns None for all operations
- If database is unavailable, logs warning and returns None
- Never blocks hook execution
"""

import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# psycopg2 imports - these are required, fail early if missing
try:
    import psycopg2
    import psycopg2.extensions
    from psycopg2.extras import Json

    _PSYCOPG2_AVAILABLE = True
except ImportError as e:
    _PSYCOPG2_AVAILABLE = False
    print(
        f"Warning: psycopg2 not available, database logging disabled: {e}",
        file=sys.stderr,
    )
    # Create stub types for type hints
    psycopg2 = None  # type: ignore
    Json = dict  # type: ignore


# Type alias for connection - use Any to avoid strict type checking on psycopg2 internals
Connection = Any  # psycopg2.extensions.connection when available


# Add project root to path for config import
project_root = Path(__file__).resolve().parents[3]  # lib → hooks → claude → omniclaude root
sys.path.insert(0, str(project_root))

# Lazy config import - defer to avoid import-time failures
_settings = None
_settings_error: str | None = None


def _get_settings():
    """Lazily load settings, returning None if unavailable."""
    global _settings, _settings_error

    if _settings is not None:
        return _settings

    if _settings_error is not None:
        # Already tried and failed, don't retry
        return None

    try:
        from config import settings

        _settings = settings
        return _settings
    except ImportError as e:
        _settings_error = f"config module not available: {e}"
        print(f"Warning: {_settings_error}", file=sys.stderr)
        return None
    except Exception as e:
        _settings_error = f"failed to load config.settings: {e}"
        print(f"Warning: {_settings_error}", file=sys.stderr)
        return None


class HookEventLogger:
    """Fast synchronous logger for hook events."""

    def __init__(self, connection_string: str | None = None):
        """Initialize with database connection.

        Args:
            connection_string: PostgreSQL connection string (uses default if None)

        Graceful Degradation:
            - If psycopg2 is unavailable, self._available = False
            - If settings is unavailable, self._available = False
            - All operations return None when unavailable
        """
        self._available = False
        self._conn: Any | None = None
        self.connection_string: str | None = None

        # Check psycopg2 availability
        if not _PSYCOPG2_AVAILABLE:
            print(
                "Warning: HookEventLogger unavailable (psycopg2 not installed)",
                file=sys.stderr,
            )
            return

        if connection_string is None:
            # Use Pydantic Settings to generate connection string
            # This provides type-safe configuration with validation
            settings = _get_settings()
            if settings is None:
                print(
                    "Warning: HookEventLogger unavailable (config.settings not loaded)",
                    file=sys.stderr,
                )
                return

            try:
                connection_string = settings.get_postgres_dsn()
            except Exception as e:
                print(
                    f"Warning: HookEventLogger unavailable (failed to get DSN: {e})",
                    file=sys.stderr,
                )
                return

            # Convert SQLAlchemy-style DSN to psycopg2 format
            # psycopg2 uses: host=... port=... dbname=... user=... password=...
            connection_string = connection_string.replace("postgresql://", "")

            # Parse DSN: user:password@host:port/database
            if "@" in connection_string:
                user_pass, host_db = connection_string.split("@", 1)
                if ":" in user_pass:
                    user, password = user_pass.split(":", 1)
                else:
                    user = user_pass
                    password = ""

                if "/" in host_db:
                    host_port, db = host_db.split("/", 1)
                    if ":" in host_port:
                        host, port = host_port.split(":", 1)
                    else:
                        host = host_port
                        port = "5432"
                else:
                    host = host_db
                    port = "5432"
                    db = "postgres"

                connection_string = (
                    f"host={host} port={port} dbname={db} user={user} password={password}"
                )

        self.connection_string = connection_string
        self._available = True

    def _get_connection(self) -> Any | None:
        """Get or create database connection.

        Returns:
            Database connection if available, None otherwise
        """
        if not self._available:
            return None

        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.connection_string)
        return self._conn

    def log_event(
        self,
        source: str,
        action: str,
        resource: str,
        resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """Log a hook event to the database.

        Args:
            source: Event source (e.g., "PreToolUse", "PostToolUse", "UserPromptSubmit")
            action: Action performed (e.g., "quality_check", "auto_fix", "agent_detected")
            resource: Resource type (e.g., "tool", "file", "prompt")
            resource_id: Resource identifier (e.g., tool name, file path)
            payload: Event payload data
            metadata: Additional metadata

        Returns:
            Event ID if successful, None if failed (including when unavailable)
        """
        # Early exit if logger is not available (graceful degradation)
        if not self._available:
            return None

        try:
            conn = self._get_connection()
            if conn is None:
                return None

            # Generate event ID
            event_id = str(uuid.uuid4())

            # Prepare data
            event_payload = payload or {}
            event_metadata = metadata or {}

            # Add timestamp to metadata
            event_metadata["logged_at"] = datetime.now(UTC).isoformat()

            # Insert event
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hook_events (
                        id, source, action, resource, resource_id,
                        payload, metadata, processed, retry_count, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                """,
                    (
                        event_id,
                        source,
                        action,
                        resource,
                        resource_id,
                        Json(event_payload),
                        Json(event_metadata),
                        False,  # processed
                        0,  # retry_count
                        datetime.now(UTC),
                    ),
                )
                conn.commit()

            return event_id

        except Exception as e:
            # Log error but don't fail the hook
            print(f"⚠️  [HookEventLogger] Failed to log event: {e}", file=sys.stderr)
            try:
                if self._conn is not None:
                    self._conn.rollback()
            except Exception as rollback_error:
                # Log rollback failure - this is critical for debugging database issues
                print(
                    f"⚠️  [HookEventLogger] Failed to rollback transaction: {rollback_error}",
                    file=sys.stderr,
                )
                # Don't re-raise - we already failed to log, don't cascade failures
            return None

    def log_pretooluse(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        correlation_id: str | None = None,
        quality_check_result: dict[str, Any] | None = None,
    ) -> str | None:
        """Log PreToolUse hook event.

        Args:
            tool_name: Name of the tool being invoked
            tool_input: Tool input parameters
            correlation_id: Request correlation ID
            quality_check_result: Quality check results if applicable

        Returns:
            Event ID if successful, None if failed
        """
        metadata = {"hook_type": "PreToolUse", "correlation_id": correlation_id}

        payload = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "quality_check": quality_check_result,
        }

        return self.log_event(
            source="PreToolUse",
            action="tool_invocation",
            resource="tool",
            resource_id=tool_name,
            payload=payload,
            metadata=metadata,
        )

    def log_posttooluse(
        self,
        tool_name: str,
        tool_output: dict[str, Any] | None = None,
        file_path: str | None = None,
        auto_fix_applied: bool = False,
        auto_fix_details: dict[str, Any] | None = None,
    ) -> str | None:
        """Log PostToolUse hook event.

        Args:
            tool_name: Name of the tool that was executed
            tool_output: Tool output/result
            file_path: File path if applicable (Write/Edit tools)
            auto_fix_applied: Whether auto-fixes were applied
            auto_fix_details: Details of auto-fixes if applied

        Returns:
            Event ID if successful, None if failed
        """
        metadata = {"hook_type": "PostToolUse", "auto_fix_applied": auto_fix_applied}

        payload = {
            "tool_name": tool_name,
            "tool_output": tool_output,
            "file_path": file_path,
            "auto_fix_details": auto_fix_details,
        }

        return self.log_event(
            source="PostToolUse",
            action="tool_completion",
            resource="tool",
            resource_id=tool_name,
            payload=payload,
            metadata=metadata,
        )

    def log_userprompt(
        self,
        prompt: str,
        agent_detected: str | None = None,
        agent_domain: str | None = None,
        correlation_id: str | None = None,
        intelligence_queries: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
        detection_method: str | None = None,
        confidence: float | None = None,
        latency_ms: float | None = None,
        reasoning: str | None = None,
    ) -> str | None:
        """Log UserPromptSubmit hook event.

        Args:
            prompt: User's prompt text (truncated to 500 chars)
            agent_detected: Detected agent name if applicable
            agent_domain: Agent domain if applicable
            correlation_id: Request correlation ID
            intelligence_queries: Intelligence queries triggered
            metadata: Enhanced metadata (workflow stage, editor context, etc.)
            detection_method: Method used to detect agent (pattern, trigger, ai, meta_trigger)
            confidence: Detection confidence score (0.0-1.0)
            latency_ms: Detection latency in milliseconds
            reasoning: AI reasoning for agent selection (if applicable)

        Returns:
            Event ID if successful, None if failed
        """
        event_metadata = {
            "hook_type": "UserPromptSubmit",
            "correlation_id": correlation_id,
            "agent_detected": agent_detected is not None,
            "detection_method": detection_method,
            "detection_latency_ms": latency_ms,
        }

        # Merge enhanced metadata if provided
        if metadata:
            event_metadata.update(metadata)

        payload = {
            "prompt_preview": prompt[:500],  # Truncate for storage
            "agent_detected": agent_detected,
            "agent_domain": agent_domain,
            "intelligence_queries": intelligence_queries,
            "detection_method": detection_method,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "reasoning": reasoning[:200] if reasoning else None,  # Truncate reasoning
        }

        return self.log_event(
            source="UserPromptSubmit",
            action="prompt_submitted",
            resource="prompt",
            resource_id=agent_detected or "no_agent",
            payload=payload,
            metadata=event_metadata,
        )

    def close(self) -> None:
        """Close database connection."""
        if not self._available:
            return
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def __del__(self):
        """Cleanup on deletion."""
        try:
            self.close()
        except Exception:
            # Suppress errors during cleanup - don't break the process
            pass


# Singleton instance for reuse across hook invocations
_logger_instance = None


def get_logger() -> HookEventLogger:
    """Get singleton logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = HookEventLogger()
    return _logger_instance


# Convenience functions for quick logging
def log_pretooluse(tool_name: str, tool_input: dict[str, Any], **kwargs) -> str | None:
    """Quick log PreToolUse event."""
    return get_logger().log_pretooluse(tool_name, tool_input, **kwargs)


def log_posttooluse(tool_name: str, **kwargs) -> str | None:
    """Quick log PostToolUse event."""
    return get_logger().log_posttooluse(tool_name, **kwargs)


def log_userprompt(prompt: str, **kwargs) -> str | None:
    """Quick log UserPromptSubmit event."""
    return get_logger().log_userprompt(prompt, **kwargs)


def log_hook_event(
    source: str,
    action: str,
    resource_id: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    """Quick log generic hook event."""
    return get_logger().log_event(
        source=source,
        action=action,
        resource="workflow",
        resource_id=resource_id,
        payload=payload,
        metadata=metadata,
    )


if __name__ == "__main__":
    # Test hook event logging
    print("Testing hook event logger...")

    logger = HookEventLogger()

    # Test PreToolUse event
    event_id = logger.log_pretooluse(
        tool_name="Write",
        tool_input={"file_path": "/test/example.py", "content": "# test"},
        correlation_id="test-correlation-123",
    )
    print(f"✓ PreToolUse event logged: {event_id}")

    # Test PostToolUse event
    event_id = logger.log_posttooluse(
        tool_name="Write",
        file_path="/test/example.py",
        auto_fix_applied=True,
        auto_fix_details={"fixes": ["renamed_variable"]},
    )
    print(f"✓ PostToolUse event logged: {event_id}")

    # Test UserPromptSubmit event
    event_id = logger.log_userprompt(
        prompt="Create a function to calculate fibonacci",
        agent_detected="agent-code-generator",
        agent_domain="code_generation",
        correlation_id="test-correlation-456",
    )
    print(f"✓ UserPromptSubmit event logged: {event_id}")

    logger.close()
    print("\n✅ All tests passed! Check database for events.")

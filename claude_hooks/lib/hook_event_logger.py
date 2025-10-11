#!/usr/bin/env python3
"""
Hook Event Logger - Fast synchronous database logging for Claude Code hooks

Writes hook events to PostgreSQL hook_events table with minimal overhead.
Target: < 50ms per event for production use.
"""

import sys
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import psycopg2
from psycopg2.extras import Json


class HookEventLogger:
    """Fast synchronous logger for hook events."""

    def __init__(self, connection_string: Optional[str] = None):
        """Initialize with database connection.

        Args:
            connection_string: PostgreSQL connection string (uses default if None)
        """
        if connection_string is None:
            connection_string = (
                "host=localhost port=5436 "
                "dbname=omninode_bridge "
                "user=postgres "
                "password=omninode-bridge-postgres-dev-2024"
            )

        self.connection_string = connection_string
        self._conn = None

    def _get_connection(self):
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.connection_string)
        return self._conn

    def log_event(
        self,
        source: str,
        action: str,
        resource: str,
        resource_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Log a hook event to the database.

        Args:
            source: Event source (e.g., "PreToolUse", "PostToolUse", "UserPromptSubmit")
            action: Action performed (e.g., "quality_check", "auto_fix", "agent_detected")
            resource: Resource type (e.g., "tool", "file", "prompt")
            resource_id: Resource identifier (e.g., tool name, file path)
            payload: Event payload data
            metadata: Additional metadata

        Returns:
            Event ID if successful, None if failed
        """
        try:
            conn = self._get_connection()

            # Generate event ID
            event_id = str(uuid.uuid4())

            # Prepare data
            event_payload = payload or {}
            event_metadata = metadata or {}

            # Add timestamp to metadata
            event_metadata['logged_at'] = datetime.now(timezone.utc).isoformat()

            # Insert event
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO hook_events (
                        id, source, action, resource, resource_id,
                        payload, metadata, processed, retry_count, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    )
                """, (
                    event_id,
                    source,
                    action,
                    resource,
                    resource_id,
                    Json(event_payload),
                    Json(event_metadata),
                    False,  # processed
                    0,      # retry_count
                    datetime.now(timezone.utc)
                ))
                conn.commit()

            return event_id

        except Exception as e:
            # Log error but don't fail the hook
            print(f"⚠️  [HookEventLogger] Failed to log event: {e}", file=sys.stderr)
            try:
                if self._conn:
                    self._conn.rollback()
            except:
                pass
            return None

    def log_pretooluse(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        correlation_id: Optional[str] = None,
        quality_check_result: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Log PreToolUse hook event.

        Args:
            tool_name: Name of the tool being invoked
            tool_input: Tool input parameters
            correlation_id: Request correlation ID
            quality_check_result: Quality check results if applicable

        Returns:
            Event ID if successful, None if failed
        """
        metadata = {
            "hook_type": "PreToolUse",
            "correlation_id": correlation_id
        }

        payload = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "quality_check": quality_check_result
        }

        return self.log_event(
            source="PreToolUse",
            action="tool_invocation",
            resource="tool",
            resource_id=tool_name,
            payload=payload,
            metadata=metadata
        )

    def log_posttooluse(
        self,
        tool_name: str,
        tool_output: Optional[Dict[str, Any]] = None,
        file_path: Optional[str] = None,
        auto_fix_applied: bool = False,
        auto_fix_details: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
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
        metadata = {
            "hook_type": "PostToolUse",
            "auto_fix_applied": auto_fix_applied
        }

        payload = {
            "tool_name": tool_name,
            "tool_output": tool_output,
            "file_path": file_path,
            "auto_fix_details": auto_fix_details
        }

        return self.log_event(
            source="PostToolUse",
            action="tool_completion",
            resource="tool",
            resource_id=tool_name,
            payload=payload,
            metadata=metadata
        )

    def log_userprompt(
        self,
        prompt: str,
        agent_detected: Optional[str] = None,
        agent_domain: Optional[str] = None,
        correlation_id: Optional[str] = None,
        intelligence_queries: Optional[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        detection_method: Optional[str] = None,
        confidence: Optional[float] = None,
        latency_ms: Optional[float] = None,
        reasoning: Optional[str] = None
    ) -> Optional[str]:
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
            "detection_latency_ms": latency_ms
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
            "reasoning": reasoning[:200] if reasoning else None  # Truncate reasoning
        }

        return self.log_event(
            source="UserPromptSubmit",
            action="prompt_submitted",
            resource="prompt",
            resource_id=agent_detected or "no_agent",
            payload=payload,
            metadata=event_metadata
        )

    def close(self):
        """Close database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()
            self._conn = None

    def __del__(self):
        """Cleanup on deletion."""
        self.close()


# Singleton instance for reuse across hook invocations
_logger_instance = None


def get_logger() -> HookEventLogger:
    """Get singleton logger instance."""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = HookEventLogger()
    return _logger_instance


# Convenience functions for quick logging
def log_pretooluse(tool_name: str, tool_input: Dict[str, Any], **kwargs) -> Optional[str]:
    """Quick log PreToolUse event."""
    return get_logger().log_pretooluse(tool_name, tool_input, **kwargs)


def log_posttooluse(tool_name: str, **kwargs) -> Optional[str]:
    """Quick log PostToolUse event."""
    return get_logger().log_posttooluse(tool_name, **kwargs)


def log_userprompt(prompt: str, **kwargs) -> Optional[str]:
    """Quick log UserPromptSubmit event."""
    return get_logger().log_userprompt(prompt, **kwargs)


def log_hook_event(source: str, action: str, resource_id: Optional[str] = None,
                    payload: Optional[Dict[str, Any]] = None,
                    metadata: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """Quick log generic hook event."""
    return get_logger().log_event(
        source=source,
        action=action,
        resource="workflow",
        resource_id=resource_id,
        payload=payload,
        metadata=metadata
    )


if __name__ == "__main__":
    # Test hook event logging
    print("Testing hook event logger...")

    logger = HookEventLogger()

    # Test PreToolUse event
    event_id = logger.log_pretooluse(
        tool_name="Write",
        tool_input={"file_path": "/test/example.py", "content": "# test"},
        correlation_id="test-correlation-123"
    )
    print(f"✓ PreToolUse event logged: {event_id}")

    # Test PostToolUse event
    event_id = logger.log_posttooluse(
        tool_name="Write",
        file_path="/test/example.py",
        auto_fix_applied=True,
        auto_fix_details={"fixes": ["renamed_variable"]}
    )
    print(f"✓ PostToolUse event logged: {event_id}")

    # Test UserPromptSubmit event
    event_id = logger.log_userprompt(
        prompt="Create a function to calculate fibonacci",
        agent_detected="agent-code-generator",
        agent_domain="code_generation",
        correlation_id="test-correlation-456"
    )
    print(f"✓ UserPromptSubmit event logged: {event_id}")

    logger.close()
    print("\n✅ All tests passed! Check database for events.")

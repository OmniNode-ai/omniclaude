#!/usr/bin/env python3
"""
Action Event Publisher - Kafka Integration for Agent Actions

Publishes agent action events (tool calls, decisions, errors) to Kafka for async logging to PostgreSQL.
Lightweight, non-blocking, with graceful degradation if Kafka is unavailable.

Usage:
    from agents.lib.action_event_publisher import publish_action_event

    await publish_action_event(
        agent_name="agent-researcher",
        action_type="tool_call",
        action_name="Read",
        action_details={
            "file_path": "/path/to/file.py",
            "line_count": 100,
            "file_size_bytes": 5432
        },
        correlation_id=correlation_id,
        duration_ms=45
    )

Features:
- Non-blocking async publishing
- Graceful degradation (logs error but doesn't fail execution)
- Automatic producer connection management
- JSON serialization with datetime handling
- Correlation ID tracking for distributed tracing
- Support for tool calls, decisions, errors, and success events
"""

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

# Import Pydantic Settings for type-safe configuration
try:
    from config import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)

# Lazy-loaded Kafka producer (singleton)
_kafka_producer = None
_producer_lock: Optional[asyncio.Lock] = None

# Threading lock for thread-safe asyncio.Lock creation
_lock_creation_lock = threading.Lock()


async def get_producer_lock():
    """
    Get or create the producer lock lazily under a running event loop.

    Uses double-checked locking pattern to ensure thread-safe lock creation.
    This prevents race conditions where multiple coroutines could create
    separate lock instances.

    This ensures asyncio.Lock() is never created at module level, which
    would cause RuntimeError in Python 3.12+ when no event loop exists.

    Returns:
        asyncio.Lock: The producer lock instance
    """
    global _producer_lock

    # First check (no lock) - fast path for already-initialized case
    if _producer_lock is None:
        # Acquire threading lock for creation
        with _lock_creation_lock:
            # Second check (with lock) - ensures only one coroutine creates the lock
            if _producer_lock is None:
                _producer_lock = asyncio.Lock()

    return _producer_lock


def _get_kafka_bootstrap_servers() -> str:
    """Get Kafka bootstrap servers from environment or settings."""
    # Try Pydantic settings first (if available)
    if settings:
        try:
            servers = settings.get_effective_kafka_bootstrap_servers()
            return servers
        except Exception as e:
            logger.debug(f"Failed to get Kafka servers from settings: {e}")

    # Fall back to environment variable
    servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        # Use production external endpoint as last resort (matches Pydantic settings default for host)
        # Note: For Docker contexts, KAFKA_BOOTSTRAP_SERVERS should be explicitly set to internal endpoint
        servers = "192.168.86.200:29092"
        logger.warning(
            f"KAFKA_BOOTSTRAP_SERVERS not configured. Using production external endpoint: {servers}. "
            f"For Docker containers, set KAFKA_BOOTSTRAP_SERVERS=omninode-bridge-redpanda:9092"
        )
    return servers


async def _get_kafka_producer():
    """
    Get or create Kafka producer (async singleton pattern).

    Returns:
        AIOKafkaProducer instance or None if unavailable
    """
    global _kafka_producer

    if _kafka_producer is not None:
        return _kafka_producer

    # Get the lock (created lazily under running event loop)
    async with await get_producer_lock():
        # Double-check after acquiring lock
        if _kafka_producer is not None:
            return _kafka_producer

        try:
            from aiokafka import AIOKafkaProducer

            bootstrap_servers = _get_kafka_bootstrap_servers()

            producer = AIOKafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                compression_type="gzip",
                linger_ms=10,  # Batch for 10ms
                acks=1,  # Leader acknowledgment (balance speed/reliability)
                max_batch_size=16384,  # 16KB batches
                request_timeout_ms=5000,  # 5 second timeout
            )

            await producer.start()
            _kafka_producer = producer
            logger.info(f"Kafka producer initialized: {bootstrap_servers}")
            return producer

        except ImportError:
            logger.error("aiokafka not installed. Install with: pip install aiokafka")
            return None
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            return None


async def publish_action_event(
    agent_name: str,
    action_type: str,
    action_name: str,
    action_details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str | UUID] = None,
    duration_ms: Optional[int] = None,
    debug_mode: bool = True,
    project_path: Optional[str] = None,
    project_name: Optional[str] = None,
    working_directory: Optional[str] = None,
) -> bool:
    """
    Publish agent action event to Kafka.

    Args:
        agent_name: Agent executing the action (e.g., "agent-researcher")
        action_type: Type of action ('tool_call', 'decision', 'error', 'success')
        action_name: Specific action name (e.g., 'Read', 'Write', 'select_agent')
        action_details: Full details of action (file paths, parameters, results, etc.)
        correlation_id: Request correlation ID for distributed tracing
        duration_ms: How long the action took in milliseconds
        debug_mode: Whether this was logged in debug mode (for cleanup)
        project_path: Path to project directory
        project_name: Name of project
        working_directory: Current working directory

    Returns:
        bool: True if published successfully, False otherwise
    """
    try:
        # Generate correlation ID if not provided
        if correlation_id is None:
            correlation_id = str(uuid4())
        else:
            correlation_id = str(correlation_id)

        # Validate action_type
        valid_types = ["tool_call", "decision", "error", "success"]
        if action_type not in valid_types:
            logger.warning(
                f"Invalid action_type '{action_type}', must be one of {valid_types}. "
                f"Using 'tool_call' as fallback."
            )
            action_type = "tool_call"

        # Build event payload
        event = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_name": action_name,
            "action_details": action_details or {},
            "debug_mode": debug_mode,
            "duration_ms": duration_ms,
            "project_path": project_path,
            "project_name": project_name,
            "working_directory": working_directory,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Remove None values to keep payload compact
        event = {k: v for k, v in event.items() if v is not None}

        # Get producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning("Kafka producer unavailable, action event not published")
            return False

        # Publish to Kafka
        topic = "agent-actions"
        partition_key = correlation_id.encode("utf-8")

        await producer.send_and_wait(topic, value=event, key=partition_key)

        logger.debug(
            f"Published action event: {action_type}/{action_name} "
            f"(agent={agent_name}, correlation_id={correlation_id})"
        )
        return True

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        logger.error(f"Failed to publish action event: {e}", exc_info=True)
        return False


async def publish_tool_call(
    agent_name: str,
    tool_name: str,
    tool_parameters: Optional[Dict[str, Any]] = None,
    tool_result: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str | UUID] = None,
    duration_ms: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    Publish tool call action event.

    Convenience method for publishing tool executions (Read, Write, Edit, Bash, etc.).

    Args:
        agent_name: Agent executing the tool
        tool_name: Tool name (e.g., 'Read', 'Write', 'Bash')
        tool_parameters: Tool input parameters
        tool_result: Tool execution result
        correlation_id: Correlation ID
        duration_ms: Execution time
        success: Whether tool succeeded
        error_message: Error message if failed
        **kwargs: Additional fields (project_path, etc.)

    Returns:
        bool: True if published successfully
    """
    action_details = {
        "tool_parameters": tool_parameters or {},
        "tool_result": tool_result or {},
        "success": success,
    }

    if error_message:
        action_details["error_message"] = error_message

    return await publish_action_event(
        agent_name=agent_name,
        action_type="tool_call",
        action_name=tool_name,
        action_details=action_details,
        correlation_id=correlation_id,
        duration_ms=duration_ms,
        **kwargs,
    )


async def publish_decision(
    agent_name: str,
    decision_name: str,
    decision_context: Optional[Dict[str, Any]] = None,
    decision_result: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str | UUID] = None,
    duration_ms: Optional[int] = None,
    **kwargs,
) -> bool:
    """
    Publish decision action event.

    Convenience method for publishing agent decisions (routing, transformation, etc.).

    Args:
        agent_name: Agent making the decision
        decision_name: Decision name (e.g., 'select_agent', 'choose_strategy')
        decision_context: Context for decision
        decision_result: Decision outcome
        correlation_id: Correlation ID
        duration_ms: Decision time
        **kwargs: Additional fields

    Returns:
        bool: True if published successfully
    """
    action_details = {
        "decision_context": decision_context or {},
        "decision_result": decision_result or {},
    }

    return await publish_action_event(
        agent_name=agent_name,
        action_type="decision",
        action_name=decision_name,
        action_details=action_details,
        correlation_id=correlation_id,
        duration_ms=duration_ms,
        **kwargs,
    )


async def publish_error(
    agent_name: str,
    error_type: str,
    error_message: str,
    error_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str | UUID] = None,
    **kwargs,
) -> bool:
    """
    Publish error action event.

    Convenience method for publishing agent errors.

    Args:
        agent_name: Agent that encountered error
        error_type: Error type (e.g., 'ImportError', 'RuntimeError')
        error_message: Error message
        error_context: Additional error context
        correlation_id: Correlation ID
        **kwargs: Additional fields

    Returns:
        bool: True if published successfully
    """
    action_details = {
        "error_type": error_type,
        "error_message": error_message,
        "error_context": error_context or {},
    }

    return await publish_action_event(
        agent_name=agent_name,
        action_type="error",
        action_name=error_type,
        action_details=action_details,
        correlation_id=correlation_id,
        **kwargs,
    )


async def publish_success(
    agent_name: str,
    success_name: str,
    success_details: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str | UUID] = None,
    duration_ms: Optional[int] = None,
    **kwargs,
) -> bool:
    """
    Publish success action event.

    Convenience method for publishing agent successes.

    Args:
        agent_name: Agent that succeeded
        success_name: Success name (e.g., 'task_completed', 'file_processed')
        success_details: Success details
        correlation_id: Correlation ID
        duration_ms: Operation time
        **kwargs: Additional fields

    Returns:
        bool: True if published successfully
    """
    action_details = success_details or {}

    return await publish_action_event(
        agent_name=agent_name,
        action_type="success",
        action_name=success_name,
        action_details=action_details,
        correlation_id=correlation_id,
        duration_ms=duration_ms,
        **kwargs,
    )


async def close_producer():
    """Close Kafka producer on shutdown."""
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            await _kafka_producer.stop()
            logger.info("Kafka producer closed")
        except Exception as e:
            logger.error(f"Error closing Kafka producer: {e}")
        finally:
            _kafka_producer = None


# Synchronous wrapper for backward compatibility
def publish_action_event_sync(
    agent_name: str, action_type: str, action_name: str, **kwargs
) -> bool:
    """
    Synchronous wrapper for publish_action_event.

    Creates new event loop if needed. Use async version when possible.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(
        publish_action_event(
            agent_name=agent_name,
            action_type=action_type,
            action_name=action_name,
            **kwargs,
        )
    )


if __name__ == "__main__":
    # Test action event publishing
    async def test():
        logging.basicConfig(level=logging.DEBUG)

        # Test tool call
        from pathlib import Path

        project_path = str(Path(__file__).parent.parent.parent.resolve())
        success = await publish_tool_call(
            agent_name="agent-researcher",
            tool_name="Read",
            tool_parameters={
                "file_path": "/path/to/file.py",
                "offset": 0,
                "limit": 100,
            },
            tool_result={"line_count": 100, "file_size_bytes": 5432},
            correlation_id=str(uuid4()),
            duration_ms=45,
            project_path=project_path,
            project_name="omniclaude",
        )

        print(f"Tool call event published: {success}")

        # Test decision
        success = await publish_decision(
            agent_name="agent-router",
            decision_name="select_agent",
            decision_context={
                "user_request": "Help me debug this code",
                "candidates": ["agent-researcher", "agent-debugger"],
            },
            decision_result={"selected_agent": "agent-debugger", "confidence": 0.92},
            correlation_id=str(uuid4()),
            duration_ms=12,
        )

        print(f"Decision event published: {success}")

        # Test error
        success = await publish_error(
            agent_name="agent-researcher",
            error_type="ImportError",
            error_message="Module 'foo' not found",
            error_context={"file": "/path/to/file.py", "line": 15},
            correlation_id=str(uuid4()),
        )

        print(f"Error event published: {success}")

        # Close producer
        await close_producer()

    asyncio.run(test())

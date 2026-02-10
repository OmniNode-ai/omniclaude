#!/usr/bin/env python3
"""
Action Event Publisher - Kafka Integration for Agent Actions

Publishes agent action events (tool calls, decisions, errors) to Kafka for async logging to PostgreSQL.
Lightweight, non-blocking, with graceful degradation if Kafka is unavailable.

Usage:
    from omniclaude.lib.core.action_event_publisher import publish_action_event

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
import atexit
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

# Configuration (settings provides fallback for bootstrap servers)
from omniclaude.config import settings
from omniclaude.hooks.topics import TopicBase, build_topic

# Import Prometheus metrics (optional integration)
try:
    from omniclaude.lib.prometheus_metrics import (
        event_publish_counter,
        event_publish_errors_counter,
        record_event_publish,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:  # nosec B110 - Optional dependency, graceful degradation
    PROMETHEUS_AVAILABLE = False
    logging.debug("Prometheus metrics not available - metrics disabled")

logger = logging.getLogger(__name__)


# =============================================================================
# Event Config Models (ONEX: Parameter reduction pattern)
# =============================================================================


@dataclass(frozen=True)
class ModelActionEventConfig:
    """Configuration for action event publishing.

    Groups related parameters for publish_action_event() to reduce
    function signature complexity per ONEX parameter guidelines.

    Attributes:
        agent_name: Agent executing the action.
        action_type: Type of action ('tool_call', 'decision', 'error', 'success').
        action_name: Specific action name.
        action_details: Full details of action.
        correlation_id: Request correlation ID for distributed tracing.
        duration_ms: How long the action took in milliseconds.
        debug_mode: Whether this was logged in debug mode.
        project_path: Path to project directory.
        project_name: Name of project.
        working_directory: Current working directory.
    """

    agent_name: str
    action_type: str
    action_name: str
    action_details: dict[str, Any] | None = None
    correlation_id: str | UUID | None = None
    duration_ms: int | None = None
    debug_mode: bool = True
    project_path: str | None = None
    project_name: str | None = None
    working_directory: str | None = None


@dataclass(frozen=True)
class ModelToolCallConfig:
    """Configuration for tool call event publishing.

    Groups related parameters for publish_tool_call() to reduce
    function signature complexity per ONEX parameter guidelines.

    Attributes:
        agent_name: Agent executing the tool.
        tool_name: Tool name (e.g., 'Read', 'Write', 'Bash').
        tool_parameters: Tool input parameters.
        tool_result: Tool execution result.
        correlation_id: Correlation ID.
        duration_ms: Execution time.
        success: Whether tool succeeded.
        error_message: Error message if failed.
        project_path: Path to project directory.
        project_name: Name of project.
        working_directory: Current working directory.
    """

    agent_name: str
    tool_name: str
    tool_parameters: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    correlation_id: str | UUID | None = None
    duration_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    project_path: str | None = None
    project_name: str | None = None
    working_directory: str | None = None


# Kafka publish timeout (10 seconds)
# Prevents indefinite blocking if broker is slow/unresponsive
KAFKA_PUBLISH_TIMEOUT_SECONDS = 10.0

# Lazy-loaded Kafka producer (singleton)
_kafka_producer: Any | None = None
_producer_lock: asyncio.Lock | None = None

# Threading lock for thread-safe asyncio.Lock creation
_lock_creation_lock = threading.Lock()


async def get_producer_lock() -> asyncio.Lock:
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
    """Get Kafka bootstrap servers from settings."""
    # Use Pydantic settings (fail fast if not configured properly)
    try:
        servers: str = settings.get_effective_kafka_bootstrap_servers()
        return servers
    except Exception as e:
        logger.debug(f"Failed to get Kafka servers from settings: {e}")

    # Fall back to environment variable
    env_servers: str | None = os.getenv("KAFKA_BOOTSTRAP_SERVERS")
    if env_servers:
        return env_servers

    # Use localhost as safe default - works in most development environments
    # Production deployments should always set KAFKA_BOOTSTRAP_SERVERS explicitly
    fallback_host = os.getenv("KAFKA_FALLBACK_HOST", "localhost")
    fallback_port = os.getenv("KAFKA_FALLBACK_PORT", "9092")
    default_servers = f"{fallback_host}:{fallback_port}"
    logger.warning(
        f"KAFKA_BOOTSTRAP_SERVERS not configured. Using fallback: {default_servers}. "
        f"Set KAFKA_BOOTSTRAP_SERVERS environment variable for production use."
    )
    return default_servers


def _get_kafka_topic_prefix() -> str:
    """Get Kafka topic prefix.

    Returns:
        Empty string. Topics are realm-agnostic per ONEX convention (OMN-1972):
        TopicBase values ARE the wire topic names, no environment prefix.
    """
    return ""


async def _get_kafka_producer() -> Any:
    """
    Get or create Kafka producer (async singleton pattern).

    Returns:
        AIOKafkaProducer instance or None if unavailable
    """
    global _kafka_producer

    # Check if producer already exists - use local reference for type narrowing
    producer = _kafka_producer
    if producer is not None:
        return producer

    # Get the lock (created lazily under running event loop)
    lock = await get_producer_lock()
    async with lock:
        # Double-check after acquiring lock
        producer = _kafka_producer
        if producer is not None:
            return producer

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


async def publish_action_event_from_config(
    config: ModelActionEventConfig,
) -> bool:
    """Publish agent action event to Kafka from config object.

    Args:
        config: Action event configuration containing all event data.

    Returns:
        bool: True if published successfully, False otherwise.
    """
    return await publish_action_event(
        agent_name=config.agent_name,
        action_type=config.action_type,
        action_name=config.action_name,
        action_details=config.action_details,
        correlation_id=config.correlation_id,
        duration_ms=config.duration_ms,
        debug_mode=config.debug_mode,
        project_path=config.project_path,
        project_name=config.project_name,
        working_directory=config.working_directory,
    )


async def publish_action_event(
    agent_name: str,
    action_type: str,
    action_name: str,
    action_details: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    duration_ms: int | None = None,
    debug_mode: bool = True,
    project_path: str | None = None,
    project_name: str | None = None,
    working_directory: str | None = None,
) -> bool:
    """Publish agent action event to Kafka.

    Note:
        Consider using publish_action_event_from_config() with
        ModelActionEventConfig for better parameter organization.

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
    # ONEX: exempt - core implementation (config-based wrapper available)
    try:
        # Generate correlation ID if not provided
        correlation_id = str(uuid4()) if correlation_id is None else str(correlation_id)

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
            "timestamp": datetime.now(UTC).isoformat(),
        }

        # Remove None values to keep payload compact
        event = {k: v for k, v in event.items() if v is not None}

        # Build ONEX-compliant topic name
        topic_prefix = _get_kafka_topic_prefix()
        topic = build_topic(topic_prefix, TopicBase.AGENT_ACTION)

        # Get producer
        producer = await _get_kafka_producer()
        if producer is None:
            logger.warning("Kafka producer unavailable, action event not published")
            if PROMETHEUS_AVAILABLE:
                event_publish_counter.labels(topic=topic, status="unavailable").inc()
            return False

        # Publish to Kafka
        partition_key = correlation_id.encode("utf-8")

        # Track timing for Prometheus
        start_time = time.time()

        # Publish with timeout to prevent indefinite hanging
        await asyncio.wait_for(
            producer.send_and_wait(topic, value=event, key=partition_key),
            timeout=KAFKA_PUBLISH_TIMEOUT_SECONDS,
        )

        # Calculate metrics
        duration = time.time() - start_time
        event_bytes = len(json.dumps(event).encode("utf-8"))

        # Record Prometheus metrics
        if PROMETHEUS_AVAILABLE:
            record_event_publish(
                topic=topic,
                duration=duration,
                size_bytes=event_bytes,
                status="success",
            )

        logger.debug(
            f"Published action event: {action_type}/{action_name} "
            f"(agent={agent_name}, correlation_id={correlation_id})"
        )
        return True

    except TimeoutError:
        # Handle timeout specifically for better observability
        # Build topic name for error reporting (may fail if topic construction failed earlier)
        try:
            error_topic = build_topic(_get_kafka_topic_prefix(), TopicBase.AGENT_ACTION)
        except Exception:
            error_topic = TopicBase.AGENT_ACTION  # Fall back to base name

        logger.error(
            f"Timeout publishing action event to Kafka "
            f"(action_type={action_type}, action_name={action_name}, "
            f"timeout={KAFKA_PUBLISH_TIMEOUT_SECONDS}s)",
            extra={"correlation_id": correlation_id},
        )

        # Record failure in Prometheus
        if PROMETHEUS_AVAILABLE:
            event_publish_counter.labels(topic=error_topic, status="timeout").inc()
            event_publish_errors_counter.labels(
                topic=error_topic, error_type="TimeoutError"
            ).inc()

        return False

    except Exception as e:
        # Log error but don't fail - observability shouldn't break execution
        # Build topic name for error reporting (may fail if topic construction failed earlier)
        try:
            error_topic = build_topic(_get_kafka_topic_prefix(), TopicBase.AGENT_ACTION)
        except Exception:
            error_topic = TopicBase.AGENT_ACTION  # Fall back to base name

        logger.error(f"Failed to publish action event: {e}", exc_info=True)

        # Record failure in Prometheus
        if PROMETHEUS_AVAILABLE:
            event_publish_counter.labels(topic=error_topic, status="failure").inc()
            event_publish_errors_counter.labels(
                topic=error_topic, error_type=type(e).__name__
            ).inc()

        return False


async def publish_tool_call_from_config(
    config: ModelToolCallConfig,
) -> bool:
    """Publish tool call action event from config object.

    Args:
        config: Tool call configuration containing all event data.

    Returns:
        bool: True if published successfully.
    """
    action_details = {
        "tool_parameters": config.tool_parameters or {},
        "tool_result": config.tool_result or {},
        "success": config.success,
    }

    if config.error_message:
        action_details["error_message"] = config.error_message

    return await publish_action_event(
        agent_name=config.agent_name,
        action_type="tool_call",
        action_name=config.tool_name,
        action_details=action_details,
        correlation_id=config.correlation_id,
        duration_ms=config.duration_ms,
        project_path=config.project_path,
        project_name=config.project_name,
        working_directory=config.working_directory,
    )


async def publish_tool_call(
    agent_name: str,
    tool_name: str,
    tool_parameters: dict[str, Any] | None = None,
    tool_result: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    duration_ms: int | None = None,
    success: bool = True,
    error_message: str | None = None,
    **kwargs: Any,
) -> bool:
    """Publish tool call action event.

    Note:
        Consider using publish_tool_call_from_config() with
        ModelToolCallConfig for better parameter organization.

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
    # ONEX: exempt - convenience wrapper (config-based method available)
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
    decision_context: dict[str, Any] | None = None,
    decision_result: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    duration_ms: int | None = None,
    **kwargs: Any,
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
    error_context: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    **kwargs: Any,
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
    success_details: dict[str, Any] | None = None,
    correlation_id: str | UUID | None = None,
    duration_ms: int | None = None,
    **kwargs: Any,
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


async def close_producer() -> None:
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


def _cleanup_producer_sync() -> None:
    """
    Synchronous wrapper for close_producer() to be called by atexit.

    This ensures the Kafka producer is closed when the Python interpreter
    exits, preventing resource leak warnings.

    Note: This function attempts graceful cleanup, but if the event loop
    is already closed (e.g., after asyncio.run()), it will forcefully
    close the producer's client connection to avoid resource warnings.
    """
    global _kafka_producer
    if _kafka_producer is not None:
        try:
            # Try to get existing event loop
            try:
                loop = asyncio.get_running_loop()
                # Loop is running, can't cleanup synchronously
                # This will be handled by async cleanup
                return
            except RuntimeError:
                # No running loop, try to get the main event loop
                pass  # nosec B110 - Expected when no event loop running

            # Try to use existing event loop if available and not closed
            # Note: asyncio.get_event_loop() is deprecated since Python 3.10.
            # We can't use get_running_loop() here because this is sync code.
            # If no running loop exists, create a new one for cleanup.
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(close_producer())
                finally:
                    loop.close()
                return
            except RuntimeError:
                pass  # nosec B110 - Expected when event loop unavailable

            # Event loop is closed. The producer was created on a closed loop.
            # We can't use async cleanup properly.
            #
            # NOTE: We avoid accessing private attributes (like _client, _sender, _closed)
            # as these are internal implementation details of AIOKafkaProducer that may
            # change between versions. Instead, we use the producer's public stop() method
            # if a new event loop can be created, or simply clear our reference and let
            # Python's garbage collector handle cleanup.
            try:
                # Try creating a new event loop for cleanup (Python 3.10+ compatible)
                new_loop = asyncio.new_event_loop()
                try:
                    new_loop.run_until_complete(close_producer())
                finally:
                    new_loop.close()
                logger.debug("Kafka producer closed via new event loop")
            except Exception as loop_error:
                # If we can't create a new loop or cleanup fails,
                # clear our reference and let garbage collection handle it.
                # This may produce ResourceWarning on exit, but is safer than
                # accessing private internals of AIOKafkaProducer.
                logger.debug(
                    f"Could not create event loop for cleanup: {loop_error}. "
                    "Producer reference cleared; GC will handle cleanup."
                )
                _kafka_producer = None

        except Exception as e:
            # Best effort cleanup - don't raise on exit
            logger.debug(f"Error during atexit producer cleanup: {e}")
            # Ensure producer is cleared to avoid repeated cleanup attempts
            _kafka_producer = None


# Register cleanup on interpreter exit
atexit.register(_cleanup_producer_sync)


# Synchronous wrapper for backward compatibility
def publish_action_event_sync(
    agent_name: str, action_type: str, action_name: str, **kwargs: Any
) -> bool:
    """
    Synchronous wrapper for publish_action_event.

    Creates new event loop if needed. Use async version when possible.
    """
    # Note: asyncio.get_event_loop() is deprecated since Python 3.10.
    # Use get_running_loop() to check for existing loop, then create new if needed.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop - create a new one for sync execution
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
    async def test() -> None:
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

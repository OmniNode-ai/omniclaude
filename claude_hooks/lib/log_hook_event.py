#!/usr/bin/env python3
"""
Hook Event Logging Helper - Kafka-based Logging for Hook Execution

This module provides convenient functions for logging hook execution events
(invocation, routing decisions, errors) to Kafka using LoggingEventPublisher.

Key Features:
- Non-blocking async logging with fire-and-forget pattern
- Integration with LoggingEventPublisher for structured logging
- Correlation ID preservation through hook execution
- Performance-optimized (<50ms overhead target)
- Graceful degradation on Kafka failure

Event Types:
- Hook Invocation: Log when hook starts execution
- Routing Decision: Log agent selection and confidence
- Hook Error: Log failures during hook execution

Usage from hooks:
    # Log hook invocation
    python3 $HOOKS_LIB/log_hook_event.py invocation \
        --hook-name "UserPromptSubmit" \
        --prompt "Help me implement..." \
        --correlation-id "$CORRELATION_ID"

    # Log routing decision
    python3 $HOOKS_LIB/log_hook_event.py routing \
        --agent "$AGENT_NAME" \
        --confidence "$CONFIDENCE" \
        --method "$SELECTION_METHOD" \
        --correlation-id "$CORRELATION_ID"

    # Log hook error
    python3 $HOOKS_LIB/log_hook_event.py error \
        --hook-name "UserPromptSubmit" \
        --error-message "Agent detection failed" \
        --correlation-id "$CORRELATION_ID"

Usage from Python:
    from log_hook_event import log_hook_invocation, log_routing_decision, log_hook_error

    # Log invocation
    await log_hook_invocation(
        hook_name="UserPromptSubmit",
        prompt="Help me...",
        correlation_id="abc-123"
    )

Performance Characteristics:
- Publish time: <10ms p95
- Non-blocking: Never blocks hook execution
- Graceful degradation: Continues on Kafka failure

Created: 2025-11-14
Reference: LoggingEventPublisher in agents/lib/logging_event_publisher.py
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4


# Add project root to path for imports
# This script is in ~/.claude/hooks/lib/, need to find omniclaude repo
def find_omniclaude_root() -> Optional[Path]:
    """
    Find omniclaude repository root directory.

    Tries multiple strategies:
    1. OMNICLAUDE_ROOT environment variable
    2. PROJECT_ROOT environment variable (if points to omniclaude)
    3. Common locations (/Volumes/PRO-G40/Code/omniclaude, ~/Code/omniclaude)
    4. Traverse up from script location looking for agents/lib/logging_event_publisher.py

    Returns:
        Path to omniclaude root, or None if not found
    """
    # Try environment variables
    if omniclaude_root := os.environ.get("OMNICLAUDE_ROOT"):
        root = Path(omniclaude_root)
        if (
            root.exists()
            and (root / "agents" / "lib" / "logging_event_publisher.py").exists()
        ):
            return root

    if project_root := os.environ.get("PROJECT_ROOT"):
        root = Path(project_root)
        if (
            root.exists()
            and (root / "agents" / "lib" / "logging_event_publisher.py").exists()
        ):
            return root

    # Try common locations
    common_locations = [
        Path("/Volumes/PRO-G40/Code/omniclaude"),
        Path.home() / "Code" / "omniclaude",
        Path("/Users/jonah/Code/omniclaude"),
    ]

    for location in common_locations:
        if (
            location.exists()
            and (location / "agents" / "lib" / "logging_event_publisher.py").exists()
        ):
            return location

    # Try traversing up from script location
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "agents" / "lib" / "logging_event_publisher.py").exists():
            return parent

    return None


# Find omniclaude root and add to path
OMNICLAUDE_ROOT = find_omniclaude_root()
if OMNICLAUDE_ROOT is None:
    print(
        "Error: Could not find omniclaude repository root. "
        "Set OMNICLAUDE_ROOT environment variable or ensure script can find the repository.",
        file=sys.stderr,
    )
    sys.exit(1)

# Add both project root and agents/lib to path for imports
sys.path.insert(0, str(OMNICLAUDE_ROOT))  # For agents.lib.config imports
sys.path.insert(0, str(OMNICLAUDE_ROOT / "agents" / "lib"))  # For direct imports

from logging_event_publisher import LoggingEventPublisher, LogLevel


logger = logging.getLogger(__name__)


def get_correlation_id() -> str:
    """
    Get or generate correlation ID.

    Returns:
        Correlation ID string
    """
    # Try environment variable first (set by hooks)
    corr_id = os.environ.get("CORRELATION_ID")
    if corr_id:
        return corr_id

    # Generate new UUID
    return str(uuid4())


def get_hook_name() -> str:
    """
    Detect hook name from environment or context.

    Returns:
        Hook name string
    """
    # Try environment variable
    hook_name = os.environ.get("HOOK_NAME")
    if hook_name:
        return hook_name

    # Try to detect from script name
    try:
        script_name = Path(sys.argv[0]).stem
        if "hook" in script_name.lower():
            return script_name.replace("_", " ").title()
    except Exception:
        pass

    return "UnknownHook"


async def log_hook_invocation(
    hook_name: str,
    prompt: str,
    correlation_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Log hook invocation event.

    Args:
        hook_name: Name of hook being executed (e.g., "UserPromptSubmit")
        prompt: User prompt text (truncated to 500 chars for logging)
        correlation_id: Optional correlation ID for request tracing
        context: Optional additional context (project path, session ID, etc.)

    Returns:
        True if logged successfully, False otherwise

    Example:
        success = await log_hook_invocation(
            hook_name="UserPromptSubmit",
            prompt="Help me implement ONEX patterns",
            correlation_id="abc-123-def-456",
            context={"project_path": "/path/to/project"},
        )
    """
    correlation_id = correlation_id or get_correlation_id()

    # Truncate prompt for logging (avoid excessive size)
    prompt_truncated = prompt[:500] + "..." if len(prompt) > 500 else prompt

    # Build context
    log_context = context or {}
    log_context.update(
        {
            "prompt_length": len(prompt),
            "prompt_preview": prompt_truncated,
        }
    )

    try:
        publisher = LoggingEventPublisher(enable_events=True)
        await publisher.start()

        try:
            return await publisher.publish_application_log(
                service_name="omniclaude-hooks",
                instance_id=os.environ.get("HOSTNAME", "local"),
                level=LogLevel.INFO,
                logger_name=f"hook.{hook_name.lower().replace(' ', '_')}",
                message=f"Hook {hook_name} invoked",
                code="HOOK_INVOCATION",
                context=log_context,
                correlation_id=correlation_id,
            )
        finally:
            await publisher.stop()

    except Exception as e:
        logger.warning(f"Failed to log hook invocation: {e}")
        return False


async def log_routing_decision(
    agent_name: str,
    confidence: float,
    method: str,
    correlation_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    reasoning: Optional[str] = None,
    domain: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Log agent routing decision event.

    Args:
        agent_name: Name of selected agent
        confidence: Confidence score (0.0-1.0)
        method: Selection method (e.g., "event-based", "fallback")
        correlation_id: Optional correlation ID for request tracing
        latency_ms: Optional routing latency in milliseconds
        reasoning: Optional reasoning for selection
        domain: Optional agent domain
        context: Optional additional context

    Returns:
        True if logged successfully, False otherwise

    Example:
        success = await log_routing_decision(
            agent_name="polymorphic-agent",
            confidence=0.95,
            method="event-based",
            correlation_id="abc-123-def-456",
            latency_ms=12,
            reasoning="High confidence match for workflow coordination",
            domain="workflow_coordination",
        )
    """
    correlation_id = correlation_id or get_correlation_id()

    # Build context
    log_context = context or {}
    log_context.update(
        {
            "agent_name": agent_name,
            "confidence": confidence,
            "method": method,
        }
    )

    if latency_ms is not None:
        log_context["latency_ms"] = latency_ms

    if reasoning:
        log_context["reasoning"] = reasoning[:200]  # Truncate

    if domain:
        log_context["domain"] = domain

    try:
        publisher = LoggingEventPublisher(enable_events=True)
        await publisher.start()

        try:
            return await publisher.publish_application_log(
                service_name="omniclaude-hooks",
                instance_id=os.environ.get("HOSTNAME", "local"),
                level=LogLevel.INFO,
                logger_name="hook.routing",
                message=f"Agent selected: {agent_name} (confidence: {confidence:.2f})",
                code="ROUTING_DECISION",
                context=log_context,
                correlation_id=correlation_id,
            )
        finally:
            await publisher.stop()

    except Exception as e:
        logger.warning(f"Failed to log routing decision: {e}")
        return False


async def log_hook_error(
    hook_name: str,
    error_message: str,
    correlation_id: Optional[str] = None,
    error_type: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Log hook error event.

    Args:
        hook_name: Name of hook that encountered error
        error_message: Error message
        correlation_id: Optional correlation ID for request tracing
        error_type: Optional error type/category
        context: Optional additional context (stack trace, etc.)

    Returns:
        True if logged successfully, False otherwise

    Example:
        success = await log_hook_error(
            hook_name="UserPromptSubmit",
            error_message="Agent detection service unavailable",
            correlation_id="abc-123-def-456",
            error_type="ServiceUnavailable",
            context={"service": "event-based-routing"},
        )
    """
    correlation_id = correlation_id or get_correlation_id()

    # Build context
    log_context = context or {}
    log_context.update(
        {
            "hook_name": hook_name,
            "error_message": error_message,
        }
    )

    if error_type:
        log_context["error_type"] = error_type

    try:
        publisher = LoggingEventPublisher(enable_events=True)
        await publisher.start()

        try:
            return await publisher.publish_application_log(
                service_name="omniclaude-hooks",
                instance_id=os.environ.get("HOSTNAME", "local"),
                level=LogLevel.ERROR,
                logger_name=f"hook.{hook_name.lower().replace(' ', '_')}",
                message=f"Hook error: {error_message}",
                code="HOOK_ERROR",
                context=log_context,
                correlation_id=correlation_id,
            )
        finally:
            await publisher.stop()

    except Exception as e:
        logger.warning(f"Failed to log hook error: {e}")
        return False


def main():
    """
    Command-line interface for hook event logging.

    Usage:
        # Log invocation
        python3 log_hook_event.py invocation --hook-name UserPromptSubmit --prompt "..." --correlation-id "abc-123"

        # Log routing decision
        python3 log_hook_event.py routing --agent polymorphic-agent --confidence 0.95 --method event-based --correlation-id "abc-123"

        # Log error
        python3 log_hook_event.py error --hook-name UserPromptSubmit --error-message "Service unavailable" --correlation-id "abc-123"
    """
    parser = argparse.ArgumentParser(description="Log hook execution events to Kafka")
    subparsers = parser.add_subparsers(dest="command", help="Event type to log")

    # Invocation command
    invocation_parser = subparsers.add_parser("invocation", help="Log hook invocation")
    invocation_parser.add_argument("--hook-name", required=True, help="Name of hook")
    invocation_parser.add_argument("--prompt", required=True, help="User prompt text")
    invocation_parser.add_argument("--correlation-id", help="Optional correlation ID")
    invocation_parser.add_argument(
        "--context", help="Optional JSON context", default="{}"
    )

    # Routing command
    routing_parser = subparsers.add_parser("routing", help="Log routing decision")
    routing_parser.add_argument("--agent", required=True, help="Selected agent name")
    routing_parser.add_argument(
        "--confidence", type=float, required=True, help="Confidence score (0.0-1.0)"
    )
    routing_parser.add_argument("--method", required=True, help="Selection method")
    routing_parser.add_argument("--correlation-id", help="Optional correlation ID")
    routing_parser.add_argument(
        "--latency-ms", type=int, help="Optional routing latency in ms"
    )
    routing_parser.add_argument("--reasoning", help="Optional reasoning for selection")
    routing_parser.add_argument("--domain", help="Optional agent domain")
    routing_parser.add_argument("--context", help="Optional JSON context", default="{}")

    # Error command
    error_parser = subparsers.add_parser("error", help="Log hook error")
    error_parser.add_argument("--hook-name", required=True, help="Name of hook")
    error_parser.add_argument("--error-message", required=True, help="Error message")
    error_parser.add_argument("--correlation-id", help="Optional correlation ID")
    error_parser.add_argument("--error-type", help="Optional error type")
    error_parser.add_argument("--context", help="Optional JSON context", default="{}")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Parse context if provided
    try:
        context = json.loads(args.context) if hasattr(args, "context") else {}
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON context: {e}", file=sys.stderr)
        sys.exit(1)

    # Execute command
    try:
        if args.command == "invocation":
            success = asyncio.run(
                log_hook_invocation(
                    hook_name=args.hook_name,
                    prompt=args.prompt,
                    correlation_id=args.correlation_id,
                    context=context,
                )
            )
        elif args.command == "routing":
            success = asyncio.run(
                log_routing_decision(
                    agent_name=args.agent,
                    confidence=args.confidence,
                    method=args.method,
                    correlation_id=args.correlation_id,
                    latency_ms=args.latency_ms,
                    reasoning=args.reasoning,
                    domain=args.domain,
                    context=context,
                )
            )
        elif args.command == "error":
            success = asyncio.run(
                log_hook_error(
                    hook_name=args.hook_name,
                    error_message=args.error_message,
                    correlation_id=args.correlation_id,
                    error_type=args.error_type,
                    context=context,
                )
            )
        else:
            print(f"Error: Unknown command: {args.command}", file=sys.stderr)
            sys.exit(1)

        # Exit with success/failure code
        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"Error logging event: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Log Hook Event - CLI tool for logging hook events

Provides a command-line interface for logging various hook events
(invocation, routing, error) to the database.

Usage:
    python3 log_hook_event.py invocation --hook-name NAME --prompt PROMPT --correlation-id ID
    python3 log_hook_event.py routing --agent AGENT --confidence 0.95 --method fuzzy
    python3 log_hook_event.py error --hook-name NAME --error-message MSG --error-type TYPE
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Type


# Add script directory to path for sibling imports
# This enables imports like 'from hook_event_logger import ...' to work
# regardless of the current working directory
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import HookEventLogger with graceful fallback
_HookEventLoggerClass: Optional[Type[Any]] = None
try:
    from hook_event_logger import HookEventLogger

    _HookEventLoggerClass = HookEventLogger
except ImportError:
    _HookEventLoggerClass = None


logger = logging.getLogger(__name__)


def log_invocation(
    hook_name: str,
    prompt: str,
    correlation_id: str,
) -> Optional[str]:
    """Log hook invocation event."""
    try:
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        event_logger = _HookEventLoggerClass()
        return event_logger.log_event(
            source=hook_name,
            action="hook_invoked",
            resource="hook",
            resource_id=hook_name,
            payload={
                "prompt_preview": prompt[:200] if prompt else "",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            metadata={
                "hook_type": hook_name,
                "correlation_id": correlation_id,
            },
        )
    except Exception as e:
        logger.error(f"Failed to log invocation: {e}")
        return None


def log_routing(
    agent: str,
    confidence: float,
    method: str,
    correlation_id: str,
    latency_ms: int = 0,
    reasoning: str = "",
    domain: str = "general",
    context: Optional[str] = None,
) -> Optional[str]:
    """Log routing decision event."""
    try:
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        event_logger = _HookEventLoggerClass()

        payload = {
            "agent_name": agent,
            "confidence": confidence,
            "method": method,
            "latency_ms": latency_ms,
            "reasoning": reasoning,
            "domain": domain,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Parse context if provided
        if context:
            try:
                payload["context"] = json.loads(context)
            except json.JSONDecodeError:
                payload["context"] = {"raw": context}

        return event_logger.log_event(
            source="UserPromptSubmit",
            action="agent_routed",
            resource="routing",
            resource_id=agent,
            payload=payload,
            metadata={
                "hook_type": "UserPromptSubmit",
                "correlation_id": correlation_id,
                "agent_name": agent,
                "confidence": confidence,
            },
        )
    except Exception as e:
        logger.error(f"Failed to log routing: {e}")
        return None


def log_error(
    hook_name: str,
    error_message: str,
    error_type: str,
    correlation_id: str,
    context: Optional[str] = None,
) -> Optional[str]:
    """Log hook error event."""
    try:
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        event_logger = _HookEventLoggerClass()

        payload = {
            "error_message": error_message,
            "error_type": error_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if context:
            try:
                payload["context"] = json.loads(context)
            except json.JSONDecodeError:
                payload["context"] = {"raw": context}

        return event_logger.log_event(
            source=hook_name,
            action="error_occurred",
            resource="error",
            resource_id=error_type,
            payload=payload,
            metadata={
                "hook_type": hook_name,
                "correlation_id": correlation_id,
                "error_type": error_type,
            },
        )
    except Exception as e:
        logger.error(f"Failed to log error: {e}")
        return None


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Log hook events")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Invocation subcommand
    invoc_parser = subparsers.add_parser("invocation", help="Log hook invocation")
    invoc_parser.add_argument("--hook-name", required=True)
    invoc_parser.add_argument("--prompt", required=True)
    invoc_parser.add_argument("--correlation-id", required=True)

    # Routing subcommand
    route_parser = subparsers.add_parser("routing", help="Log routing decision")
    route_parser.add_argument("--agent", required=True)
    route_parser.add_argument("--confidence", type=float, required=True)
    route_parser.add_argument("--method", required=True)
    route_parser.add_argument("--correlation-id", required=True)
    route_parser.add_argument("--latency-ms", type=int, default=0)
    route_parser.add_argument("--reasoning", default="")
    route_parser.add_argument("--domain", default="general")
    route_parser.add_argument("--context")

    # Error subcommand
    error_parser = subparsers.add_parser("error", help="Log hook error")
    error_parser.add_argument("--hook-name", required=True)
    error_parser.add_argument("--error-message", required=True)
    error_parser.add_argument("--error-type", required=True)
    error_parser.add_argument("--correlation-id", required=True)
    error_parser.add_argument("--context")

    args = parser.parse_args()

    if args.command == "invocation":
        event_id = log_invocation(
            hook_name=args.hook_name,
            prompt=args.prompt,
            correlation_id=args.correlation_id,
        )
    elif args.command == "routing":
        event_id = log_routing(
            agent=args.agent,
            confidence=args.confidence,
            method=args.method,
            correlation_id=args.correlation_id,
            latency_ms=args.latency_ms,
            reasoning=args.reasoning,
            domain=args.domain,
            context=args.context,
        )
    elif args.command == "error":
        event_id = log_error(
            hook_name=args.hook_name,
            error_message=args.error_message,
            error_type=args.error_type,
            correlation_id=args.correlation_id,
            context=args.context,
        )
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        sys.exit(1)

    if event_id:
        print(f"Event logged: {event_id}")
        sys.exit(0)
    else:
        print("Failed to log event", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

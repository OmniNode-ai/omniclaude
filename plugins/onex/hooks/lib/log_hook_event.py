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
import re
import select
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
# This enables imports like 'from hook_event_logger import ...' to work
# regardless of the current working directory
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import HookEventLogger with graceful fallback
_HookEventLoggerClass: type[Any] | None = None
try:
    from hook_event_logger import HookEventLogger

    _HookEventLoggerClass = HookEventLogger
except ImportError:
    _HookEventLoggerClass = None


logger = logging.getLogger(__name__)

# Canonical routing path values - must match route_via_events_wrapper.py
VALID_ROUTING_PATHS = frozenset({"event", "local", "hybrid"})

# Secret patterns for prompt redaction - mirrors user-prompt-submit.sh patterns
_SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"AKIA[A-Z0-9]{16}"), "AKIA***REDACTED***"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "ghp_***REDACTED***"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "gho_***REDACTED***"),
    (re.compile(r"xox[baprs]-[a-zA-Z0-9-]+"), "xox*-***REDACTED***"),
    (re.compile(r"Bearer [a-zA-Z0-9._-]{20,}"), "Bearer ***REDACTED***"),
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
    ),
]


def _sanitize_prompt_preview(text: str, max_len: int = 200) -> str:
    """Truncate and redact secrets from a prompt before logging."""
    preview = text[:max_len] if text else ""
    for pattern, replacement in _SECRET_PATTERNS:
        preview = pattern.sub(replacement, preview)
    return preview


def _read_stdin_with_timeout(timeout_sec: float = 2.0) -> str:
    """Read stdin with a timeout to avoid blocking when no data is piped."""
    try:
        if select.select([sys.stdin], [], [], timeout_sec)[0]:
            return sys.stdin.read()
        logger.warning("Timed out waiting for prompt data on stdin")
    except (ValueError, OSError):
        # select() may fail if stdin is closed or invalid
        logger.warning("Cannot select on stdin, skipping read")
    return ""


def log_invocation(
    hook_name: str,
    prompt: str,
    correlation_id: str,
) -> str | None:
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
                "prompt_preview": _sanitize_prompt_preview(prompt),
                "timestamp": datetime.now(UTC).isoformat(),
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
    context: str | None = None,
    routing_path: str = "local",
) -> str | None:
    """Log routing decision event."""
    try:
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        # Validate routing_path - do not accept arbitrary values
        if routing_path not in VALID_ROUTING_PATHS:
            logger.warning(
                f"Invalid routing_path '{routing_path}' received - coercing to 'local'. "
                f"Valid values: {VALID_ROUTING_PATHS}. This indicates instrumentation drift."
            )
            routing_path = "local"

        event_logger = _HookEventLoggerClass()

        payload = {
            "agent_name": agent,
            "confidence": confidence,
            "method": method,
            "routing_path": routing_path,
            "latency_ms": latency_ms,
            "reasoning": reasoning,
            "domain": domain,
            "timestamp": datetime.now(UTC).isoformat(),
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
                "routing_path": routing_path,
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
    context: str | None = None,
) -> str | None:
    """Log hook error event."""
    try:
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        event_logger = _HookEventLoggerClass()

        payload = {
            "error_message": error_message,
            "error_type": error_type,
            "timestamp": datetime.now(UTC).isoformat(),
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
    invoc_parser.add_argument("--prompt", required=False, default=None)
    invoc_parser.add_argument(
        "--prompt-stdin",
        action="store_true",
        help="Read prompt from stdin (avoids exposing prompt in process table)",
    )
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
    route_parser.add_argument("--routing-path", default="local")

    # Error subcommand
    error_parser = subparsers.add_parser("error", help="Log hook error")
    error_parser.add_argument("--hook-name", required=True)
    error_parser.add_argument("--error-message", required=True)
    error_parser.add_argument("--error-type", required=True)
    error_parser.add_argument("--correlation-id", required=True)
    error_parser.add_argument("--context")

    args = parser.parse_args()

    # Validate JSON context early if provided (defense in depth)
    if hasattr(args, "context") and args.context is not None:
        try:
            json.loads(args.context)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(
                f"Malformed JSON in --context ({e}), will be treated as raw string"
            )

    if args.command == "invocation":
        # Read prompt from stdin only when --prompt-stdin is explicitly set.
        # Use timeout to prevent blocking if no data is piped.
        prompt = args.prompt
        if getattr(args, "prompt_stdin", False):
            prompt = _read_stdin_with_timeout(timeout_sec=2.0)
        elif prompt is None:
            prompt = ""
        event_id = log_invocation(
            hook_name=args.hook_name,
            prompt=prompt,
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
            routing_path=args.routing_path,
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
        sys.exit(0)

    if event_id:
        print(f"Event logged: {event_id}")
    else:
        # Non-fatal: hook logging failures must not propagate errors
        print("Failed to log event (non-fatal)", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        # Normalize non-zero exits (e.g. argparse error code 2) to 0.
        # Hook logging is best-effort; failures must not block Claude Code.
        sys.exit(0)
    except Exception as e:
        # Graceful degradation: emit diagnostic and exit cleanly
        print(f"log_hook_event: unhandled error: {e}", file=sys.stderr)
        sys.exit(0)

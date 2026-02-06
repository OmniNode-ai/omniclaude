#!/usr/bin/env python3
"""
Route Via Events Wrapper - Synchronous wrapper for event-based routing

Provides a synchronous CLI interface for the event-based agent routing system.
Publishes routing requests to Kafka and waits for responses.

Usage:
    python3 route_via_events_wrapper.py "user prompt" "correlation-id"

Output:
    JSON object with routing decision:
    {
        "selected_agent": "agent-name",
        "confidence": 0.95,
        "reasoning": "...",
        "method": "event_based",
        "latency_ms": 45,
        "domain": "general",
        "purpose": "..."
    }
"""

import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
# This enables imports like 'from hook_event_adapter import ...' to work
# regardless of the current working directory
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import hook_event_adapter with graceful fallback
_get_hook_event_adapter: Callable[[], Any] | None = None
try:
    from hook_event_adapter import get_hook_event_adapter

    _get_hook_event_adapter = get_hook_event_adapter
except ImportError:
    _get_hook_event_adapter = None

# Import emit_event and secret redactor for routing decision emission.
# Uses __package__ check for proper import resolution instead of
# fragile string-based error detection on ImportError messages.
_emit_event_fn: Callable[..., bool] | None = None
_redact_secrets_fn: Callable[[str], str] | None = None

try:
    if __package__:
        from .emit_client_wrapper import emit_event as _emit_event_fn
        from .secret_redactor import redact_secrets as _redact_secrets_fn
    else:
        from emit_client_wrapper import (
            emit_event as _emit_event_fn,  # type: ignore[no-redef]
        )
        from secret_redactor import (
            redact_secrets as _redact_secrets_fn,  # type: ignore[no-redef]
        )
except ImportError:
    _emit_event_fn = None
    _redact_secrets_fn = None


logger = logging.getLogger(__name__)

# Canonical routing path values for metrics
VALID_ROUTING_PATHS = frozenset({"event", "local", "hybrid"})


def _compute_routing_path(method: str, event_attempted: bool) -> str:
    """
    Map method to canonical routing_path.

    Logic:
    - event_attempted=False → "local" (never tried event path)
    - event_attempted=True AND method=event_based → "event"
    - event_attempted=True AND method=fallback → "hybrid" (tried event, fell back)
    - Unknown method → "local" with loud warning

    Args:
        method: The routing method used (event_based, fallback, etc.)
        event_attempted: Whether event-based routing was attempted

    Returns:
        Canonical routing path: "event", "local", or "hybrid"
    """
    if not event_attempted:
        return "local"

    if method == "event_based":
        return "event"
    elif method == "fallback":
        return "hybrid"  # Attempted event, but fell back
    else:
        # Unknown method - log loudly, do NOT silently accept
        logger.warning(
            f"Unknown routing method '{method}' - forcing routing_path='local'. "
            "This indicates instrumentation drift."
        )
        return "local"


def _sanitize_prompt_preview(prompt: str, max_length: int = 100) -> str:
    """Create a sanitized, truncated prompt preview.

    Truncates to max_length and redacts any secrets using the
    existing secret_redactor module.

    Args:
        prompt: Raw user prompt text.
        max_length: Maximum length for the preview.

    Returns:
        Sanitized and truncated prompt preview.
    """
    preview = prompt[:max_length] if prompt else ""
    if _redact_secrets_fn is not None:
        preview = _redact_secrets_fn(preview)
    return preview


def _emit_routing_decision(
    result: dict[str, Any],
    prompt: str,
    correlation_id: str,
) -> None:
    """Emit routing decision event via the emit daemon.

    Non-blocking: logs at debug level on failure but never raises.
    Uses emit_event(event_type, payload) with correct argument order.

    The event type ``routing.decision`` follows the daemon's semantic naming
    convention (``{domain}.{action}``). The daemon's EventRegistry maps this
    to the appropriate Kafka topic following ONEX canonical format:
    ``onex.evt.omniclaude.routing-decision.v1``.

    Args:
        result: Routing decision result dictionary.
        prompt: Original user prompt (will be sanitized before emission).
        correlation_id: Correlation ID for tracking.
    """
    if _emit_event_fn is None:
        logger.debug("emit_event not available, skipping routing decision emission")
        return

    try:
        payload: dict[str, object] = {
            "correlation_id": correlation_id,
            "selected_agent": result.get("selected_agent", "polymorphic-agent"),
            "confidence": result.get("confidence", 0.5),
            "method": result.get("method", "fallback"),
            "routing_path": result.get("routing_path", "local"),
            "latency_ms": result.get("latency_ms", 0),
            "domain": result.get("domain", ""),
            "reasoning": result.get("reasoning", ""),
            "prompt_preview": _sanitize_prompt_preview(prompt),
            "event_attempted": result.get("event_attempted", False),
        }

        # Correct argument order: emit_event(event_type, payload)
        _emit_event_fn("routing.decision", payload)
    except Exception as e:
        # Non-blocking: routing emission failure must not break routing
        logger.debug("Failed to emit routing decision: %s", e)


def route_via_events(
    prompt: str,
    correlation_id: str,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """
    Route user prompt via event-based routing system.

    Args:
        prompt: User prompt to route
        correlation_id: Correlation ID for tracking
        timeout_ms: Timeout in milliseconds

    Returns:
        Routing decision dictionary with routing_path signal
    """
    start_time = time.time()
    event_attempted = False

    # Validate inputs before processing
    if not isinstance(prompt, str) or not prompt.strip():
        logger.warning("Invalid or empty prompt received, using fallback")
        return {
            "selected_agent": "polymorphic-agent",
            "confidence": 0.5,
            "reasoning": "Invalid input - empty or non-string prompt",
            "method": "fallback",
            "latency_ms": 0,
            "domain": "workflow_coordination",
            "purpose": "Intelligent coordinator for development workflows",
            "event_attempted": False,
            "routing_path": "local",
        }

    if not isinstance(correlation_id, str) or not correlation_id.strip():
        logger.warning("Invalid or empty correlation_id, using fallback")
        return {
            "selected_agent": "polymorphic-agent",
            "confidence": 0.5,
            "reasoning": "Invalid input - empty or non-string correlation_id",
            "method": "fallback",
            "latency_ms": 0,
            "domain": "workflow_coordination",
            "purpose": "Intelligent coordinator for development workflows",
            "event_attempted": False,
            "routing_path": "local",
        }

    try:
        # Check if adapter is available (pre-imported at module level)
        if _get_hook_event_adapter is None:
            logger.warning(
                "Event routing not available: hook_event_adapter import failed"
            )
            # event_attempted stays False - adapter never available
        else:
            adapter = _get_hook_event_adapter()

            # Publish routing request and wait for response
            # Note: This is a simplified implementation
            # Full implementation would use Kafka request-response pattern

            # For now, use the adapter's routing capability if available
            if hasattr(adapter, "route_request"):
                event_attempted = True  # We're about to try event routing
                result = adapter.route_request(
                    prompt=prompt,
                    correlation_id=correlation_id,
                    timeout_ms=timeout_ms,
                )
                if result:
                    latency_ms = int((time.time() - start_time) * 1000)
                    method = "event_based"
                    result["latency_ms"] = latency_ms
                    result["method"] = method
                    result["event_attempted"] = True
                    result["routing_path"] = _compute_routing_path(method, True)
                    _emit_routing_decision(result, prompt, correlation_id)
                    return result

    except Exception as e:
        logger.warning(
            f"Event routing failed with {type(e).__name__}: {e}. "
            f"event_attempted={event_attempted}"
        )
        # event_attempted is True if we got past the adapter check

    # Fallback: Return polymorphic-agent as default
    latency_ms = int((time.time() - start_time) * 1000)
    method = "fallback"
    routing_path = _compute_routing_path(method, event_attempted)

    result = {
        "selected_agent": "polymorphic-agent",
        "confidence": 0.5,
        "reasoning": "Event-based routing unavailable - using default agent",
        "method": method,
        "latency_ms": latency_ms,
        "domain": "workflow_coordination",
        "purpose": "Intelligent coordinator for development workflows",
        "event_attempted": event_attempted,
        "routing_path": routing_path,
    }
    _emit_routing_decision(result, prompt, correlation_id)
    return result


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
        # Missing args - never attempted event routing
        print(
            json.dumps(
                {
                    "selected_agent": "polymorphic-agent",
                    "confidence": 0.5,
                    "reasoning": "Missing arguments - using fallback",
                    "method": "fallback",
                    "latency_ms": 0,
                    "domain": "workflow_coordination",
                    "purpose": "Intelligent coordinator for development workflows",
                    "event_attempted": False,
                    "routing_path": "local",
                }
            )
        )
        sys.exit(0)

    prompt = sys.argv[1]
    correlation_id = sys.argv[2]
    timeout_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 5000

    result = route_via_events(prompt, correlation_id, timeout_ms)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

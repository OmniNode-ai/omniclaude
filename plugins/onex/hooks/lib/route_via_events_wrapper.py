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


logger = logging.getLogger(__name__)


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
        Routing decision dictionary
    """
    start_time = time.time()

    try:
        # Check if adapter is available (pre-imported at module level)
        if _get_hook_event_adapter is None:
            logger.warning("Event routing not available: hook_event_adapter import failed")
        else:
            adapter = _get_hook_event_adapter()

            # Publish routing request and wait for response
            # Note: This is a simplified implementation
            # Full implementation would use Kafka request-response pattern

            # For now, use the adapter's routing capability if available
            if hasattr(adapter, "route_request"):
                result = adapter.route_request(
                    prompt=prompt,
                    correlation_id=correlation_id,
                    timeout_ms=timeout_ms,
                )
                if result:
                    latency_ms = int((time.time() - start_time) * 1000)
                    result["latency_ms"] = latency_ms
                    result["method"] = "event_based"
                    return result

    except Exception as e:
        logger.error(f"Event routing failed: {e}")

    # Fallback: Return polymorphic-agent as default
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "selected_agent": "polymorphic-agent",
        "confidence": 0.5,
        "reasoning": "Event-based routing unavailable - using default agent",
        "method": "fallback",
        "latency_ms": latency_ms,
        "domain": "workflow_coordination",
        "purpose": "Intelligent coordinator for development workflows",
    }


def main():
    """CLI entry point."""
    if len(sys.argv) < 3:
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

#!/usr/bin/env python3
"""
Route Via Events Wrapper - Polly-First Agent Routing

Implements the Polly-first routing architecture where the polymorphic agent
(Polly) is the intentional default for all requests. This is NOT a fallback -
it's the primary routing strategy.

Routing Semantics (three distinct fields):
- routing_method: HOW routing executed (event_based, local, fallback)
- routing_policy: WHY this path was chosen (polly_first, safety_gate, cost_gate)
- routing_path: WHAT canonical outcome (event, local, hybrid)

Usage:
    python3 route_via_events_wrapper.py "user prompt" "correlation-id"

Output:
    JSON object with routing decision:
    {
        "selected_agent": "polymorphic-agent",
        "confidence": 0.95,
        "reasoning": "Polly-first routing: intelligent coordinator handles all requests",
        "routing_method": "local",
        "routing_policy": "polly_first",
        "routing_path": "local",
        "latency_ms": 2,
        "domain": "workflow_coordination",
        "purpose": "Intelligent coordinator for development workflows"
    }
"""

import json
import logging
import sys
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

# Add script directory to path for sibling imports
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

logger = logging.getLogger(__name__)


class RoutingMethod(str, Enum):
    """HOW the routing decision was made."""

    EVENT_BASED = "event_based"  # Via Kafka request-response
    LOCAL = "local"  # Local decision without external service
    FALLBACK = "fallback"  # Error recovery path


class RoutingPolicy(str, Enum):
    """WHY this routing path was chosen."""

    POLLY_FIRST = "polly_first"  # Intentional Polly-first architecture
    SAFETY_GATE = "safety_gate"  # Safety/compliance routing
    COST_GATE = "cost_gate"  # Cost optimization routing
    EXPLICIT_AGENT = "explicit_agent"  # User explicitly requested an agent


class RoutingPath(str, Enum):
    """WHAT canonical routing outcome."""

    EVENT = "event"  # Event-based routing used
    LOCAL = "local"  # Local routing used
    HYBRID = "hybrid"  # Combination of approaches


# Import emit_client_wrapper for event emission (optional)
_emit_routing_event: Callable[..., bool] | None = None
try:
    from emit_client_wrapper import emit_via_daemon

    _emit_routing_event = emit_via_daemon
except ImportError:
    logger.debug(
        "emit_client_wrapper not available, routing events will not be emitted"
    )

# Import cohort assignment for A/B testing tracking (optional)
_assign_cohort: Callable[..., Any] | None = None
_EnumCohort: type | None = None
try:
    # Add src to path for omniclaude imports (sys and Path already imported above)
    _src_dir = Path(__file__).parent.parent.parent.parent.parent / "src"
    if str(_src_dir) not in sys.path:
        sys.path.insert(0, str(_src_dir))

    from omniclaude.hooks.cohort_assignment import EnumCohort, assign_cohort

    _assign_cohort = assign_cohort
    _EnumCohort = EnumCohort
except ImportError:
    logger.debug("cohort_assignment not available, A/B testing will not be tracked")


def _emit_routing_decision(
    correlation_id: str,
    selected_agent: str,
    confidence: float,
    routing_method: str,
    routing_policy: str,
    routing_path: str,
    latency_ms: int,
    prompt_preview: str,
    cohort: str | None = None,
    cohort_seed: int | None = None,
) -> None:
    """
    Emit routing decision event for observability.

    Non-blocking, best-effort - failures are logged but don't affect routing.
    Includes A/B testing cohort assignment for experiment tracking.
    """
    if _emit_routing_event is None:
        return

    try:
        event = {
            "event_type": "routing.decision",
            "correlation_id": correlation_id,
            "selected_agent": selected_agent,
            "confidence": confidence,
            "routing_method": routing_method,
            "routing_policy": routing_policy,
            "routing_path": routing_path,
            "latency_ms": latency_ms,
            "prompt_preview": prompt_preview[:100] if prompt_preview else "",
            # A/B testing cohort tracking
            "cohort": cohort,
            "cohort_seed": cohort_seed,
        }
        # Remove None values
        event = {k: v for k, v in event.items() if v is not None}
        # Fire-and-forget - emit_via_daemon is non-blocking
        _emit_routing_event(json.dumps(event), "routing-decisions")
    except Exception as e:
        # Log but don't fail - observability is best-effort
        logger.debug(f"Failed to emit routing decision event: {e}")


def route_via_events(
    prompt: str,
    correlation_id: str,
    timeout_ms: int = 5000,
    session_id: str | None = None,
) -> dict[str, Any]:
    """
    Route user prompt using Polly-first architecture.

    The polymorphic agent (Polly) is the INTENTIONAL default for all requests.
    This is the primary routing strategy, not a fallback.

    Polly-first benefits:
    - Single point of coordination for all workflows
    - Dynamic transformation to specialized agents when needed
    - Consistent observability and action logging
    - Transformation validation prevents routing bypasses

    Args:
        prompt: User prompt to route
        correlation_id: Correlation ID for tracking
        timeout_ms: Timeout in milliseconds (reserved for future event-based routing)
        session_id: Session ID for A/B cohort assignment (optional)

    Returns:
        Routing decision dictionary with semantic routing fields
    """
    start_time = time.time()

    # A/B testing cohort assignment (for experiment tracking)
    cohort: str | None = None
    cohort_seed: int | None = None
    if _assign_cohort is not None and session_id:
        try:
            assignment = _assign_cohort(session_id)
            cohort = assignment.cohort.value
            cohort_seed = assignment.assignment_seed
        except Exception as e:
            logger.debug(f"Cohort assignment failed: {e}")

    # Polly-first: Always route to polymorphic-agent with high confidence
    # This is INTENTIONAL, not a fallback
    latency_ms = int((time.time() - start_time) * 1000)

    result: dict[str, Any] = {
        "selected_agent": "polymorphic-agent",
        "confidence": 0.95,
        "reasoning": "Polly-first routing: intelligent coordinator handles all requests",
        # Routing semantics - three distinct fields
        "routing_method": RoutingMethod.LOCAL.value,
        "routing_policy": RoutingPolicy.POLLY_FIRST.value,
        "routing_path": RoutingPath.LOCAL.value,
        # Legacy field for backward compatibility
        "method": RoutingPolicy.POLLY_FIRST.value,
        # Performance tracking
        "latency_ms": latency_ms,
        # Agent metadata
        "domain": "workflow_coordination",
        "purpose": "Intelligent coordinator for development workflows",
    }

    # Add cohort information if available (for A/B testing)
    if cohort is not None:
        result["cohort"] = cohort
        result["cohort_seed"] = cohort_seed

    # Emit routing decision event for observability (non-blocking)
    _emit_routing_decision(
        correlation_id=correlation_id,
        selected_agent=result["selected_agent"],
        confidence=result["confidence"],
        routing_method=result["routing_method"],
        routing_policy=result["routing_policy"],
        routing_path=result["routing_path"],
        latency_ms=latency_ms,
        prompt_preview=prompt,
        cohort=cohort,
        cohort_seed=cohort_seed,
    )

    return result


def main() -> None:
    """CLI entry point.

    Usage:
        python route_via_events_wrapper.py "prompt" "correlation-id" [timeout_ms] [session_id]
    """
    if len(sys.argv) < 3:
        # Still use Polly-first even with missing args (graceful degradation)
        print(
            json.dumps(
                {
                    "selected_agent": "polymorphic-agent",
                    "confidence": 0.95,
                    "reasoning": "Polly-first routing (missing args, using defaults)",
                    "routing_method": RoutingMethod.LOCAL.value,
                    "routing_policy": RoutingPolicy.POLLY_FIRST.value,
                    "routing_path": RoutingPath.LOCAL.value,
                    "method": RoutingPolicy.POLLY_FIRST.value,
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
    session_id = sys.argv[4] if len(sys.argv) > 4 else None

    result = route_via_events(prompt, correlation_id, timeout_ms, session_id)
    print(json.dumps(result))


if __name__ == "__main__":
    main()

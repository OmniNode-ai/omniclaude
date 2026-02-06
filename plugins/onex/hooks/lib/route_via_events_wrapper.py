#!/usr/bin/env python3
"""
Route Via Events Wrapper - Intelligent Agent Routing

Routes user prompts to the best-matched agent using trigger matching and
confidence scoring. Falls back to polymorphic-agent only when no good match
is found (confidence below threshold).

Routing Semantics (three distinct fields):
- routing_method: HOW routing executed (event_based, local, fallback)
- routing_policy: WHY this path was chosen (trigger_match, explicit_request, fallback_default)
- routing_path: WHAT canonical outcome (event, local, hybrid)

Usage:
    python3 route_via_events_wrapper.py "user prompt" "correlation-id"

Output:
    JSON object with routing decision:
    {
        "selected_agent": "agent-debug",
        "confidence": 0.85,
        "candidates": [
            {"name": "agent-debug", "score": 0.85, "description": "Debug agent", "reason": "Exact match: 'debug'"},
            {"name": "agent-testing", "score": 0.60, "description": "Testing agent", "reason": "Fuzzy match: 'test'"}
        ],
        "reasoning": "Strong trigger match: 'debug'",
        "routing_method": "local",
        "routing_policy": "trigger_match",
        "routing_path": "local",
        "latency_ms": 15,
        "domain": "debugging",
        "purpose": "Debug and troubleshoot issues"
    }

    The `candidates` array contains the top N agent matches sorted by score
    descending, allowing downstream consumers (e.g., Claude) to make the final
    semantic selection. Each candidate includes name, score, description, and
    match reason. The array is empty when no router is available or routing fails.
"""

import json
import logging
import sys
import threading
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

# Canonical routing path values for metrics (from OMN-1893)
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


class RoutingMethod(str, Enum):
    """HOW the routing decision was made."""

    EVENT_BASED = "event_based"  # Via Kafka request-response
    LOCAL = "local"  # Local decision without external service
    FALLBACK = "fallback"  # Error recovery path


class RoutingPolicy(str, Enum):
    """WHY this routing path was chosen."""

    TRIGGER_MATCH = "trigger_match"  # Matched based on activation triggers
    EXPLICIT_REQUEST = "explicit_request"  # User explicitly requested an agent
    FALLBACK_DEFAULT = "fallback_default"  # No good match, using default agent
    SAFETY_GATE = "safety_gate"  # Safety/compliance routing
    COST_GATE = "cost_gate"  # Cost optimization routing


class RoutingPath(str, Enum):
    """WHAT canonical routing outcome."""

    EVENT = "event"  # Event-based routing used
    LOCAL = "local"  # Local routing used
    HYBRID = "hybrid"  # Combination of approaches


# Import emit_client_wrapper for event emission (optional)
_emit_routing_event: Callable[..., bool] | None = None
try:
    from emit_client_wrapper import emit_event

    _emit_routing_event = emit_event
except ImportError:
    logger.debug(
        "emit_client_wrapper not available, routing events will not be emitted"
    )

# Import secret redaction for prompt_preview sanitization (optional)
_redact_secrets: Callable[[str], str] | None = None
try:
    from secret_redactor import redact_secrets

    _redact_secrets = redact_secrets
except ImportError:
    logger.debug("secret_redactor not available, prompt_preview will not be sanitized")

# Import cohort assignment for A/B testing tracking (optional)
_assign_cohort: Callable[..., Any] | None = None
try:
    # Find project root by searching for pyproject.toml (more robust than counting parents)
    _current = Path(__file__).resolve()
    _project_root: Path | None = None
    for _parent in [_current] + list(_current.parents):
        if (_parent / "pyproject.toml").exists():
            _project_root = _parent
            break

    if _project_root is not None:
        _src_dir = _project_root / "src"
        if _src_dir.exists() and str(_src_dir) not in sys.path:
            sys.path.insert(0, str(_src_dir))

    from omniclaude.hooks.cohort_assignment import assign_cohort

    _assign_cohort = assign_cohort
except ImportError:
    logger.debug("cohort_assignment not available, A/B testing will not be tracked")

# Import AgentRouter for intelligent routing
_AgentRouter: type | None = None
_router_instance: Any = None
_router_lock = threading.Lock()
try:
    from agent_router import AgentRouter

    _AgentRouter = AgentRouter
except ImportError:
    logger.debug("agent_router not available, will use fallback routing")


# Confidence threshold for accepting a routed agent
# Below this threshold, we fall back to polymorphic-agent
CONFIDENCE_THRESHOLD = 0.5

# Default fallback agent when no good match is found
DEFAULT_AGENT = "polymorphic-agent"


def _get_router() -> Any:
    """
    Get or create the singleton AgentRouter instance.

    Uses double-checked locking for thread safety.

    Returns:
        AgentRouter instance or None if unavailable
    """
    global _router_instance
    if _router_instance is not None:
        return _router_instance
    if _AgentRouter is None:
        return None
    with _router_lock:
        # Double-check after acquiring lock
        if _router_instance is not None:
            return _router_instance
        try:
            _router_instance = _AgentRouter()
            logger.info(
                f"AgentRouter initialized with {len(_router_instance.registry.get('agents', {}))} agents"
            )
        except Exception as e:
            logger.warning(f"Failed to initialize AgentRouter: {e}")
            return None
    return _router_instance


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
        # Sanitize prompt_preview before emission to redact secrets
        sanitized_preview = ""
        if prompt_preview:
            sanitized = (
                _redact_secrets(prompt_preview) if _redact_secrets else prompt_preview
            )
            sanitized_preview = sanitized[:100]

        event = {
            "event_type": "routing.decision",
            "correlation_id": correlation_id,
            "selected_agent": selected_agent,
            "confidence": confidence,
            "routing_method": routing_method,
            "routing_policy": routing_policy,
            "routing_path": routing_path,
            "latency_ms": latency_ms,
            "prompt_preview": sanitized_preview,
            # A/B testing cohort tracking
            "cohort": cohort,
            "cohort_seed": cohort_seed,
        }
        # Remove None values
        event = {k: v for k, v in event.items() if v is not None}
        # Fire-and-forget - emit_event is non-blocking
        _emit_routing_event("routing.decision", event)
    except Exception as e:
        # Log but don't fail - observability is best-effort
        logger.debug(f"Failed to emit routing decision event: {e}")


def route_via_events(
    prompt: str,
    correlation_id: str,
    timeout_ms: int = 5000,  # noqa: ARG001 - Reserved for future event-based routing
    session_id: str | None = None,
    user_id: str | None = None,
    repo_path: str | None = None,
) -> dict[str, Any]:
    """
    Route user prompt using intelligent trigger matching and confidence scoring.

    Uses AgentRouter to analyze the prompt and match against agent activation
    triggers. Falls back to polymorphic-agent only when no good match is found
    (confidence below threshold).

    Args:
        prompt: User prompt to route
        correlation_id: Correlation ID for tracking
        timeout_ms: **Reserved for future use - currently ignored.**
            This parameter is accepted for API compatibility but not used.
            When event-based routing is implemented, this will control the
            timeout for the request-response cycle.
        session_id: Session ID for A/B cohort assignment (optional)
        user_id: User ID for sticky cohort assignment across sessions (optional)
        repo_path: Repository path for repo-level cohort stickiness (optional)

    Returns:
        Routing decision dictionary with routing_path signal

    Note:
        Cohort assignment priority: user_id > repo_path > session_id
        Using user_id or repo_path provides stickier cohort assignment that
        persists across sessions.
    """
    start_time = time.time()
    event_attempted = False  # Local routing, no event bus

    # A/B testing cohort assignment (for experiment tracking)
    # Priority: user_id > repo_path > session_id for stickier assignment
    cohort: str | None = None
    cohort_seed: int | None = None
    identity_type: str | None = None
    if _assign_cohort is not None and session_id:
        try:
            assignment = _assign_cohort(
                session_id, user_id=user_id, repo_path=repo_path
            )
            cohort = assignment.cohort.value
            cohort_seed = assignment.assignment_seed
            identity_type = assignment.identity_type.value
        except Exception as e:
            logger.debug(f"Cohort assignment failed: {e}")

    # Build context for routing
    context: dict[str, Any] = {}
    if repo_path:
        context["repo_path"] = repo_path

    # Attempt intelligent routing via AgentRouter
    router = _get_router()
    selected_agent = DEFAULT_AGENT
    confidence = 0.5
    reasoning = "Fallback: no router available"
    routing_policy = RoutingPolicy.FALLBACK_DEFAULT
    domain = "workflow_coordination"
    purpose = "Intelligent coordinator for development workflows"

    # Candidates list populated from all router recommendations
    candidates_list: list[dict[str, Any]] = []

    if router is not None:
        try:
            recommendations = router.route(prompt, context, max_recommendations=5)

            if recommendations:
                # Build candidates from ALL recommendations (sorted by score descending)
                agents_registry = router.registry.get("agents", {})
                for rec in recommendations:
                    rec_agent_data = agents_registry.get(rec.agent_name, {})
                    candidates_list.append(
                        {
                            "name": rec.agent_name,
                            "score": rec.confidence.total,
                            "description": rec_agent_data.get(
                                "description", rec.agent_title
                            ),
                            "reason": rec.reason,
                        }
                    )

                top_rec = recommendations[0]
                top_confidence = top_rec.confidence.total

                if top_confidence >= CONFIDENCE_THRESHOLD:
                    # Good match found - use the recommended agent
                    selected_agent = top_rec.agent_name
                    confidence = top_confidence
                    reasoning = f"{top_rec.reason} - {top_rec.confidence.explanation}"
                    routing_policy = RoutingPolicy.TRIGGER_MATCH

                    # Extract domain from agent data if available
                    agent_data = agents_registry.get(selected_agent, {})
                    domain = agent_data.get("domain_context", "general")
                    purpose = agent_data.get("description", top_rec.agent_title)

                    # Check if this was an explicit request
                    if getattr(top_rec, "is_explicit", False):
                        routing_policy = RoutingPolicy.EXPLICIT_REQUEST

                    logger.info(
                        f"Routed to {selected_agent} (confidence={confidence:.2f}): {reasoning}"
                    )
                else:
                    # Low confidence - fall back to polymorphic-agent
                    reasoning = (
                        f"Low confidence ({top_confidence:.2f} < {CONFIDENCE_THRESHOLD}), "
                        f"best match was {top_rec.agent_name}"
                    )
                    logger.debug(f"Falling back to {DEFAULT_AGENT}: {reasoning}")
            else:
                # No matches found
                reasoning = "No trigger matches found in prompt"
                logger.debug(f"No matches, using {DEFAULT_AGENT}")

        except Exception as e:
            # Router error - fall back gracefully
            candidates_list = []
            reasoning = f"Routing error: {type(e).__name__}"
            logger.warning(f"AgentRouter error: {e}")

    latency_ms = int((time.time() - start_time) * 1000)

    # Compute routing_path using the helper (for consistency with observability)
    routing_path = _compute_routing_path(RoutingMethod.LOCAL.value, event_attempted)

    result: dict[str, Any] = {
        "selected_agent": selected_agent,
        "confidence": confidence,
        "candidates": candidates_list,
        "reasoning": reasoning,
        # Routing semantics - three distinct fields
        "routing_method": RoutingMethod.LOCAL.value,
        "routing_policy": routing_policy.value,
        "routing_path": routing_path,
        # Legacy field for backward compatibility
        "method": routing_policy.value,
        # Performance tracking
        "latency_ms": latency_ms,
        # Agent metadata
        "domain": domain,
        "purpose": purpose,
        # Observability signal (from OMN-1893)
        "event_attempted": event_attempted,
    }

    # Add cohort information if available (for A/B testing)
    if cohort is not None:
        result["cohort"] = cohort
        result["cohort_seed"] = cohort_seed
        if identity_type is not None:
            result["cohort_identity_type"] = identity_type

    # Emit routing decision event for observability (non-blocking)
    _emit_routing_decision(
        correlation_id=correlation_id,
        selected_agent=result["selected_agent"],
        confidence=result["confidence"],
        routing_method=result["routing_method"],
        routing_policy=result["routing_policy"],
        routing_path=result["routing_path"],
        latency_ms=latency_ms,
        prompt_preview=prompt[:100],
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
        # Graceful degradation with fallback agent when args missing
        print(
            json.dumps(
                {
                    "selected_agent": DEFAULT_AGENT,
                    "confidence": 0.5,
                    "candidates": [],
                    "reasoning": "Fallback: missing required arguments",
                    "routing_method": RoutingMethod.LOCAL.value,
                    "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
                    "routing_path": RoutingPath.LOCAL.value,
                    "method": RoutingPolicy.FALLBACK_DEFAULT.value,
                    "latency_ms": 0,
                    "domain": "workflow_coordination",
                    "purpose": "Intelligent coordinator for development workflows",
                    "event_attempted": False,
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

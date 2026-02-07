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

import asyncio
import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

# Add script directory to path for sibling imports
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
# Each import is in its own try block so a failure in one does not
# suppress the other (e.g., redactor failure must not disable emission).
_emit_event_fn: Callable[..., bool] | None = None
_redact_secrets_fn: Callable[[str], str] | None = None

try:
    if __package__:
        from .emit_client_wrapper import emit_event as _emit_event_fn
    else:
        from emit_client_wrapper import (
            emit_event as _emit_event_fn,  # type: ignore[no-redef]
        )
except ImportError:
    _emit_event_fn = None

try:
    if __package__:
        from .secret_redactor import redact_secrets as _redact_secrets_fn
    else:
        from secret_redactor import (
            redact_secrets as _redact_secrets_fn,  # type: ignore[no-redef]
        )
except ImportError:
    _redact_secrets_fn = None


logger = logging.getLogger(__name__)

# ONEX routing node imports (for USE_ONEX_ROUTING_NODES feature flag)
_onex_nodes_available = False
try:
    from omniclaude.nodes.node_agent_routing_compute.handler_routing_default import (
        HandlerRoutingDefault,
    )
    from omniclaude.nodes.node_agent_routing_compute.models import (
        ModelAgentDefinition,
        ModelRoutingRequest,
    )
    from omniclaude.nodes.node_routing_emission_effect.handler_routing_emitter import (
        HandlerRoutingEmitter,
    )
    from omniclaude.nodes.node_routing_emission_effect.models import (
        ModelEmissionRequest,
    )
    from omniclaude.nodes.node_routing_history_reducer.handler_history_postgres import (
        HandlerHistoryPostgres,
    )

    _onex_nodes_available = True
except ImportError:
    logger.debug("ONEX routing nodes not available, USE_ONEX_ROUTING_NODES ignored")

if TYPE_CHECKING:
    from omniclaude.nodes.node_agent_routing_compute._internal import AgentRegistry

# Canonical routing path values for metrics (from OMN-1893)
VALID_ROUTING_PATHS = frozenset({"event", "local", "hybrid"})


def _compute_routing_path(method: str, event_attempted: bool) -> str:
    """
    Map method to canonical routing_path.

    Logic:
    - event_attempted=False -> "local" (never tried event path)
    - event_attempted=True AND method=event_based -> "event"
    - event_attempted=True AND method=fallback -> "hybrid" (tried event, fell back)
    - Unknown method -> "local" with loud warning

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


def _sanitize_prompt_preview(prompt: str, max_length: int = 100) -> str:
    """Create a sanitized, truncated prompt preview.

    Truncates to max_length and redacts any secrets using the
    existing secret_redactor module.  If the redactor is unavailable,
    returns a placeholder to avoid emitting raw prompt text.

    Args:
        prompt: Raw user prompt text.
        max_length: Maximum length for the preview.

    Returns:
        Sanitized and truncated prompt preview, or a safe placeholder
        when the redaction module is not available.
    """
    if _redact_secrets_fn is None:
        # Redaction unavailable - never emit raw prompt text
        return "[redaction unavailable]"
    preview = prompt[:max_length] if prompt else ""
    return _redact_secrets_fn(preview)


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
            "selected_agent": result.get("selected_agent", DEFAULT_AGENT),
            "confidence": result.get("confidence", 0.5),
            "routing_method": result.get(
                "routing_method", RoutingMethod.FALLBACK.value
            ),
            "routing_policy": result.get(
                "routing_policy", RoutingPolicy.FALLBACK_DEFAULT.value
            ),
            "routing_path": result.get("routing_path", "local"),
            "latency_ms": result.get("latency_ms", 0),
            "domain": result.get("domain", ""),
            "reasoning": result.get("reasoning", ""),
            "prompt_preview": _sanitize_prompt_preview(prompt),
            "event_attempted": result.get("event_attempted", False),
        }

        _emit_event_fn(event_type="routing.decision", payload=payload)
    except Exception as e:
        # Non-blocking: routing emission failure must not break routing
        logger.debug("Failed to emit routing decision: %s", e)


# ONEX routing node singletons (USE_ONEX_ROUTING_NODES)
_compute_handler: Any = None
_emit_handler: Any = None
_history_handler: Any = None
_onex_handler_lock = threading.Lock()
_cached_stats: Any = None
_cached_stats_time: float | None = None
_STATS_CACHE_TTL_SECONDS = 300  # 5 min; stale stats are acceptable for routing hints
_stats_lock = threading.Lock()


def _use_onex_routing_nodes() -> bool:
    """Check if ONEX routing nodes feature flag is enabled."""
    if not _onex_nodes_available:
        return False
    return os.environ.get("USE_ONEX_ROUTING_NODES", "false").lower() in (
        "true",
        "1",
        "yes",
        "on",
        "y",
        "t",
    )


def _get_onex_handlers() -> tuple[Any, Any, Any] | None:
    """Get or create singleton ONEX handlers (compute, emitter, history)."""
    global _compute_handler, _emit_handler, _history_handler
    if _compute_handler is not None:
        return _compute_handler, _emit_handler, _history_handler
    if not _onex_nodes_available:
        return None
    with _onex_handler_lock:
        if _compute_handler is not None:
            return _compute_handler, _emit_handler, _history_handler
        try:
            # Assign to locals first — only promote to globals after all
            # three handlers construct successfully, avoiding a stale
            # non-None _compute_handler when a later constructor fails.
            compute = HandlerRoutingDefault()
            emitter = HandlerRoutingEmitter()
            history = HandlerHistoryPostgres()
        except Exception as e:
            logger.warning("Failed to initialize ONEX handlers: %s", e)
            return None
        # Assign the sentinel (_compute_handler) LAST so that concurrent
        # threads bypassing the lock never see a non-None sentinel while
        # _emit_handler / _history_handler are still None.
        _emit_handler = emitter
        _history_handler = history
        _compute_handler = compute
    return _compute_handler, _emit_handler, _history_handler


def _run_async(coro: Any) -> Any:
    """Run a coroutine from synchronous code.

    Uses asyncio.run() for the common case.  If an event loop is already
    running (e.g., nested async context), falls back to
    loop.run_until_complete() to avoid the RuntimeError that asyncio.run()
    raises in that scenario.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)


def _get_cached_stats() -> Any:
    """Pre-fetch routing stats, cached with a TTL.

    Stats are used as hints for confidence scoring, so brief staleness
    (up to _STATS_CACHE_TTL_SECONDS) is acceptable.  This avoids a
    database round-trip on every routing call while ensuring the cache
    does not grow infinitely stale.
    """
    global _cached_stats, _cached_stats_time
    now = time.time()
    if (
        _cached_stats is not None
        and _cached_stats_time is not None
        and (now - _cached_stats_time) < _STATS_CACHE_TTL_SECONDS
    ):
        return _cached_stats
    handlers = _get_onex_handlers()
    if handlers is None:
        return None
    _, _, history = handlers
    with _stats_lock:
        # Re-check after acquiring lock (another thread may have refreshed)
        if (
            _cached_stats is not None
            and _cached_stats_time is not None
            and (time.time() - _cached_stats_time) < _STATS_CACHE_TTL_SECONDS
        ):
            return _cached_stats
        try:
            _cached_stats = _run_async(history.query_routing_stats())
            _cached_stats_time = time.time()
        except Exception as e:
            logger.debug("Failed to pre-fetch routing stats: %s", e)
    return _cached_stats


def _build_agent_definitions(registry: "AgentRegistry") -> tuple[Any, ...]:
    """Convert AgentRouter registry to ModelAgentDefinition tuple."""
    defs: list[Any] = []
    for name, data in registry.get("agents", {}).items():
        try:
            # domain_context may be a dict in some YAML configs; extract primary
            dc = data.get("domain_context", "general")
            if isinstance(dc, dict):
                dc = dc.get("primary", "general")
            defs.append(
                ModelAgentDefinition(
                    name=name,
                    agent_type=data.get(
                        "agent_type",
                        name.replace("agent-", "").replace("-", "_"),
                    ),
                    description=data.get("description", data.get("title", "")),
                    domain_context=str(dc),
                    explicit_triggers=tuple(data.get("activation_triggers", [])),
                    context_triggers=(),
                    capabilities=tuple(data.get("capabilities", [])),
                    definition_path=data.get("definition_path"),
                )
            )
        except Exception as e:
            logger.debug("Skipping agent %s in ONEX conversion: %s", name, e)
    return tuple(defs)


def _route_via_onex_nodes(
    prompt: str,
    correlation_id: str,
    timeout_ms: int,
    session_id: str | None,
) -> dict[str, Any] | None:
    """Route via ONEX compute + effect nodes. Returns None to fall back."""
    from datetime import UTC, datetime
    from uuid import UUID, uuid4

    handlers = _get_onex_handlers()
    if handlers is None:
        return None
    compute, emitter, _ = handlers

    router = _get_router()
    if router is None:
        return None

    agent_defs = _build_agent_definitions(router.registry)
    if not agent_defs:
        return None

    try:
        cid = UUID(correlation_id)
    except (ValueError, AttributeError):
        cid = uuid4()

    stats = _get_cached_stats()
    start_time = time.time()

    try:
        request = ModelRoutingRequest(
            prompt=prompt,
            correlation_id=cid,
            agent_registry=agent_defs,
            historical_stats=stats,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )

        async def _compute_and_emit() -> tuple[Any, int]:
            """Compute routing and emit in a single event loop."""
            r = await compute.compute_routing(request, correlation_id=cid)
            elapsed_ms = int((time.time() - start_time) * 1000)
            # Emit only if within timeout budget — avoids emitting a routing
            # decision that will be discarded (which would conflict with the
            # legacy fallback's own emission).
            if elapsed_ms <= timeout_ms:
                try:
                    emit_req = ModelEmissionRequest(
                        correlation_id=cid,
                        session_id=session_id or "unknown",
                        selected_agent=r.selected_agent,
                        confidence=r.confidence,
                        confidence_breakdown=r.confidence_breakdown,
                        routing_policy=r.routing_policy,
                        routing_path=r.routing_path,
                        prompt_preview=_sanitize_prompt_preview(prompt),
                        prompt_length=len(prompt),
                        emitted_at=datetime.now(UTC),
                    )
                    await emitter.emit_routing_decision(emit_req, correlation_id=cid)
                except Exception as exc:
                    logger.debug("ONEX emission failed (non-blocking): %s", exc)
            return r, elapsed_ms

        result, latency_ms = _run_async(_compute_and_emit())

        if latency_ms > timeout_ms:
            logger.warning(
                "ONEX routing exceeded %dms budget (%dms), falling back",
                timeout_ms,
                latency_ms,
            )
            return None

        # Result shaping: ModelRoutingResult → wrapper dict
        agents_reg = router.registry.get("agents", {})
        agent_info = agents_reg.get(result.selected_agent, {})
        # Validate routing_path against canonical set (matches legacy path behavior)
        onex_routing_path = result.routing_path
        if onex_routing_path not in VALID_ROUTING_PATHS:
            logger.warning(
                "ONEX routing returned invalid routing_path '%s', defaulting to 'local'",
                onex_routing_path,
            )
            onex_routing_path = "local"
        return {
            "selected_agent": result.selected_agent,
            "confidence": result.confidence,
            "candidates": [
                {
                    "name": c.agent_name,
                    "score": c.confidence,
                    "description": agents_reg.get(c.agent_name, {}).get(
                        "description",
                        agents_reg.get(c.agent_name, {}).get("title", c.agent_name),
                    ),
                    "reason": c.match_reason,
                }
                for c in result.candidates
            ],
            "reasoning": result.fallback_reason
            or result.confidence_breakdown.explanation,
            "routing_method": RoutingMethod.LOCAL.value,
            "routing_policy": result.routing_policy,
            "routing_path": onex_routing_path,
            "method": result.routing_policy,
            "latency_ms": latency_ms,
            "domain": agent_info.get("domain_context", "general"),
            "purpose": agent_info.get("description", agent_info.get("title", "")),
            "event_attempted": False,
        }

    except Exception as e:
        logger.warning("ONEX routing failed, falling back to legacy: %s", e)
        return None


def route_via_events(
    prompt: str,
    correlation_id: str,
    timeout_ms: int = 5000,
    session_id: str | None = None,  # Used by ONEX emission path
) -> dict[str, Any]:
    """
    Route user prompt using intelligent trigger matching and confidence scoring.

    When USE_ONEX_ROUTING_NODES is enabled, delegates to ONEX compute and
    effect nodes. Otherwise uses AgentRouter directly. Falls back to
    polymorphic-agent only when no good match is found.

    Args:
        prompt: User prompt to route
        correlation_id: Correlation ID for tracking
        timeout_ms: Maximum allowed routing time in milliseconds (default 5000).
            If the routing operation exceeds this budget, the result is
            discarded and a fallback to the default agent is returned.
        session_id: Session ID for emission tracking

    Returns:
        Routing decision dictionary with routing_path signal
    """
    start_time = time.time()
    event_attempted = False  # Local routing, no event bus

    # Validate inputs before processing
    if not isinstance(prompt, str) or not prompt.strip():
        logger.warning("Invalid or empty prompt received, using fallback")
        return {
            "selected_agent": DEFAULT_AGENT,
            "confidence": 0.5,
            "candidates": [],
            "reasoning": "Invalid input - empty or non-string prompt",
            "routing_method": RoutingMethod.FALLBACK.value,
            "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
            "routing_path": RoutingPath.LOCAL.value,
            "method": RoutingPolicy.FALLBACK_DEFAULT.value,
            "latency_ms": 0,
            "domain": "workflow_coordination",
            "purpose": "Intelligent coordinator for development workflows",
            "event_attempted": False,
        }

    if not isinstance(correlation_id, str) or not correlation_id.strip():
        logger.warning("Invalid or empty correlation_id, using fallback")
        return {
            "selected_agent": DEFAULT_AGENT,
            "confidence": 0.5,
            "candidates": [],
            "reasoning": "Invalid input - empty or non-string correlation_id",
            "routing_method": RoutingMethod.FALLBACK.value,
            "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
            "routing_path": RoutingPath.LOCAL.value,
            "method": RoutingPolicy.FALLBACK_DEFAULT.value,
            "latency_ms": 0,
            "domain": "workflow_coordination",
            "purpose": "Intelligent coordinator for development workflows",
            "event_attempted": False,
        }

    # ONEX node routing path (when feature flag is enabled)
    if _use_onex_routing_nodes():
        onex_result = _route_via_onex_nodes(
            prompt, correlation_id, timeout_ms, session_id
        )
        if onex_result is not None:
            return onex_result
        logger.debug("ONEX routing returned None, falling through to legacy path")

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
            recommendations = router.route(prompt, max_recommendations=5)

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

    # Enforce timeout: if routing exceeded the budget, discard result and
    # force fallback so callers never wait longer than they specified.
    if latency_ms > timeout_ms:
        logger.warning(
            "Routing exceeded %dms timeout (%dms elapsed), forcing fallback to %s",
            timeout_ms,
            latency_ms,
            DEFAULT_AGENT,
        )
        selected_agent = DEFAULT_AGENT
        confidence = 0.5
        candidates_list = []
        reasoning = f"Routing timeout ({latency_ms}ms > {timeout_ms}ms limit)"
        routing_policy = RoutingPolicy.FALLBACK_DEFAULT
        domain = "workflow_coordination"
        purpose = "Intelligent coordinator for development workflows"

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

    # Emit routing decision event for observability (non-blocking)
    _emit_routing_decision(result=result, prompt=prompt, correlation_id=correlation_id)

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

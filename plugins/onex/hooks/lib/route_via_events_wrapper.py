#!/usr/bin/env python3
"""
Route Via Events Wrapper - Intelligent Agent Routing

Routes user prompts to the best-matched agent using trigger matching and
confidence scoring. Returns an empty string (no agent selected) when no good
match is found (confidence below threshold).

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
from typing import TYPE_CHECKING, Any, Protocol

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

# ONEX routing node imports (for USE_ONEX_ROUTING_NODES feature flag).
# Split into two independent try blocks so that a failure in HandlerRoutingLlm
# does not mask _onex_nodes_available (or vice-versa).  Each flag reflects only
# the availability of the symbols it actually guards.
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

# LLM handler import (for USE_LLM_ROUTING feature flag).
# Kept separate from the ONEX nodes block so that HandlerRoutingLlm import
# failures do not affect _onex_nodes_available.
_llm_handler_available = False
# Routing prompt version sentinel — overwritten on successful import below.
_llm_routing_prompt_version: str = "unknown"
try:
    from omniclaude.nodes.node_agent_routing_compute.handler_routing_llm import (
        _ROUTING_PROMPT_VERSION,  # noqa: PLC2701
        HandlerRoutingLlm,
    )

    _llm_routing_prompt_version = _ROUTING_PROMPT_VERSION
    _llm_handler_available = True
except ImportError:
    logger.debug("HandlerRoutingLlm not available, USE_LLM_ROUTING ignored")

# LLM endpoint registry import (for USE_LLM_ROUTING feature flag)
_llm_registry_available = False
try:
    from omniclaude.config.model_local_llm_config import (
        LlmEndpointPurpose,
        LocalLlmEndpointRegistry,
    )

    _llm_registry_available = True
except ImportError:
    logger.debug("LLM endpoint registry not available, USE_LLM_ROUTING ignored")

if TYPE_CHECKING:
    from omniclaude.nodes.node_agent_routing_compute._internal import AgentRegistry

# Canonical routing path values for metrics (from OMN-1893)
VALID_ROUTING_PATHS = frozenset({"event", "local", "hybrid"})


class _LatencyGuardProtocol(Protocol):
    """Structural interface for the LatencyGuard singleton.

    Describes only the methods actually called on the guard throughout this
    module.  The conditional import of LatencyGuard uses this Protocol so
    that mypy can type-check all call sites without requiring the concrete
    class to be importable at type-check time.
    """

    @classmethod
    def get_instance(cls) -> "_LatencyGuardProtocol": ...
    def is_enabled(self) -> bool: ...
    def record_latency(self, latency_ms: float) -> None: ...
    def record_agreement(self, *, agreed: bool) -> None: ...


# LatencyGuard import (for USE_LLM_ROUTING latency SLO enforcement).
# Graceful fallback: if unavailable, LLM routing proceeds without the guard.
_latency_guard_available = False
_LatencyGuardClass: type[_LatencyGuardProtocol] | None = None
try:
    if __package__:
        from .latency_guard import LatencyGuard as _LatencyGuardClass  # noqa: I001
    else:
        from latency_guard import (  # type: ignore[import-not-found,no-redef]
            LatencyGuard as _LatencyGuardClass,
        )
    _latency_guard_available = True
except ImportError:
    logger.debug("latency_guard not available, LLM routing proceeds without SLO guard")


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

# Lock that ensures at most one llm-fuzzy-agreement thread runs at a time.
# acquire(blocking=False) at spawn time: if already locked, skip spawning.
# try/finally in the thread body always releases it.
_agreement_lock = threading.Lock()

try:
    from agent_router import AgentRouter

    _AgentRouter = AgentRouter
except ImportError:
    logger.debug("agent_router not available, will use fallback routing")


# Confidence threshold for accepting a routed agent
# Below this threshold, no agent is selected (empty string)
CONFIDENCE_THRESHOLD = 0.5

# Empty string — no fallback agent; callers receive "" when nothing matched
DEFAULT_AGENT = ""


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


def _emit_llm_routing_decision(
    result: dict[str, Any],
    correlation_id: str,
    session_id: str | None,
    *,
    fuzzy_top_candidate: str | None,
    llm_selected_candidate: str | None,
    agreement: bool,
    routing_prompt_version: str,
    model_used: str,
) -> None:
    """Emit LLM routing decision event (OMN-2273).

    Emitted after a successful LLM routing decision.  Contains the full
    decision metadata including the determinism-audit fields required to
    compare LLM vs fuzzy matching agreement.

    Non-blocking: logs at debug level on failure but never raises.

    Args:
        result: Routing result dict from ``_route_via_llm``.
        correlation_id: Correlation ID for distributed tracing.
        session_id: Session identifier for Kafka partition key.
        fuzzy_top_candidate: Top agent from fuzzy matching (audit).
        llm_selected_candidate: Raw agent name the LLM returned.
        agreement: True when LLM and fuzzy top candidates agree.
        routing_prompt_version: Prompt template version string.
        model_used: Model identifier used for routing.
    """
    if _emit_event_fn is None:
        logger.debug("emit_event not available, skipping llm routing decision emission")
        return

    try:
        payload: dict[str, object] = {
            "session_id": session_id or "unknown",
            "correlation_id": correlation_id,
            "selected_agent": result.get("selected_agent", DEFAULT_AGENT),
            "llm_confidence": result.get("confidence", 0.0),
            "llm_latency_ms": result.get("latency_ms", 0),
            "fallback_used": bool(result.get("fallback_used", False)),
            "model_used": model_used,
            "fuzzy_top_candidate": fuzzy_top_candidate,
            "llm_selected_candidate": llm_selected_candidate,
            "agreement": agreement,
            "routing_prompt_version": routing_prompt_version,
        }
        _emit_event_fn(event_type="llm.routing.decision", payload=payload)
    except Exception as exc:
        logger.debug("Failed to emit llm routing decision: %s", exc)


def _emit_llm_routing_fallback(
    correlation_id: str,
    session_id: str | None,
    fallback_reason: str,
    llm_url: str | None,
    routing_prompt_version: str,
) -> None:
    """Emit LLM routing fallback event (OMN-2273).

    Emitted when ``_route_via_llm`` returns None, causing the pipeline
    to fall through to fuzzy matching.  Provides observability into why
    the LLM routing path was not used.

    Non-blocking: logs at debug level on failure but never raises.

    Args:
        correlation_id: Correlation ID for distributed tracing.
        session_id: Session identifier for Kafka partition key.
        fallback_reason: Human-readable reason for the fallback.
        llm_url: LLM endpoint URL that was attempted, if known.
        routing_prompt_version: Prompt template version string.
    """
    if _emit_event_fn is None:
        logger.debug("emit_event not available, skipping llm routing fallback emission")
        return

    try:
        payload: dict[str, object] = {
            "session_id": session_id or "unknown",
            "correlation_id": correlation_id,
            "fallback_reason": fallback_reason,
            "llm_url": llm_url,
            "routing_prompt_version": routing_prompt_version,
        }
        _emit_event_fn(event_type="llm.routing.fallback", payload=payload)
    except Exception as exc:
        logger.debug("Failed to emit llm routing fallback: %s", exc)


# ONEX routing node singletons (USE_ONEX_ROUTING_NODES)
_compute_handler: Any = None
_emit_handler: Any = None
_history_handler: Any = None
_onex_handler_lock = threading.Lock()
_cached_stats: Any = None
_cached_stats_time: float | None = None
_STATS_CACHE_TTL_SECONDS = 300  # 5 min; stale stats are acceptable for routing hints
_stats_lock = threading.Lock()


# Truthy value set shared by feature flag helpers below.
_TRUTHY = frozenset(("true", "1", "yes", "on", "y", "t"))


def _use_onex_routing_nodes() -> bool:
    """Check if ONEX routing nodes feature flag is enabled."""
    if not _onex_nodes_available:
        return False
    return os.environ.get("USE_ONEX_ROUTING_NODES", "false").lower() in _TRUTHY


def _parse_routing_timeout(
    raw: str | None, default: float, min_val: float = 0.01
) -> float:
    """Parse a timeout value from an environment variable string.

    Enforces a lower bound (``min_val``) and an upper bound of 60 seconds.
    Values outside either bound are rejected and ``default`` is returned
    instead.  The 60-second ceiling prevents accidental misconfiguration
    (e.g. ``LLM_ROUTING_TIMEOUT_S=600``) from freezing the hook indefinitely.

    Args:
        raw: Raw string value from the environment (or None / empty string).
        default: Value to return when raw is absent, unparseable, or invalid.
        min_val: Minimum acceptable value; values <= min_val are rejected.

    Returns:
        Parsed float timeout, or ``default`` when the input is absent or
        invalid.  Warnings are written to both stderr and the module logger
        so they do not pollute the hook's JSON stdout while still appearing
        in structured log output.
    """
    _MAX_TIMEOUT_S = 60.0  # Hard ceiling — values above this indicate misconfiguration

    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        msg = (
            f"[route_via_events_wrapper] WARNING: invalid timeout value {raw!r} "
            f"(expected float) — using default {default}s"
        )
        print(msg, file=sys.stderr)
        logger.warning(msg)
        return default
    if value <= min_val:
        msg = (
            f"[route_via_events_wrapper] WARNING: timeout value {value} is <= {min_val} "
            f"— using default {default}s"
        )
        print(msg, file=sys.stderr)
        logger.warning(msg)
        return default
    if value > _MAX_TIMEOUT_S:
        msg = (
            f"[route_via_events_wrapper] WARNING: timeout value {value} exceeds "
            f"maximum allowed {_MAX_TIMEOUT_S}s — clamping to default {default}s"
        )
        print(msg, file=sys.stderr)
        logger.warning(msg)
        return default
    return value


# Timeout for the LLM health check and routing call.
# Default is 100ms (per ticket spec, designed for local models).
# Override via LLM_ROUTING_TIMEOUT_S env var for networked models — e.g.
# set to 2.0 when routing through a model on a remote server.
_LLM_ROUTING_TIMEOUT_S: float = _parse_routing_timeout(
    os.environ.get("LLM_ROUTING_TIMEOUT_S"), default=0.1
)
# Inner httpx timeout for the health check, kept at 85% of the outer timeout
# so the HTTP request can fail cleanly before asyncio.wait_for fires.
_LLM_HEALTH_CHECK_TIMEOUT_S: float = _LLM_ROUTING_TIMEOUT_S * 0.85


def _get_latency_guard() -> _LatencyGuardProtocol | None:
    """Return the LatencyGuard singleton, or None if unavailable.

    Returns:
        LatencyGuard instance or None when the guard module is not importable.
    """
    if not _latency_guard_available or _LatencyGuardClass is None:
        return None
    try:
        return _LatencyGuardClass.get_instance()
    except Exception as exc:
        logger.debug("LatencyGuard.get_instance() failed (non-blocking): %s", exc)
        return None


def _use_llm_routing() -> bool:
    """Check if LLM routing is enabled.

    Requires:
    - ENABLE_LOCAL_INFERENCE_PIPELINE=true  (parent gate)
    - USE_LLM_ROUTING=true                  (specific flag)
    - HandlerRoutingLlm and LocalLlmEndpointRegistry importable
    - LatencyGuard allows it (circuit not open, agreement rate not low)

    Returns:
        True only when all conditions are met.
    """
    if not _llm_handler_available or not _llm_registry_available:
        return False
    parent = os.environ.get("ENABLE_LOCAL_INFERENCE_PIPELINE", "").lower()
    if parent not in _TRUTHY:
        return False
    flag = os.environ.get("USE_LLM_ROUTING", "").lower()
    if flag not in _TRUTHY:
        return False
    # LatencyGuard is the final gate: circuit-open or low agreement → False.
    guard = _get_latency_guard()
    if guard is not None and not guard.is_enabled():
        logger.debug("LLM routing suppressed by LatencyGuard (SLO or agreement breach)")
        return False
    return True


def _get_llm_routing_url() -> tuple[str, str] | None:
    """Return the (url, model_name) pair to use for routing, or None.

    Prefers LlmEndpointPurpose.ROUTING; falls back to GENERAL (Qwen2.5-14B),
    then REASONING (Qwen2.5-72B) since no dedicated routing model is currently
    deployed.

    Returns:
        ``(url, model_name)`` tuple (url without trailing slash) or None.
    """
    if not _llm_registry_available:
        return None
    try:
        registry = LocalLlmEndpointRegistry()
        # Try dedicated ROUTING purpose first, then GENERAL, REASONING, CODE_ANALYSIS.
        # CODE_ANALYSIS last so that a coder model (e.g. .201) is picked up
        # automatically once LLM_CODER_URL is set, without needing a code change.
        endpoint = registry.get_endpoint(LlmEndpointPurpose.ROUTING)
        if endpoint is None:
            endpoint = registry.get_endpoint(LlmEndpointPurpose.GENERAL)
        if endpoint is None:
            endpoint = registry.get_endpoint(LlmEndpointPurpose.REASONING)
        if endpoint is None:
            endpoint = registry.get_endpoint(LlmEndpointPurpose.CODE_ANALYSIS)
        if endpoint is None:
            logger.debug("No LLM endpoint configured for routing")
            return None
        url = str(endpoint.url).rstrip("/")
        model_name = getattr(endpoint, "model_name", None) or "unknown"
        logger.debug(
            "Resolved LLM routing URL: purpose=%s url=%s model=%s",
            endpoint.purpose if hasattr(endpoint, "purpose") else "unknown",
            url,
            model_name,
        )
        return url, model_name
    except Exception as exc:
        logger.debug("Failed to load LLM endpoint registry: %s", exc)
        return None


async def _check_llm_health(llm_url: str, timeout_s: float) -> bool:
    """Probe the LLM endpoint /health route within *timeout_s* seconds.

    A successful HTTP response (any 2xx) is treated as healthy. Any
    exception or non-2xx status code is treated as unhealthy. Never raises.

    Args:
        llm_url: Base URL of the LLM endpoint.
        timeout_s: Maximum seconds to wait for the health check.

    Returns:
        True if the endpoint appears healthy, False otherwise.
    """
    try:
        # httpx is treated as an optional dependency: it is not listed in
        # pyproject.toml because the LLM routing path is feature-flagged.
        # ImportError is intentionally caught here as a health check failure
        # so that the hook degrades gracefully when httpx is not installed.
        import httpx

        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(f"{llm_url}/health")
            return response.is_success
    except Exception as exc:
        logger.debug("LLM health check failed for %s: %s", llm_url, exc)
        return False


def _route_via_llm(
    prompt: str,
    correlation_id: str,
) -> dict[str, Any] | None:
    """Attempt LLM-based routing and return a result dict, or None to fall through.

    Chain:
    1. Resolve LLM URL from endpoint registry.
    2. Health-check the endpoint within _LLM_ROUTING_TIMEOUT_S (100 ms).
    3. Build ModelAgentDefinition list from the AgentRouter registry via
       _build_agent_definitions(), then construct a ModelRoutingRequest.
    4. Call HandlerRoutingLlm.compute_routing() within _LLM_ROUTING_TIMEOUT_S.
    5. Shape result into the canonical wrapper dict.

    On any failure (unhealthy endpoint, timeout, exception) returns None so
    the caller falls through to fuzzy matching. "LLM enhances, never blocks."

    Latency budget note:
        Each of the two async calls (health check and LLM routing) is guarded
        by _LLM_ROUTING_TIMEOUT_S independently.  In the worst case both calls
        time out, producing a combined latency of ~200 ms (2 x 100 ms) before
        this function returns None.  This is documented in .env.example and is
        intentional — the health check and the routing call are sequential, not
        parallelised, so callers should budget for ~200 ms worst-case when LLM
        routing is enabled.

    Args:
        prompt: User prompt to route.
        correlation_id: Correlation ID for tracing.

    Returns:
        Routing result dict on success, None on any failure.
    """
    from uuid import UUID, uuid4

    # `start` is set later, immediately before the actual LLM HTTP call (step 4),
    # so that the LatencyGuard SLO measures only the LLM invocation latency and
    # not the pre-call overhead (URL resolution, health check, registry building).
    # Including the health check (up to 80 ms) would cause false circuit trips
    # even when the LLM itself responds within the 80 ms P95 SLO.
    start: float | None = None

    # 1. Resolve LLM URL (now returns (url, model_name) tuple)
    llm_endpoint = _get_llm_routing_url()
    if llm_endpoint is None:
        return None
    llm_url, llm_model_name = llm_endpoint

    # 2. Health check (100 ms budget per call; combined worst-case with step 4 is ~200 ms)
    # _LLM_HEALTH_CHECK_TIMEOUT_S (0.08 s) is passed to httpx so the HTTP
    # request completes or fails before asyncio.wait_for's outer 0.1 s
    # deadline fires.  This ensures clean cancellation ordering.
    try:
        healthy = _run_async(
            _check_llm_health(llm_url, _LLM_HEALTH_CHECK_TIMEOUT_S),
            timeout=_LLM_ROUTING_TIMEOUT_S,
        )
    except Exception as exc:
        logger.debug("LLM health check raised: %s", exc)
        healthy = False

    if not healthy:
        logger.debug("LLM endpoint %s is unhealthy, skipping LLM routing", llm_url)
        return None

    # 3. Build routing request from AgentRouter registry
    router = _get_router()
    if router is None:
        return None

    agent_defs = _build_agent_definitions(router.registry)
    # Robust guard: agent_defs must be a non-empty sequence with at least one
    # item.  A plain `if not agent_defs` would also catch empty tuples/lists,
    # but the isinstance check makes the intent explicit and guards against
    # pathological return values (e.g., None, a non-sequence) that could
    # otherwise propagate silently into HandlerRoutingLlm.
    if not isinstance(agent_defs, (list, tuple)) or len(agent_defs) < 1:
        logger.warning(
            "LLM routing skipped: _build_agent_definitions returned no valid agents "
            "(type=%s, len=%s, correlation_id=%s)",
            type(agent_defs).__name__,
            len(agent_defs) if isinstance(agent_defs, (list, tuple)) else "n/a",
            correlation_id,
        )
        return None

    try:
        cid = UUID(correlation_id)
    except (ValueError, AttributeError):
        cid = uuid4()

    # 4. Call HandlerRoutingLlm within 100 ms (independent budget from step 2; see docstring)
    # HandlerRoutingLlm construction and ModelRoutingRequest construction are in
    # separate try blocks so that a failure in either produces a distinct log
    # message and the successfully-constructed handler is not silently abandoned
    # without a clear indication of which step failed.
    try:
        llm_handler = HandlerRoutingLlm(
            llm_url=llm_url,
            model_name=llm_model_name,
            timeout=_LLM_ROUTING_TIMEOUT_S,
        )
    except Exception as exc:
        logger.debug(
            "HandlerRoutingLlm construction failed: %s (correlation_id=%s)",
            exc,
            correlation_id,
        )
        return None

    try:
        request = ModelRoutingRequest(
            prompt=prompt,
            correlation_id=cid,
            agent_registry=agent_defs,
            confidence_threshold=CONFIDENCE_THRESHOLD,
        )
    except Exception as exc:
        logger.debug(
            "ModelRoutingRequest construction failed: %s (correlation_id=%s)",
            exc,
            correlation_id,
        )
        return None

    # Start timing immediately before the HTTP/LLM invocation so the LatencyGuard
    # SLO only measures the actual LLM call latency (not health check or setup).
    # Use monotonic clock (not wall clock) to avoid NTP adjustments producing
    # incorrect (negative or inflated) latency readings per latency_guard.py.
    start = time.monotonic()
    try:
        result = _run_async(
            llm_handler.compute_routing(request, correlation_id=cid),
            timeout=_LLM_ROUTING_TIMEOUT_S,
        )
    except TimeoutError:
        logger.debug(
            "LLM routing call timed out after %.0fms (correlation_id=%s)",
            _LLM_ROUTING_TIMEOUT_S * 1000,
            correlation_id,
        )
        if start is not None:
            elapsed_ms = (time.monotonic() - start) * 1000
            guard = _get_latency_guard()
            if guard is not None:
                try:
                    guard.record_latency(elapsed_ms)
                except Exception as exc:
                    logger.debug(
                        "LatencyGuard.record_latency failed on timeout (non-blocking): %s",
                        exc,
                    )
        return None
    except Exception as exc:
        logger.debug(
            "LLM routing call failed: %s (correlation_id=%s)", exc, correlation_id
        )
        return None

    # 5. Shape result into canonical wrapper dict
    # latency_ms measures only the LLM HTTP call (start set immediately above).
    # Use float for the guard measurement to preserve sub-millisecond precision
    # (e.g. 80.9ms must not be truncated to 80.0ms, which would not trip the
    # P95 SLO circuit that opens at > 80.0ms).  The integer version is kept
    # for the output dict / logs so the external interface stays the same.
    if start is None:
        # start is always set before the LLM call; all early-returns above exit
        # first.  This guard defends against optimised builds where assert is
        # stripped (-O flag) and any future code paths that bypass the assignment.
        # Return None (not the raw Pydantic object) so the caller falls through
        # to fuzzy routing — callers consume the return value as a dict via
        # `.get(...)`, so a Pydantic object would cause silent attribute errors.
        logger.warning(
            "_route_via_llm: start timestamp unexpectedly None after LLM call "
            "(correlation_id=%s); skipping latency recording",
            correlation_id,
        )
        return None
    latency_ms_float = (time.monotonic() - start) * 1000
    latency_ms = int(latency_ms_float)

    # Record latency with the guard so it can enforce the P95 SLO.
    guard = _get_latency_guard()
    if guard is not None:
        try:
            guard.record_latency(latency_ms_float)
        except Exception as exc:
            logger.debug("LatencyGuard.record_latency failed (non-blocking): %s", exc)

    agents_reg = router.registry.get("agents", {})
    agent_info = agents_reg.get(result.selected_agent, {})
    if result.selected_agent not in agents_reg:
        logger.warning(
            "LLM routing selected agent '%s' not found in agents registry "
            "(possible hallucination); domain/purpose will use defaults "
            "(correlation_id=%s)",
            result.selected_agent,
            correlation_id,
        )
    onex_routing_path = result.routing_path
    if onex_routing_path not in VALID_ROUTING_PATHS:
        logger.warning(
            "LLM routing returned invalid routing_path '%s', defaulting to 'local'",
            onex_routing_path,
        )
        onex_routing_path = "local"

    logger.info(
        "LLM routing selected %s (confidence=%.2f, latency=%dms, correlation_id=%s)",
        result.selected_agent,
        result.confidence,
        latency_ms,
        correlation_id,
    )

    return {
        "selected_agent": result.selected_agent,
        "confidence": result.confidence,
        "candidates": [
            {
                "name": c.agent_name,
                "score": c.confidence,
                "description": (ci := agents_reg.get(c.agent_name, {})).get(
                    "description",
                    ci.get("title", c.agent_name),
                ),
                "reason": c.match_reason,
            }
            for c in result.candidates
        ],
        "reasoning": result.fallback_reason
        or (
            result.confidence_breakdown.explanation
            if result.confidence_breakdown is not None
            else ""
        ),
        # routing_method is intentionally LOCAL here: LLM routing runs in-process
        # on the local machine (consistent with the ONEX path that also uses LOCAL).
        # A dedicated RoutingMethod.LLM value would require new enum governance and
        # is deferred until a clear product need arises.
        "routing_method": RoutingMethod.LOCAL.value,
        "routing_policy": result.routing_policy,
        "routing_path": onex_routing_path,
        "method": result.routing_policy,
        "latency_ms": latency_ms,
        "domain": agent_info.get("domain_context", "general"),
        "purpose": agent_info.get("description", agent_info.get("title", "")),
        "event_attempted": False,
        # OMN-2273: observability fields for LLM routing decision event
        "model_used": llm_model_name,
        "llm_url": llm_url,
        # llm_selected_candidate: raw agent name before fallback validation.
        # ``result.fallback_reason is not None`` means the LLM selection was
        # overridden by the fuzzy fallback, so the selected_agent is the
        # highest-confidence trigger candidate, not what the LLM returned.
        # We track the post-validation selected_agent here; the raw LLM text
        # is not retained by HandlerRoutingLlm and is unavailable at this level.
        "llm_selected_candidate": result.selected_agent,
        "fallback_used": result.fallback_reason is not None,
    }


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


def _run_async(coro: Any, timeout: float = 5.0) -> Any:
    """Run a coroutine from synchronous code with timeout enforcement.

    Uses asyncio.run() for the common case.  If an event loop is already
    running (e.g., nested async context), offloads to a new thread with
    its own event loop to avoid RuntimeError.

    Args:
        coro: The coroutine to execute.
        timeout: Maximum seconds to allow the coroutine to run before
            cancellation.  Defaults to 5.0, matching the routing budget.
            The timeout is enforced at the async boundary via
            ``asyncio.wait_for`` so that the coroutine is *cancelled*
            rather than merely abandoned.  On the thread path a secondary
            ``future.result(timeout=...)`` guard provides belt-and-suspenders
            protection against hangs outside the coroutine itself.

    Raises:
        TimeoutError: If the coroutine exceeds *timeout* seconds.
            On the event-loop path this is ``asyncio.TimeoutError``; on the
            thread-pool path it is ``concurrent.futures.TimeoutError``.  Both
            are subclasses of the builtin ``TimeoutError`` on Python 3.11+.
    """
    guarded = asyncio.wait_for(coro, timeout=timeout)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No loop running — safe to create one
        return asyncio.run(guarded)

    # Loop is running — cannot use run_until_complete or asyncio.run.
    # Offload to a new thread that creates its own event loop.
    # Use explicit pool lifecycle (no context manager) so that on timeout
    # we call shutdown(wait=False) to avoid blocking on a hung thread.
    import concurrent.futures

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(asyncio.run, guarded)
    try:
        # Secondary timeout guard (belt-and-suspenders): if the inner
        # asyncio.wait_for doesn't fire for some reason, this catches it.
        return future.result(timeout=timeout)
    finally:
        # Always shut down without waiting. On success the thread has
        # already finished; on timeout or error we must not block.
        # cancel_futures=True (Python 3.9+) prevents queued work.
        pool.shutdown(wait=False, cancel_futures=True)


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
            _cached_stats = _run_async(history.query_routing_stats(), timeout=5.0)
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

        result, latency_ms = _run_async(_compute_and_emit(), timeout=timeout_ms / 1000)

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
            or (
                result.confidence_breakdown.explanation
                if result.confidence_breakdown is not None
                else ""
            ),
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


def _record_llm_fuzzy_agreement(llm_selected: str, prompt: str) -> None:
    """Record whether the LLM routing result agrees with fuzzy matching.

    Runs fuzzy matching in shadow mode (result discarded) to compare against
    the LLM-selected agent, then records the observation with the LatencyGuard.
    Non-blocking: any failure is suppressed so routing is never affected.

    Agreement is defined as both methods selecting the same top agent name.
    When fuzzy matching falls back to DEFAULT_AGENT, the LLM must also have
    selected DEFAULT_AGENT for agreement to be True.

    Args:
        llm_selected: Agent name selected by LLM routing.
        prompt: The user prompt (passed to fuzzy router for comparison).
    """
    try:
        guard = _get_latency_guard()
        if guard is None:
            return

        router = _get_router()
        if router is None:
            # No fuzzy router — cannot compute agreement; skip recording to
            # avoid artificially deflating the rate.
            return

        recommendations = router.route(prompt, max_recommendations=1)
        if (
            recommendations
            and recommendations[0].confidence.total >= CONFIDENCE_THRESHOLD
        ):
            fuzzy_selected = recommendations[0].agent_name
        else:
            fuzzy_selected = DEFAULT_AGENT

        agreed = llm_selected == fuzzy_selected
        guard.record_agreement(agreed=agreed)
        logger.debug(
            "LatencyGuard agreement: llm=%s fuzzy=%s agreed=%s",
            llm_selected,
            fuzzy_selected,
            agreed,
        )
    except Exception as exc:
        # Log at debug so failures anywhere in this function (guard lookup, fuzzy
        # router, or guard.record_agreement) are not completely invisible
        # (non-blocking — routing continues).
        logger.debug("_record_llm_fuzzy_agreement failed (non-blocking): %s", exc)
    finally:
        _agreement_lock.release()


def route_via_events(
    prompt: str,
    correlation_id: str,
    timeout_ms: int = 5000,
    session_id: str | None = None,  # Used by ONEX emission path
    _start_time: float | None = None,
) -> dict[str, Any]:
    """
    Route user prompt using intelligent trigger matching and confidence scoring.

    When USE_ONEX_ROUTING_NODES is enabled, delegates to ONEX compute and
    effect nodes. Otherwise uses AgentRouter directly. Returns an empty string
    (no agent selected) when no good match is found.

    Args:
        prompt: User prompt to route
        correlation_id: Correlation ID for tracking
        timeout_ms: Maximum allowed routing time in milliseconds (default 5000).
            If the routing operation exceeds this budget, the result is
            discarded and a fallback to the default agent is returned.
        session_id: Session ID for emission tracking
        _start_time: Optional wall-clock start time (from ``time.time()``).
            When provided, latency tracking includes time spent *before*
            this function was called (e.g., Python interpreter startup,
            argument parsing).  Callers that care about end-to-end budget
            accuracy should capture ``time.time()`` as early as possible
            and pass it here.

    Returns:
        Routing decision dictionary with routing_path signal
    """
    start_time = _start_time if _start_time is not None else time.time()
    event_attempted = False  # Local routing, no event bus

    # Validate inputs before processing
    if not isinstance(prompt, str) or not prompt.strip():
        logger.warning("Invalid or empty prompt received, using fallback")
        return {
            "selected_agent": DEFAULT_AGENT,
            "confidence": 0.0,
            "candidates": [],
            "reasoning": "Invalid input - empty or non-string prompt",
            "routing_method": RoutingMethod.FALLBACK.value,
            "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
            "routing_path": RoutingPath.LOCAL.value,
            "method": RoutingPolicy.FALLBACK_DEFAULT.value,
            "latency_ms": 0,
            "domain": "",
            "purpose": "",
            "event_attempted": False,
        }

    if not isinstance(correlation_id, str) or not correlation_id.strip():
        logger.warning("Invalid or empty correlation_id, using fallback")
        return {
            "selected_agent": DEFAULT_AGENT,
            "confidence": 0.0,
            "candidates": [],
            "reasoning": "Invalid input - empty or non-string correlation_id",
            "routing_method": RoutingMethod.FALLBACK.value,
            "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
            "routing_path": RoutingPath.LOCAL.value,
            "method": RoutingPolicy.FALLBACK_DEFAULT.value,
            "latency_ms": 0,
            "domain": "",
            "purpose": "",
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

    # LLM routing path (when USE_LLM_ROUTING + ENABLE_LOCAL_INFERENCE_PIPELINE enabled)
    if _use_llm_routing():
        llm_result = _route_via_llm(prompt, correlation_id)
        if llm_result is not None:
            # Record agreement: compare LLM selection against fuzzy matching.
            # Run fuzzy in shadow (result discarded) to track the agreement rate
            # that feeds the LatencyGuard auto-disable gate.
            #
            # Backgrounded in a daemon thread so that fuzzy routing (CPU-bound)
            # does NOT add synchronous latency to the UserPromptSubmit hot path.
            # Hooks must never block the UI (CLAUDE.md performance budget).
            # The thread is a daemon so it does not prevent process exit.
            #
            # _agreement_lock ensures at most one agreement-recording thread
            # runs at a time.  acquire(blocking=False) skips spawning a new
            # thread when one is already running (prevents unbounded thread
            # accumulation under concurrent routing calls).
            _llm_selected = llm_result.get("selected_agent", "")
            if _agreement_lock.acquire(blocking=False):
                _agreement_thread = threading.Thread(
                    target=_record_llm_fuzzy_agreement,
                    args=(_llm_selected, prompt),
                    daemon=True,
                    name="llm-fuzzy-agreement",
                )
                try:
                    _agreement_thread.start()
                except Exception as exc:
                    # Thread failed to start (e.g. RuntimeError: can't start new
                    # thread).  Release the lock immediately so future routing
                    # calls can still spawn an agreement thread.
                    _agreement_lock.release()
                    logger.debug(
                        "llm-fuzzy-agreement thread failed to start (non-blocking): %s",
                        exc,
                    )
            else:
                logger.debug(
                    "llm-fuzzy-agreement thread already running, skipping spawn"
                )
            _emit_routing_decision(
                result=llm_result, prompt=prompt, correlation_id=correlation_id
            )
            # OMN-2273: emit LLM-specific decision event with determinism audit fields.
            # agreement is not yet known here (background thread), so we emit without
            # it and rely on the LatencyGuard's record_agreement for tracking.
            _emit_llm_routing_decision(
                result=llm_result,
                correlation_id=correlation_id,
                session_id=session_id,
                fuzzy_top_candidate=None,  # not yet known at emission time; background thread runs after this call
                llm_selected_candidate=llm_result.get(
                    "llm_selected_candidate", llm_result.get("selected_agent")
                ),
                agreement=False,  # not yet known at emission time; Kafka is append-only so this field cannot be updated retroactively
                routing_prompt_version=_llm_routing_prompt_version,
                model_used=llm_result.get("model_used", "unknown"),
            )
            return llm_result
        # OMN-2273: LLM routing returned None — emit fallback event so consumers can
        # observe how often the LLM path is skipped and the reason distribution.
        _emit_llm_routing_fallback(
            correlation_id=correlation_id,
            session_id=session_id,
            fallback_reason="LLM routing returned None",
            llm_url=None,  # always None here: _route_via_llm returns None on any failure path, discarding the URL it resolved internally; surfacing it would require significant refactoring of the return signature
            routing_prompt_version=_llm_routing_prompt_version,
        )
        logger.debug("LLM routing returned None, falling through to fuzzy matching")

    # Attempt intelligent routing via AgentRouter
    router = _get_router()
    selected_agent = DEFAULT_AGENT
    confidence = 0.0
    reasoning = "Fallback: no router available"
    routing_policy = RoutingPolicy.FALLBACK_DEFAULT
    domain = ""
    purpose = ""

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
                    # Low confidence — no agent selected (empty string)
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
        confidence = 0.0
        candidates_list = []
        reasoning = f"Routing timeout ({latency_ms}ms > {timeout_ms}ms limit)"
        routing_policy = RoutingPolicy.FALLBACK_DEFAULT
        domain = ""
        purpose = ""

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
    # Capture wall-clock time before argument parsing so that interpreter
    # startup and import overhead are included in the latency budget.
    entry_time = time.time()

    if len(sys.argv) < 3:
        # Graceful degradation with fallback agent when args missing
        print(
            json.dumps(
                {
                    "selected_agent": DEFAULT_AGENT,
                    "confidence": 0.0,
                    "candidates": [],
                    "reasoning": "Fallback: missing required arguments",
                    "routing_method": RoutingMethod.LOCAL.value,
                    "routing_policy": RoutingPolicy.FALLBACK_DEFAULT.value,
                    "routing_path": RoutingPath.LOCAL.value,
                    "method": RoutingPolicy.FALLBACK_DEFAULT.value,
                    "latency_ms": 0,
                    "domain": "",
                    "purpose": "",
                    "event_attempted": False,
                }
            )
        )
        sys.exit(0)

    prompt = sys.argv[1]
    correlation_id = sys.argv[2]
    timeout_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 5000
    session_id = sys.argv[4] if len(sys.argv) > 4 else None

    result = route_via_events(
        prompt, correlation_id, timeout_ms, session_id, _start_time=entry_time
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()

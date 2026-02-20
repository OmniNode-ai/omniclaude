#!/usr/bin/env python3
"""Delegation Orchestrator — task-type routing with quality gate (OMN-2281).

Routes delegation to the appropriate handler based on TaskIntent:
  - DOCUMENT → Reasoning endpoint (Qwen-72B) with doc system prompt
  - TEST      → Code analysis endpoint (Qwen-Coder) with test system prompt
  - RESEARCH  → Code analysis endpoint (Qwen-Coder) with code-review system prompt

After receiving the handler response, runs a fast heuristic quality gate:
1. Structural check (length, error indicators, task-type markers)
2. Emits ``compliance.evaluate`` async for the advisory pipeline (non-blocking)

Falls back to Claude (delegated=False) when:
- Feature flags are not both active
- Prompt classification returns non-delegatable intent
- No endpoint is configured for the detected task type
- LLM call fails or times out
- Quality gate fails (response is malformed or too short)

Emits ``onex.evt.omniclaude.task-delegated.v1`` on both success and quality gate
failures so that success rate (golden metric >80%) can be tracked downstream.

Design constraints:
- NEVER raises from ``orchestrate_delegation()``
- All I/O is bounded (LLM call <= 7 s, emit via daemon is fire-and-forget;
  actual emit client timeout is controlled by OMNICLAUDE_EMIT_TIMEOUT env var,
  defaulting to 5 s — the hook does not block on it)
- No ``datetime.now()`` defaults in internal sub-functions — ``emitted_at`` is
  injected explicitly through the call chain; the public entrypoint
  (``orchestrate_delegation``) accepts an optional ``emitted_at`` for testing.
- Module-level imports (after path setup) allow unit tests to patch them easily
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup (module-level, idempotent)
# ---------------------------------------------------------------------------
# This file runs in the hook lib context, outside the installed package.
# Ensure the repo src/ directory is on sys.path so omniclaude.* imports work.
# Pattern mirrors local_delegation_handler.py and hook_event_adapter.py.

_SCRIPT_DIR = Path(__file__).parent
_SRC_PATH = _SCRIPT_DIR.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# Ensure lib dir (this directory) is on sys.path for emit_client_wrapper import.
_LIB_DIR = str(_SCRIPT_DIR)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

# ---------------------------------------------------------------------------
# Secret redaction (imported after path setup so secret_redactor is on sys.path)
# ---------------------------------------------------------------------------
try:
    from secret_redactor import (  # type: ignore[import-not-found]
        redact_secrets as _redact_secrets,
    )
except ImportError:
    # Minimal inline fallback covering the patterns documented in CLAUDE.md.
    import re as _re

    _INLINE_SECRET_PATTERNS: list[tuple[_re.Pattern[str], str]] = [
        (_re.compile(r"\bsk-[a-zA-Z0-9]{20,}", _re.IGNORECASE), "sk-***REDACTED***"),
        (_re.compile(r"\bAKIA[A-Z0-9]{16}", _re.IGNORECASE), "AKIA***REDACTED***"),
        (_re.compile(r"\bghp_[a-zA-Z0-9]{36}", _re.IGNORECASE), "ghp_***REDACTED***"),
        (
            _re.compile(r"\bxox[baprs]-[a-zA-Z0-9-]{10,}", _re.IGNORECASE),
            "xox*-***REDACTED***",
        ),
        (
            _re.compile(
                r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
            ),
            "-----BEGIN ***REDACTED*** PRIVATE KEY-----",
        ),
        (
            _re.compile(r"(Bearer\s+)[a-zA-Z0-9._-]{20,}", _re.IGNORECASE),
            r"\1***REDACTED***",
        ),
        (_re.compile(r"(://[^:]+:)[^@]+(@)"), r"\1***REDACTED***\2"),
    ]

    def _redact_secrets(text: str) -> str:
        result = text
        for pattern, replacement in _INLINE_SECRET_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    logger.debug(
        "secret_redactor not available; using inline fallback for prompt redaction"
    )


# ---------------------------------------------------------------------------
# Module-level imports (after path setup, with graceful fallback)
# ---------------------------------------------------------------------------
# Importing at module level allows tests to patch these names via
#   patch("delegation_orchestrator.TaskClassifier", ...)
# instead of needing to patch inside the function's local namespace.

try:
    from omniclaude.lib.task_classifier import (
        TaskClassifier,  # noqa: F401  (re-exported)
    )
except ImportError:  # pragma: no cover
    TaskClassifier = None  # type: ignore[assignment,misc]

try:
    from omniclaude.config.model_local_llm_config import (  # noqa: F401
        LlmEndpointPurpose,
        LocalLlmEndpointRegistry,
    )
except ImportError:  # pragma: no cover
    LlmEndpointPurpose = None  # type: ignore[assignment,misc]
    LocalLlmEndpointRegistry = None  # type: ignore[assignment,misc]

# Shadow validation (OMN-2283) — imported at module level so tests can patch it.
try:
    from shadow_validation import (  # type: ignore[import-not-found]
        run_shadow_validation as _run_shadow_validation,
    )
except ImportError:  # pragma: no cover
    _run_shadow_validation = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Classifier instance cache
# ---------------------------------------------------------------------------
# The module-level TaskClassifier name is already cached for test patchability.
# We additionally cache the *instance* so that repeated hook calls (one per
# user prompt) do not pay the constructor cost on every invocation.
#
# Cache invalidation: if TaskClassifier changes (e.g., a test patches it with
# a different object), _get_classifier() detects the type mismatch and
# constructs a fresh instance.  _reset_classifier_cache() is provided for
# explicit teardown in tests.

# Not thread-safe: hook execution is single-threaded by design
_cached_classifier: TaskClassifier | None = (
    None  # TaskClassifier may be None on failed import (graceful degradation)
)


def _get_classifier() -> TaskClassifier:
    """Return the cached TaskClassifier instance, creating it when necessary.

    The cache is invalidated whenever ``TaskClassifier`` itself has been
    replaced (e.g., by ``unittest.mock.patch``) so that test patches receive a
    fresh instance instead of the stale one.
    """
    global _cached_classifier
    if _cached_classifier is not None and type(_cached_classifier) is TaskClassifier:
        return _cached_classifier
    _cached_classifier = TaskClassifier()
    return _cached_classifier


def _reset_classifier_cache() -> None:
    """Reset the cached TaskClassifier instance.

    Call this in test teardown after patching ``TaskClassifier`` to ensure the
    next real (unpatched) call gets a fresh instance.
    """
    global _cached_classifier
    _cached_classifier = None


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


def _configure_logging() -> None:
    """Configure file logging when LOG_FILE is set in the environment."""
    log_file = os.environ.get("LOG_FILE", "").strip()
    if not log_file or logger.handlers:
        return
    try:
        handler = logging.FileHandler(str(Path(log_file).expanduser()))
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    except Exception:
        pass


_configure_logging()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRUTHY = frozenset(("true", "1", "yes", "on"))

# Timeout for local LLM call in seconds.  Matches local_delegation_handler.py.
_LLM_CALL_TIMEOUT_S = 7.0

# Maximum tokens requested from the local model per task type.
_MAX_TOKENS = 2048

# Maximum prompt characters sent to the local LLM endpoint.
_MAX_PROMPT_CHARS: int = 8_000

# ---------------------------------------------------------------------------
# System prompts per task type
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_DOC = (
    "You are a technical documentation expert. "
    "Generate clear, well-structured documentation including docstrings, "
    "parameter descriptions, return values, and usage examples. "
    "Format using Python docstring conventions (Args/Returns/Raises sections). "
    "Be concise but complete."
)

_SYSTEM_PROMPT_TEST = (
    "You are a Python testing expert. "
    "Generate comprehensive pytest test code with proper fixtures, "
    "descriptive test names, and clear assertions. "
    "Include edge cases and error scenarios. "
    "Use @pytest.mark.unit decorator for unit tests."
)

_SYSTEM_PROMPT_RESEARCH = (
    "You are a code review and research assistant. "
    "Provide clear, accurate explanations with relevant code examples. "
    "When reviewing code, identify issues, suggest improvements, "
    "and explain the reasoning. Be direct and technical."
)

# ---------------------------------------------------------------------------
# Handler routing table
# ---------------------------------------------------------------------------
# Maps TaskIntent value → (purpose_name, system_prompt, handler_name, min_response_len)
# purpose_name must match an LlmEndpointPurpose value (lowercase).

_HANDLER_ROUTING: dict[str, tuple[str, str, str, int]] = {
    # Each purpose string must exactly match an LlmEndpointPurpose enum value.
    # A mismatch silently causes _select_handler_endpoint() to return None.
    "document": (
        "reasoning",
        _SYSTEM_PROMPT_DOC,
        "doc_gen",
        100,
    ),  # LlmEndpointPurpose.REASONING
    "test": (
        "code_analysis",
        _SYSTEM_PROMPT_TEST,
        "test_boilerplate",
        80,
    ),  # LlmEndpointPurpose.CODE_ANALYSIS
    "research": (
        "code_analysis",
        _SYSTEM_PROMPT_RESEARCH,
        "code_review",
        60,
    ),  # LlmEndpointPurpose.CODE_ANALYSIS
}

# Module-load validation of routing table purpose names
try:
    if LlmEndpointPurpose is not None:
        _valid_purposes = {p.value for p in LlmEndpointPurpose}
        for _intent, (_purpose, *_) in _HANDLER_ROUTING.items():
            if _purpose not in _valid_purposes:
                logger.warning(
                    "HANDLER_ROUTING: intent=%r maps to unknown purpose=%r (valid: %s)",
                    _intent,
                    _purpose,
                    sorted(_valid_purposes),
                )
except Exception:
    pass

# Error phrases that indicate the model refused or couldn't complete the request.
# Checked against the first 200 characters of the response (case-insensitive).
_ERROR_INDICATORS: tuple[str, ...] = (
    "i cannot",
    "i'm unable",
    "i apologize",
    "as an ai",
    "i don't have",
    "i can't",
)

# Required markers per task type — at least one must be present.
_TASK_MARKERS: dict[str, tuple[str, ...]] = {
    "test": ("def test_", "class test", "@pytest", "assert"),
    "document": ('"""', "args:", "returns:", "parameters:"),
}


# ---------------------------------------------------------------------------
# Feature flag helpers
# ---------------------------------------------------------------------------


def _is_delegation_enabled() -> bool:
    """Return True only when both delegation feature flags are active.

    Both ``ENABLE_LOCAL_INFERENCE_PIPELINE`` and ``ENABLE_LOCAL_DELEGATION``
    must be set to a truthy value (true/1/yes/on, case-insensitive).
    """
    parent = os.environ.get("ENABLE_LOCAL_INFERENCE_PIPELINE", "").lower()
    if parent not in _TRUTHY:
        return False
    delegation = os.environ.get("ENABLE_LOCAL_DELEGATION", "").lower()
    return delegation in _TRUTHY


# ---------------------------------------------------------------------------
# Handler endpoint selection
# ---------------------------------------------------------------------------


def _select_handler_endpoint(
    intent_value: str,
) -> tuple[str, str, str, str] | None:
    """Resolve the LLM endpoint URL and metadata for the given intent.

    Looks up the routing table to find which endpoint purpose is appropriate,
    then queries LocalLlmEndpointRegistry for the configured URL.

    Args:
        intent_value: TaskIntent enum value string (e.g., "document", "test").

    Returns:
        Tuple of ``(url, model_name, system_prompt, handler_name)`` when an
        endpoint is configured, or None when no endpoint is available.
    """
    routing = _HANDLER_ROUTING.get(intent_value)
    if routing is None:
        logger.debug("No routing entry for intent=%s", intent_value)
        return None

    purpose_name, system_prompt, handler_name, _min_len = routing

    # Use module-level names (allows patching in tests).
    # If imports failed at module load, these will be None and we catch below.
    _registry_cls = LocalLlmEndpointRegistry  # noqa: F821  (defined at module level)
    _purpose_cls = LlmEndpointPurpose  # noqa: F821  (defined at module level)

    try:
        purpose = _purpose_cls(purpose_name)
        registry = _registry_cls()
        endpoint = registry.get_endpoint(purpose)
        if endpoint is not None:
            url = str(endpoint.url).rstrip("/")
            return url, endpoint.model_name, system_prompt, handler_name
        logger.debug(
            "No endpoint configured for purpose=%s (intent=%s)",
            purpose_name,
            intent_value,
        )
        return None
    except Exception as exc:
        logger.debug(
            "Endpoint resolution failed for intent=%s: %s: %s",
            intent_value,
            type(exc).__name__,
            exc,
        )
        return None


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


def _call_llm_with_system_prompt(
    prompt: str,
    endpoint_url: str,
    system_prompt: str,
    model_name: str = "local",
    timeout_s: float = _LLM_CALL_TIMEOUT_S,
) -> tuple[str, str] | None:
    """Call local LLM via OpenAI-compatible /v1/chat/completions with a system prompt.

    Args:
        prompt: User prompt to send.
        endpoint_url: Base URL of the OpenAI-compatible endpoint (no trailing slash).
        system_prompt: System-level instruction for the model.
        model_name: Model identifier to include in the request payload.
        timeout_s: HTTP request timeout in seconds.

    Returns:
        Tuple of ``(response_text, model_name)`` on success, None on any error.
    """
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not installed; delegation call skipped")
        return None

    # Truncate oversized prompts to avoid exceeding server limits.
    if len(prompt) > _MAX_PROMPT_CHARS:
        logger.debug(
            "Prompt truncated from %d to %d chars for delegation",
            len(prompt),
            _MAX_PROMPT_CHARS,
        )
        prompt = (
            prompt[:_MAX_PROMPT_CHARS]
            + f"\n[... prompt truncated at {_MAX_PROMPT_CHARS} chars ...]"
        )

    url = f"{endpoint_url}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": _MAX_TOKENS,
        "temperature": 0.3,
    }

    try:
        # httpx scalar timeout sets all four phases (connect, read, write, pool)
        # to the same value — unlike requests which only covers read.  No
        # separate connect timeout is needed; TCP connect is bounded by timeout_s.
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            logger.debug("LLM returned empty choices list")
            return None

        content: str = choices[0].get("message", {}).get("content", "")
        if not content:
            logger.debug("LLM returned empty content")
            return None

        _returned_model_name: str = data.get("model") or "local-model"
        return content, _returned_model_name

    except Exception as exc:
        logger.debug("LLM call failed: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------


def _run_quality_gate(response: str, task_type: str) -> tuple[bool, str]:
    """Run a fast heuristic quality check on the handler response.

    Checks (in order):
    1. Minimum length per task type (DOCUMENT: 100, TEST: 80, RESEARCH: 60 chars).
    2. No error indicators in the first 200 characters (case-insensitive).
    3. Task-type-specific content markers (for TEST and DOCUMENT only).

    This gate is intentionally heuristic and executes in < 5 ms.  No LLM call
    is made.  The async compliance emit (``_emit_compliance_advisory``) is the
    complement that feeds the advisory pipeline for deeper analysis.

    Args:
        response: Raw text returned by the handler LLM.
        task_type: TaskIntent value string ("document", "test", "research").

    Returns:
        Tuple of ``(passed, reason)`` where reason is an empty string when
        the gate passes, or a human-readable failure description.
    """
    routing = _HANDLER_ROUTING.get(task_type)
    min_length = routing[3] if routing else 60

    # Check 1: minimum length
    if len(response) < min_length:
        return (
            False,
            f"response too short: {len(response)} < {min_length} chars for {task_type!r}",
        )

    # Check 2: error indicators in the first 200 chars
    # Fast heuristic: check first 200 chars only. Models typically front-load
    # refusals; longer preambles may bypass this check (acceptable tradeoff for
    # a <5ms gate).
    preview = response[:200].lower()
    for indicator in _ERROR_INDICATORS:
        if indicator in preview:
            return False, f"response contains refusal indicator: {indicator!r}"

    # Check 3: task-type markers (TEST and DOCUMENT only)
    markers = _TASK_MARKERS.get(task_type)
    if markers:
        response_lower = response.lower()
        if not any(marker in response_lower for marker in markers):
            return (
                False,
                f"response missing expected markers for {task_type!r}: "
                f"none of {markers} found",
            )

    return True, ""


# ---------------------------------------------------------------------------
# Compliance advisory emit (async, non-blocking)
# ---------------------------------------------------------------------------


def _emit_compliance_advisory(
    response: str,
    task_type: str,
    correlation_id: str,
    session_id: str,
) -> None:
    """Emit a compliance.evaluate event for the advisory pipeline (fire-and-forget).

    Sends the handler response to the compliance advisory pipeline
    (OMN-2340 picks it up next turn). This is non-blocking — the hook must
    never wait for a compliance result within its own execution window.

    Failures are silently swallowed; compliance emit errors must never
    block or crash the delegation path.

    Args:
        response: Handler response text.
        task_type: TaskIntent value string.
        correlation_id: Correlation ID for tracing.
        session_id: Session identifier.
    """
    try:
        from emit_client_wrapper import emit_event  # type: ignore[import-not-found]

        from omniclaude.hooks.topics import TopicBase

        # INTENTIONAL (ADR-005, reviewed): sending model-generated output to an
        # access-restricted cmd.omniintelligence.* topic is correct per CLAUDE.md —
        # cmd topics are the preferred channel for content that may contain model
        # echoes of user input.  The ``response[:500]`` truncation caps the echo
        # blast radius to 500 chars, which is the agreed privacy boundary for this
        # topic.  This is NOT an oversight; the alternative (evt.*) would be wrong
        # because evt topics have broad access and this content could echo user input.
        emit_event(
            event_type=TopicBase.COMPLIANCE_EVALUATE,
            payload={
                "response": response[:500],  # Truncate to stay within payload limits
                "task_type": task_type,
                "correlation_id": correlation_id,
                "session_id": session_id,
                "source": "delegation_orchestrator",
            },
            # timeout_ms is ignored by emit_event — actual timeout is OMNICLAUDE_EMIT_TIMEOUT (default 5 s)
        )
    except Exception as exc:
        logger.debug("Compliance advisory emit failed (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# Delegation event emit
# ---------------------------------------------------------------------------


def _emit_delegation_event(
    *,
    session_id: str,
    correlation_id: str,
    task_type: str,
    handler_name: str,
    model_name: str,
    quality_gate_passed: bool,
    quality_gate_reason: str,
    delegation_success: bool,
    savings_usd: float,
    latency_ms: int,
    emitted_at: datetime,
) -> None:
    """Emit onex.evt.omniclaude.task-delegated.v1 for observability (fire-and-forget).

    This function never raises.  Failure to emit is logged at DEBUG level and
    silently swallowed so that delegation result is always returned to the caller.

    Args:
        session_id: Session identifier.
        correlation_id: Correlation ID for distributed tracing.
        task_type: TaskIntent value string.
        handler_name: Endpoint purpose name used (doc_gen, test_boilerplate, code_review).
        model_name: Model identifier returned by the endpoint.
        quality_gate_passed: Whether the quality gate passed.
        quality_gate_reason: Failure reason (empty string when gate passed).
        delegation_success: Whether the delegation produced a usable response.
        savings_usd: Estimated cost savings in USD.
        latency_ms: Total delegation wall-clock time in milliseconds.
        emitted_at: Timestamp to use for the event (injected by caller, no datetime.now()).
    """
    try:
        from uuid import UUID, uuid4

        from omniclaude.hooks.schemas import ModelTaskDelegatedPayload
        from omniclaude.hooks.topics import TopicBase

        # Validate correlation_id is a UUID; generate a placeholder if not.
        try:
            corr_uuid = UUID(correlation_id)
        except (ValueError, AttributeError):
            corr_uuid = uuid4()
            logger.debug(
                "correlation_id %r is not a UUID; generated placeholder %s",
                correlation_id,
                corr_uuid,
            )

        payload = ModelTaskDelegatedPayload(
            session_id=session_id or "unknown",
            correlation_id=corr_uuid,
            emitted_at=emitted_at,
            task_type=task_type,
            handler_used=handler_name,
            model_used=model_name,
            quality_gate_passed=quality_gate_passed,
            quality_gate_reason=quality_gate_reason[:200]
            if quality_gate_reason
            else None,
            delegation_success=delegation_success,
            estimated_savings_usd=max(0.0, savings_usd),
            latency_ms=max(0, latency_ms),
        )

        from emit_client_wrapper import emit_event

        emit_event(
            event_type=TopicBase.TASK_DELEGATED,
            payload=payload.model_dump(mode="json"),
            # timeout_ms is ignored by emit_event — actual timeout is OMNICLAUDE_EMIT_TIMEOUT (default 5 s)
        )
        logger.debug(
            "Emitted task-delegated event: task=%s handler=%s success=%s",
            task_type,
            handler_name,
            delegation_success,
        )
    except Exception as exc:
        logger.debug("task-delegated event emission failed (non-critical): %s", exc)


# ---------------------------------------------------------------------------
# Main orchestration entry point
# ---------------------------------------------------------------------------


def orchestrate_delegation(
    *,
    prompt: str,
    session_id: str = "",
    correlation_id: str,
    emitted_at: datetime | None = None,
) -> dict[str, Any]:
    """Orchestrate delegation with task-type routing and quality gate.

    Decision tree:
    1. Feature flags off                -> delegated=False, reason="feature_disabled"
       (delegation event emitted with delegation_success=False)
    2. Classification fails / raises    -> delegated=False
       (delegation event emitted with delegation_success=False)
    3. Not delegatable                  -> delegated=False
       (delegation event emitted with delegation_success=False)
    4. No endpoint for task type        -> delegated=False, reason="pre_gate:no_endpoint_configured"
       (delegation event emitted with delegation_success=False)
    5. LLM call fails                   -> delegated=False, reason="pre_gate:llm_call_failed"
       (delegation event emitted with delegation_success=False)
    6. Quality gate fails               -> delegated=False, reason="quality_gate_failed"
       (delegation event emitted with quality_gate_passed=False, delegation_success=False)
    7. All gates pass                   -> delegated=True
       (delegation event emitted with delegation_success=True)

    This function NEVER raises.  All errors are caught and returned as
    ``delegated=False`` so the hook always falls back to Claude safely.

    Args:
        prompt: Raw user prompt text.
        session_id: Session identifier (empty string when not known).
        correlation_id: Correlation ID for distributed tracing.
        emitted_at: Timestamp for the delegation event. When None, defaults to
            ``datetime.now(UTC)``. Inject a fixed value in tests for deterministic
            assertions.

    Returns:
        Dict with at minimum ``{"delegated": bool}``.
        When delegated=True: also includes "response", "model", "confidence",
        "intent", "savings_usd", "latency_ms", "handler", "quality_gate_passed".
        When delegated=False: also includes "reason".
    """
    emitted_at = emitted_at or datetime.now(UTC)
    start_time = time.time()

    try:
        # Gate 1: Feature flags
        if not _is_delegation_enabled():
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type="unknown",
                handler_name="unknown",
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason="feature_disabled",
                delegation_success=False,
                savings_usd=0.0,
                latency_ms=int((time.time() - start_time) * 1000),
                emitted_at=emitted_at,
            )
            return {"delegated": False, "reason": "feature_disabled"}

        # Gate 2: Classification
        try:
            classifier = _get_classifier()
            score = classifier.is_delegatable(prompt)
        except Exception as exc:
            logger.debug("Classification failed: %s", exc)
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type="unknown",
                handler_name="unknown",
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason=f"classification_error: {type(exc).__name__}",
                delegation_success=False,
                savings_usd=0.0,
                latency_ms=int((time.time() - start_time) * 1000),
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": f"classification_error: {type(exc).__name__}",
            }

        if not score.delegatable:
            reasons = "; ".join(score.reasons) if score.reasons else "not delegatable"
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type="unknown",
                handler_name="unknown",
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason=reasons,
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=int((time.time() - start_time) * 1000),
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": reasons,
                "confidence": score.confidence,
            }

        # Extract the intent value string for routing (reuse existing classifier instance).
        try:
            ctx = classifier.classify(prompt)
            intent_value = (
                ctx.primary_intent.value
            )  # e.g., "document", "test", "research"
        except Exception as exc:
            logger.debug("Intent value extraction failed: %s", exc)
            latency_ms = int((time.time() - start_time) * 1000)
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type="unknown",
                handler_name="unknown",
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason=f"pre_gate:intent_extraction_error: {type(exc).__name__}",
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=latency_ms,
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": f"pre_gate:intent_extraction_error: {type(exc).__name__}",
            }

        # Gate 3: Endpoint selection for this specific task type
        endpoint_result = _select_handler_endpoint(intent_value)
        if endpoint_result is None:
            latency_ms = int((time.time() - start_time) * 1000)
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type=intent_value,
                handler_name="unknown",
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason="pre_gate:no_endpoint_configured",
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=latency_ms,
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": "pre_gate:no_endpoint_configured",
                "confidence": score.confidence,
                "intent": intent_value,
            }

        endpoint_url, model_name, system_prompt, handler_name = endpoint_result

        # Gate 4: LLM call with task-specific system prompt
        # Redact secrets from the prompt before forwarding to the local LLM
        # (CLAUDE.md invariant: "Automatic secret redaction").
        try:
            redacted_prompt = _redact_secrets(prompt)
        except Exception as exc:
            logger.debug(
                "Secret redaction failed; aborting delegation to protect secrets: %s",
                exc,
            )
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type=intent_value,
                handler_name=handler_name,
                model_name="unknown",
                quality_gate_passed=False,
                quality_gate_reason="pre_gate:redaction_error",
                delegation_success=False,
                savings_usd=0.0,
                latency_ms=int((time.time() - start_time) * 1000),
                emitted_at=emitted_at,
            )
            return {"delegated": False, "reason": "redaction_error"}

        llm_result = _call_llm_with_system_prompt(
            redacted_prompt, endpoint_url, system_prompt, model_name
        )
        if llm_result is None:
            latency_ms = int((time.time() - start_time) * 1000)
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type=intent_value,
                handler_name=handler_name,
                model_name=model_name,
                quality_gate_passed=False,
                quality_gate_reason="pre_gate:llm_call_failed",
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=latency_ms,
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": "pre_gate:llm_call_failed",
                "confidence": score.confidence,
                "intent": intent_value,
            }

        response_text, actual_model_name = llm_result
        if not response_text or not response_text.strip():
            latency_ms = int((time.time() - start_time) * 1000)
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type=intent_value,
                handler_name=handler_name,
                model_name=actual_model_name or model_name,
                quality_gate_passed=False,
                quality_gate_reason="pre_gate:empty_response",
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=latency_ms,
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": "pre_gate:empty_response",
                "confidence": score.confidence,
                "intent": intent_value,
            }

        # Normalise model name (the endpoint may return None for the model field)
        if not actual_model_name or not actual_model_name.strip():
            actual_model_name = model_name or "local-model"

        # Gate 5: Quality gate
        gate_passed, gate_reason = _run_quality_gate(response_text, intent_value)
        latency_ms = int((time.time() - start_time) * 1000)

        if not gate_passed:
            logger.debug(
                "Quality gate failed: reason=%s task=%s handler=%s",
                gate_reason,
                intent_value,
                handler_name,
            )
            _emit_delegation_event(
                session_id=session_id,
                correlation_id=correlation_id,
                task_type=intent_value,
                handler_name=handler_name,
                model_name=actual_model_name,
                quality_gate_passed=False,
                quality_gate_reason=gate_reason,
                delegation_success=False,
                savings_usd=score.estimated_savings_usd,
                latency_ms=latency_ms,
                emitted_at=emitted_at,
            )
            return {
                "delegated": False,
                "reason": "quality_gate_failed",
                "quality_gate_reason": gate_reason,
                "confidence": score.confidence,
                "intent": intent_value,
            }

        # All gates passed — emit compliance advisory and delegation event.
        _emit_compliance_advisory(
            response_text, intent_value, correlation_id, session_id
        )

        # Shadow validation (OMN-2283): sample 5-10% of successful delegations
        # and asynchronously compare local model output against Claude.
        # This is non-blocking — the response is returned to the user immediately.
        _shadow_fn = _run_shadow_validation  # module-level name, patchable in tests
        if _shadow_fn is not None:
            try:
                _shadow_fn(
                    prompt=redacted_prompt,
                    local_response=response_text,
                    local_model=actual_model_name,
                    session_id=session_id,
                    correlation_id=correlation_id,
                    task_type=intent_value,
                    emitted_at=emitted_at,
                )
            except ValueError as _shadow_val_err:
                # ValueError from shadow validation is a programming error
                # (e.g. emitted_at is None) — log at WARNING, not DEBUG.
                logger.warning(
                    "Shadow validation rejected call (programming error): %s",
                    _shadow_val_err,
                )
            except Exception as _shadow_exc:
                # Other errors (network, import, etc.) are non-critical
                logger.debug(
                    "Shadow validation call raised unexpectedly (non-critical): %s: %s",
                    type(_shadow_exc).__name__,
                    _shadow_exc,
                )

        _emit_delegation_event(
            session_id=session_id,
            correlation_id=correlation_id,
            task_type=intent_value,
            handler_name=handler_name,
            model_name=actual_model_name,
            quality_gate_passed=True,
            quality_gate_reason="",
            delegation_success=True,
            savings_usd=score.estimated_savings_usd,
            latency_ms=latency_ms,
            emitted_at=emitted_at,
        )

        logger.info(
            "Orchestrated delegation succeeded: model=%s intent=%s handler=%s "
            "confidence=%.3f latency=%dms correlation=%s",
            actual_model_name,
            intent_value,
            handler_name,
            score.confidence,
            latency_ms,
            correlation_id,
        )

        # Format the response with visible attribution (mirrors local_delegation_handler pattern).
        display_model_name = actual_model_name
        attribution = f"[Local Model Response - {display_model_name}]"
        reasons_summary = "; ".join(score.reasons) if score.reasons else ""
        savings_str = (
            f"~${score.estimated_savings_usd:.4f}"
            if score.estimated_savings_usd > 0
            else "local inference"
        )
        formatted_response = (
            f"{attribution}\n\n"
            f"{response_text}\n\n"
            f"---\n"
            f"Delegated via local model: confidence={score.confidence:.3f}, "
            f"savings={savings_str}, handler={handler_name}. "
            f"Reason: {reasons_summary}"
        )

        return {
            "delegated": True,
            "response": formatted_response,
            "model": actual_model_name,
            "confidence": score.confidence,
            "intent": intent_value,
            "savings_usd": score.estimated_savings_usd,
            "latency_ms": latency_ms,
            "handler": handler_name,
            "quality_gate_passed": True,
        }

    except Exception as exc:
        logger.debug(
            "orchestrate_delegation unexpected error: %s: %s", type(exc).__name__, exc
        )
        return {"delegated": False, "reason": "orchestrator_error", "error": str(exc)}

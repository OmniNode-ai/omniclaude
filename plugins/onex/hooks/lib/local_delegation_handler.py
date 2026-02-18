#!/usr/bin/env python3
"""Local Model Delegation Handler.

Implements the delegation dispatch path introduced in OMN-2271.

When ENABLE_LOCAL_DELEGATION=true and ENABLE_LOCAL_INFERENCE_PIPELINE=true,
this module:

1. Classifies the user prompt via TaskClassifier.is_delegatable().
2. If delegatable (confidence > 0.9, allowed task type, no vision/tool signals):
   - Resolves the appropriate local LLM endpoint from LocalLlmEndpointRegistry.
   - Calls the endpoint via OpenAI-compatible /v1/chat/completions.
   - Returns a ModelDelegatedResponse-formatted string for injection.
3. Otherwise returns None to let the normal Claude path proceed.

Feature flags (both required):
    ENABLE_LOCAL_INFERENCE_PIPELINE=true   (parent gate, shared with other features)
    ENABLE_LOCAL_DELEGATION=true           (specific delegation flag)

Conservative design:
    Any error, timeout, or missing configuration causes this module to return
    None immediately. Claude is NEVER bypassed on uncertainty — only when all
    four delegation gates pass AND the LLM call succeeds.

Usage (called from user-prompt-submit.sh):
    printf '%s' "$PROMPT_B64" | python3 local_delegation_handler.py --prompt-stdin <correlation_id>

    The --prompt-stdin flag reads the base64-encoded prompt from stdin so it
    never appears in the process table (ps aux / /proc/PID/cmdline).

    Outputs one of:
    - JSON with {"delegated": true, "response": "<formatted text>", ...}
    - JSON with {"delegated": false, "reason": "<explanation>"}
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup (module-level, idempotent)
# ---------------------------------------------------------------------------
# This file runs in the hook lib context, outside the installed package.
# Ensure the repo src/ directory is on sys.path so omniclaude.* imports work.
# Pattern mirrors hook_event_adapter.py and session_intelligence.py.

_SCRIPT_DIR = Path(__file__).parent
_SRC_PATH = _SCRIPT_DIR.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))


def _ensure_src_on_path() -> None:
    """Ensure src/ is on sys.path (idempotent, no-op after first call)."""
    if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
        sys.path.insert(0, str(_SRC_PATH))


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
# Honor LOG_FILE env var so hook logs are written when configured.
# Mirrors the pattern used by other hooks in this lib.

_LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"


def _configure_logging() -> None:
    """Configure file logging when LOG_FILE is set in the environment.

    Attaches a FileHandler to the module logger only if LOG_FILE is set
    and no handler has been added yet (avoids duplicates on re-import).
    Sets propagate=False so records don't also appear on stderr.
    """
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
        # Never fail hook startup due to logging misconfiguration.
        pass


_configure_logging()

# ---------------------------------------------------------------------------
# Feature flag resolution
# ---------------------------------------------------------------------------

_TRUTHY = frozenset(("true", "1", "yes", "on"))

# Timeout for local LLM call in seconds.
# Kept below the 8s shell-level timeout so httpx fails cleanly before SIGALRM
# kills the process. Worst-case sync path: routing 5s + injection 1s + advisory
# 1s + delegation 8s = ~15s, well under the 41s that the previous 35s timeout produced.
_LLM_CALL_TIMEOUT_S = 7.0

# Maximum tokens requested from the local model.
# Delegation targets bounded text-only tasks (documentation, tests, research)
# where responses rarely exceed this limit.
_MAX_TOKENS = 2048

# Attribution prefix injected into every delegated response.
_ATTRIBUTION_HEADER = "[Local Model Response - {model}]"


def _is_delegation_enabled() -> bool:
    """Check whether local delegation feature flags are active.

    Both flags must be set to truthy values:
    - ENABLE_LOCAL_INFERENCE_PIPELINE (parent gate)
    - ENABLE_LOCAL_DELEGATION         (delegation-specific gate)

    Returns:
        True only when both flags are truthy.
    """
    parent = os.environ.get("ENABLE_LOCAL_INFERENCE_PIPELINE", "").lower()
    if parent not in _TRUTHY:
        return False
    delegation = os.environ.get("ENABLE_LOCAL_DELEGATION", "").lower()
    return delegation in _TRUTHY


def _get_delegate_endpoint_url() -> str | None:
    """Resolve the LLM endpoint URL to use for delegation.

    Uses LocalLlmEndpointRegistry with LlmEndpointPurpose.GENERAL as the
    primary purpose for delegation tasks (documentation, tests, research).
    Falls back to the LLM_QWEN_14B_URL environment variable directly if the
    registry is not available.

    Returns:
        URL string (no trailing slash) or None if unconfigured.
    """
    try:
        _ensure_src_on_path()

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry()
        endpoint = registry.get_endpoint(LlmEndpointPurpose.GENERAL)
        if endpoint is not None:
            return str(endpoint.url).rstrip("/")
        logger.debug("No GENERAL endpoint configured in registry")
        return None
    except ImportError:
        logger.debug("LocalLlmEndpointRegistry not importable, trying direct env var")
    except Exception as exc:
        logger.debug("Registry lookup failed: %s", exc)

    # Fallback: use LLM_QWEN_14B_URL directly (Qwen2.5-14B on Mac Mini)
    url = os.environ.get("LLM_QWEN_14B_URL", "").strip().rstrip("/")
    return url if url else None


def _classify_prompt(prompt: str) -> Any:
    """Classify prompt for delegation suitability.

    Adds src to sys.path if needed so TaskClassifier can be imported from
    the hook lib context.

    Returns:
        ModelDelegationScore from TaskClassifier.is_delegatable().
    """
    _ensure_src_on_path()

    from omniclaude.lib.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    return classifier.is_delegatable(prompt)


def _call_local_llm(
    prompt: str,
    endpoint_url: str,
    timeout_s: float = _LLM_CALL_TIMEOUT_S,
) -> tuple[str, str] | None:
    """Call local LLM via OpenAI-compatible /v1/chat/completions endpoint.

    Uses httpx for HTTP transport (optional dependency; graceful failure if
    not installed).

    Args:
        prompt: User prompt to send.
        endpoint_url: Base URL of the OpenAI-compatible endpoint.
        timeout_s: HTTP request timeout in seconds.

    Returns:
        Tuple of (response_text, model_name) on success.
        None on any error (network, timeout, parse failure, etc.).
    """
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not installed; local delegation call skipped")
        return None

    url = f"{endpoint_url}/v1/chat/completions"
    payload = {
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": _MAX_TOKENS,
        "temperature": 0.3,
    }

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            logger.debug("LLM returned empty choices list")
            return None

        content = choices[0].get("message", {}).get("content", "")
        if not content:
            logger.debug("LLM returned empty content")
            return None

        model_name = data.get("model", "local-model")
        return content, model_name

    except httpx.TimeoutException:
        logger.debug("LLM call timed out after %.1fs", timeout_s)
        return None
    except httpx.HTTPStatusError as exc:
        logger.debug("LLM returned HTTP %d: %s", exc.response.status_code, exc)
        return None
    except Exception as exc:
        logger.debug("LLM call failed: %s: %s", type(exc).__name__, exc)
        return None


def _format_delegated_response(
    response_text: str,
    model_name: str,
    delegation_score: Any,
    prompt: str,
) -> str:
    """Format the local model response as ModelDelegatedResponse.

    Adds visible attribution header so users know the response came from a
    local model. This satisfies the "visible attribution" requirement from
    the ticket.

    Format:
        [Local Model Response - <model>]

        <response text>

        ---
        Delegated: confidence=<n>, task=<intent>, savings=~$<n>

    Args:
        response_text: Raw text from the local LLM.
        model_name: Model identifier returned by the endpoint.
        delegation_score: Classification result with reasons/savings.
        prompt: Original user prompt (used for context).

    Returns:
        Formatted attribution block ready for injection into Claude's context.
    """
    safe_model_name = model_name.replace("{", "{{").replace("}", "}}")
    header = _ATTRIBUTION_HEADER.format(model=safe_model_name)
    reasons_summary = "; ".join(delegation_score.reasons)
    savings_str = (
        f"~${delegation_score.estimated_savings_usd:.4f}"
        if delegation_score.estimated_savings_usd > 0
        else "local inference"
    )

    return (
        f"{header}\n\n"
        f"{response_text}\n\n"
        f"---\n"
        f"Delegated via local model: confidence={delegation_score.confidence:.3f}, "
        f"savings={savings_str}. "
        f"Reason: {reasons_summary}"
    )


def handle_delegation(
    prompt: str,
    correlation_id: str,
) -> dict[str, object]:
    """Entry point: attempt local delegation for the given prompt.

    Decision tree:
    1. Feature flags off → delegated=false immediately.
    2. Classify prompt → not delegatable → delegated=false.
    3. Resolve endpoint URL → none configured → delegated=false.
    4. Call local LLM → failure → delegated=false (Claude takes over).
    5. Format and return delegated response.

    This function NEVER raises. All errors are caught and returned as
    delegated=false so the hook always falls back to Claude safely.

    Args:
        prompt: Raw user prompt text.
        correlation_id: Correlation ID for tracing/logging.

    Returns:
        Dict with at minimum {"delegated": bool}.
        When delegated=True: also includes "response", "model", "confidence",
        "intent", "savings_usd", "latency_ms".
        When delegated=False: also includes "reason".
    """
    start_time = time.time()

    # Gate 1: Feature flags
    if not _is_delegation_enabled():
        return {
            "delegated": False,
            "reason": "feature_disabled",
        }

    # Gate 2: Classification
    try:
        score = _classify_prompt(prompt)
    except Exception as exc:
        logger.debug("Classification failed: %s", exc)
        return {
            "delegated": False,
            "reason": f"classification_error: {type(exc).__name__}",
        }

    if not score.delegatable:
        reasons = "; ".join(score.reasons) if score.reasons else "not delegatable"
        return {
            "delegated": False,
            "reason": reasons,
            "confidence": score.confidence,
        }

    # Gate 3: Endpoint resolution
    endpoint_url = _get_delegate_endpoint_url()
    if not endpoint_url:
        return {
            "delegated": False,
            "reason": "no_endpoint_configured",
            "confidence": score.confidence,
        }

    # Gate 4: LLM call
    result = _call_local_llm(prompt, endpoint_url)
    if result is None:
        return {
            "delegated": False,
            "reason": "llm_call_failed",
            "confidence": score.confidence,
        }

    response_text, model_name = result
    latency_ms = int((time.time() - start_time) * 1000)

    formatted = _format_delegated_response(
        response_text=response_text,
        model_name=model_name,
        delegation_score=score,
        prompt=prompt,
    )

    logger.info(
        "Delegation succeeded: model=%s confidence=%.3f latency=%dms correlation=%s",
        model_name,
        score.confidence,
        latency_ms,
        correlation_id,
    )

    return {
        "delegated": True,
        "response": formatted,
        "model": model_name,
        "confidence": score.confidence,
        "intent": score.delegate_to_model,
        "savings_usd": score.estimated_savings_usd,
        "latency_ms": latency_ms,
    }


def main() -> None:
    """CLI entry point for user-prompt-submit.sh.

    Preferred usage (avoids exposing the prompt in the process table):
        printf '%s' "$PROMPT_B64" | python3 local_delegation_handler.py --prompt-stdin <correlation_id>

    Legacy usage (kept for backward-compat with tests; do NOT use in production):
        python3 local_delegation_handler.py <prompt_b64> <correlation_id>

    When --prompt-stdin is the first argument, the base64-encoded prompt is read
    from stdin instead of argv[1], so the full prompt never appears in
    /proc/PID/cmdline or `ps aux` output.

    Always exits 0. Non-zero exit would block the hook.

    Note: Python 3.12+ is guaranteed by the project's requires-python
    constraint and by find_python() in common.sh — no runtime check needed.
    """
    args = sys.argv[1:]

    if args and args[0] == "--prompt-stdin":
        # Secure path: read base64-encoded prompt from stdin.
        # Expected remaining args: [correlation_id]
        if len(args) < 2:
            print(json.dumps({"delegated": False, "reason": "missing_args"}))
            sys.exit(0)
        correlation_id = args[1]
        try:
            raw_b64 = sys.stdin.read().strip()
            prompt = base64.b64decode(raw_b64).decode("utf-8", "replace")
        except Exception:
            print(json.dumps({"delegated": False, "reason": "prompt_decode_error"}))
            sys.exit(0)
    else:
        # Legacy path: prompt_b64 passed as argv[1].
        # Kept only for unit-test callers; not used by the hook script.
        if len(args) < 2:
            print(json.dumps({"delegated": False, "reason": "missing_args"}))
            sys.exit(0)
        try:
            prompt = base64.b64decode(args[0]).decode("utf-8", "replace")
        except Exception:
            print(json.dumps({"delegated": False, "reason": "prompt_decode_error"}))
            sys.exit(0)
        correlation_id = args[1]

    try:
        result = handle_delegation(prompt, correlation_id)
    except Exception as exc:
        # Belt-and-suspenders: handle_delegation should never raise, but
        # if it does, return a safe fallback.
        logger.debug("Unexpected error in handle_delegation: %s", exc)
        result = {
            "delegated": False,
            "reason": f"unexpected_error: {type(exc).__name__}",
        }

    print(json.dumps(result))
    sys.exit(0)


if __name__ == "__main__":
    main()

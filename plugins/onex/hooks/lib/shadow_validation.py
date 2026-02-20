#!/usr/bin/env python3
"""Shadow Validation — async quality comparison for delegated tasks (OMN-2283).

Samples 5-10% of delegated tasks and calls Claude (shadow model) asynchronously
to compare the local model response against Claude's response.  The local model
response is returned to the user immediately; shadow validation runs in a
background thread and never blocks the hook.

Architecture:
    - Shadow call is non-blocking (threading.Thread, daemon=True)
    - Sampling decision is made via deterministic hash of the correlation_id so
      the same task is never double-counted in tests
    - Comparison metrics: length divergence, keyword overlap (Jaccard), structural
      match (code block presence)
    - Divergence events are emitted to onex.evt.omniclaude.delegation-shadow-comparison.v1
    - Exit criteria: auto-disable when pass rate >= 95% for 30 consecutive days
      (tracked via SHADOW_CONSECUTIVE_PASSING_DAYS env var written by a reducer)

Feature flags:
    ENABLE_SHADOW_VALIDATION=true        (master switch)
    SHADOW_SAMPLE_RATE=0.07              (float 0.0-1.0, default 0.07 = 7%)
    SHADOW_EXIT_THRESHOLD=0.95           (float, default 0.95)
    SHADOW_EXIT_WINDOW_DAYS=30           (int, default 30)
    SHADOW_CONSECUTIVE_PASSING_DAYS=0    (int, updated by exit-criteria reducer)
    SHADOW_MODEL=claude-sonnet-4-6       (model identifier for shadow calls)
    SHADOW_CLAUDE_API_KEY=<key>          (Anthropic API key for shadow calls)
    SHADOW_CLAUDE_BASE_URL=              (optional override, default https://api.anthropic.com)
    SHADOW_CALL_TIMEOUT_S=30             (float, default 30 seconds)
    SHADOW_MAX_TOKENS=2048               (int, max tokens for shadow API call, default 2048)

Design constraints:
    - Does not raise except ValueError when emitted_at is None (by design —
      callers must inject timestamps; no silent datetime.now() fallback allowed)
    - All I/O (Claude API call, event emit) is bounded and non-blocking
    - Module-level imports allow unit tests to patch them easily
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# sys.path setup (module-level, idempotent)
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).parent
_SRC_PATH = _SCRIPT_DIR.parent.parent.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

_LIB_DIR = str(_SCRIPT_DIR)
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

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

# Default sampling rate (7%).  Overridden by SHADOW_SAMPLE_RATE env var.
_DEFAULT_SAMPLE_RATE: float = 0.07

# Default timeout for the shadow Claude API call.
_DEFAULT_SHADOW_TIMEOUT_S: float = 30.0

# Default max tokens for the shadow Claude API call.
_DEFAULT_SHADOW_MAX_TOKENS: int = 2048

# Default shadow model identifier.
_DEFAULT_SHADOW_MODEL: str = "claude-sonnet-4-6"

# Default exit criteria thresholds.
_DEFAULT_EXIT_THRESHOLD: float = 0.95
_DEFAULT_EXIT_WINDOW_DAYS: int = 30

# English stop-words to exclude from keyword overlap computation.
# A minimal set covering the most common words to reduce noise.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "being",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "get",
        "has",
        "have",
        "if",
        "in",
        "is",
        "it",
        "its",
        "not",
        "of",
        "on",
        "or",
        "should",
        "so",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "was",
        "we",
        "were",
        "which",
        "with",
        "would",
        "you",
    }
)

# Minimum significant-word overlap score to pass the quality gate.
_MIN_KEYWORD_OVERLAP: float = 0.35

# Maximum length divergence ratio to pass the quality gate.
_MAX_LENGTH_DIVERGENCE: float = 0.70

# Regex to detect code blocks (``` or 4-space indented lines with def/class).
_CODE_BLOCK_RE = re.compile(r"```|^\s{4}(?:def |class |import |from )", re.MULTILINE)

# Local URL prefixes that are allowed to use plain HTTP (loopback only).
# Used in both run_shadow_validation (primary enforcement) and
# _call_shadow_claude (defense-in-depth secondary guard).
# 0.0.0.0 is intentionally excluded: it is a wildcard bind address (all
# interfaces), not a loopback, and is externally routable on most OSes.
_LOCAL_PREFIXES: tuple[str, ...] = (
    "http://localhost",
    "http://127.0.0.1",
    "http://[::1]",
)


# ---------------------------------------------------------------------------
# Feature flag helpers
# ---------------------------------------------------------------------------


def _is_shadow_validation_enabled() -> bool:
    """Return True when shadow validation is enabled and not auto-disabled.

    Auto-disable occurs when SHADOW_CONSECUTIVE_PASSING_DAYS >=
    SHADOW_EXIT_WINDOW_DAYS.  The env var is updated by the exit-criteria
    reducer and checked here to prevent unnecessary shadow calls after the
    quality bar has been met for the full window.
    """
    flag = os.environ.get("ENABLE_SHADOW_VALIDATION", "").lower()
    if flag not in _TRUTHY:
        return False

    # Check exit criteria (auto-disable)
    try:
        consecutive = int(os.environ.get("SHADOW_CONSECUTIVE_PASSING_DAYS", "0"))
        window = int(
            os.environ.get("SHADOW_EXIT_WINDOW_DAYS", str(_DEFAULT_EXIT_WINDOW_DAYS))
        )
        if consecutive >= window:
            logger.debug(
                "Shadow validation auto-disabled: consecutive_passing_days=%d >= window=%d",
                consecutive,
                window,
            )
            return False
    except (ValueError, TypeError):
        pass

    return True


def _get_sample_rate() -> float:
    """Return the configured sampling rate, clamped to [0.0, 1.0]."""
    try:
        rate = float(os.environ.get("SHADOW_SAMPLE_RATE", str(_DEFAULT_SAMPLE_RATE)))
        return max(0.0, min(1.0, rate))
    except (ValueError, TypeError):
        return _DEFAULT_SAMPLE_RATE


def _get_exit_threshold() -> float:
    """Return the configured exit threshold, clamped to [0.0, 1.0]."""
    try:
        threshold = float(
            os.environ.get("SHADOW_EXIT_THRESHOLD", str(_DEFAULT_EXIT_THRESHOLD))
        )
        return max(0.0, min(1.0, threshold))
    except (ValueError, TypeError):
        return _DEFAULT_EXIT_THRESHOLD


def _get_exit_window_days() -> int:
    """Return the configured exit window in days (minimum 1)."""
    try:
        days = int(
            os.environ.get("SHADOW_EXIT_WINDOW_DAYS", str(_DEFAULT_EXIT_WINDOW_DAYS))
        )
        return max(1, days)
    except (ValueError, TypeError):
        return _DEFAULT_EXIT_WINDOW_DAYS


def _get_consecutive_passing_days() -> int:
    """Return the number of consecutive passing days from env (for event payload)."""
    try:
        return max(0, int(os.environ.get("SHADOW_CONSECUTIVE_PASSING_DAYS", "0")))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Sampling decision
# ---------------------------------------------------------------------------


def _should_sample(correlation_id: str, sample_rate: float) -> bool:
    """Determine whether this task should be shadow-validated.

    Uses a deterministic hash of the correlation_id so the same task is
    consistently sampled or skipped (useful for reproducible test assertions).

    Args:
        correlation_id: Unique identifier for this delegation invocation.
        sample_rate: Fraction of tasks to sample. Values <= 0.0 always skip;
            values >= 1.0 always sample. Callers should use _get_sample_rate()
            to pre-clamp the value to [0.0, 1.0].

    Returns:
        True when this task falls within the sample.
    """
    if sample_rate <= 0.0:
        return False
    if sample_rate >= 1.0:
        return True

    # 4-byte unsigned int from the first 4 bytes of the SHA-256 hash
    digest = hashlib.sha256(correlation_id.encode("utf-8", "replace")).digest()
    bucket = int.from_bytes(digest[:4], "big") / (2**32)
    return bucket < sample_rate


# ---------------------------------------------------------------------------
# Output comparison
# ---------------------------------------------------------------------------


def _extract_keywords(text: str) -> frozenset[str]:
    """Extract significant words from text, excluding stop-words.

    Splits on non-alphanumeric characters, lower-cases, and removes
    stop-words and single-character tokens.

    Args:
        text: Raw response text.

    Returns:
        Frozenset of significant lowercase words.
    """
    words = re.split(r"[^a-zA-Z0-9_]+", text.lower())
    return frozenset(w for w in words if len(w) > 1 and w not in _STOP_WORDS)


def _jaccard_similarity(a: frozenset[str], b: frozenset[str]) -> float:
    """Compute Jaccard similarity between two word sets.

    Args:
        a: First word set.
        b: Second word set.

    Returns:
        Float in [0.0, 1.0] where 1.0 = identical sets.
    """
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _has_code_block(text: str) -> bool:
    """Return True when the text contains a recognizable code block.

    Checks for triple-backtick fences OR 4-space indented code with Python
    keywords.

    Args:
        text: Response text to inspect.

    Returns:
        True when a code block is detected.
    """
    return bool(_CODE_BLOCK_RE.search(text))


def compare_responses(
    local_response: str,
    shadow_response: str,
) -> dict[str, Any]:
    """Compare local model and shadow (Claude) responses.

    Computes three metrics:
    1. Length divergence ratio: abs(local_len - shadow_len) / max(shadow_len, 1)
    2. Keyword overlap score: Jaccard similarity of significant word sets
    3. Structural match: both responses have (or both lack) code blocks

    Then evaluates a quality gate:
    - Gate PASSES when all of:
        - length_divergence_ratio <= _MAX_LENGTH_DIVERGENCE (0.70)
        - keyword_overlap_score >= _MIN_KEYWORD_OVERLAP (0.35)
    - structural_match is recorded for observability but does NOT gate pass/fail

    Args:
        local_response: Text returned by the local (delegated) model.
        shadow_response: Text returned by the shadow (Claude) model.

    Returns:
        Dict with keys:
            local_response_length, shadow_response_length,
            length_divergence_ratio, keyword_overlap_score,
            structural_match, quality_gate_passed, divergence_reason.
            divergence_reason: Explanation of divergence. None only when no
            divergence of any kind occurred (including advisory metrics). May
            be non-None even when quality_gate_passed=True (e.g., structural
            mismatch is advisory and does not fail the gate).
    """
    local_len = len(local_response)
    shadow_len = len(shadow_response)

    # Length divergence (capped at 10.0 to match schema le=10.0 constraint)
    length_divergence = min(abs(local_len - shadow_len) / max(shadow_len, 1), 10.0)

    # Keyword overlap
    local_kw = _extract_keywords(local_response)
    shadow_kw = _extract_keywords(shadow_response)
    overlap = _jaccard_similarity(local_kw, shadow_kw)

    # Structural match (code block presence)
    local_has_code = _has_code_block(local_response)
    shadow_has_code = _has_code_block(shadow_response)
    structural_match = local_has_code == shadow_has_code

    # Quality gate — structural_match is observability-only, not a gate factor
    reasons: list[str] = []
    if length_divergence > _MAX_LENGTH_DIVERGENCE:
        reasons.append(
            f"length_divergence={length_divergence:.3f} > threshold={_MAX_LENGTH_DIVERGENCE}"
        )
    if overlap < _MIN_KEYWORD_OVERLAP:
        reasons.append(
            f"keyword_overlap={overlap:.3f} < threshold={_MIN_KEYWORD_OVERLAP}"
        )
    if not structural_match:
        reasons.append(
            f"structural_mismatch: local_code={local_has_code} shadow_code={shadow_has_code}"
        )

    gate_passed = (
        length_divergence <= _MAX_LENGTH_DIVERGENCE and overlap >= _MIN_KEYWORD_OVERLAP
    )
    divergence_reason: str | None = "; ".join(reasons) if reasons else None

    return {
        "local_response_length": local_len,
        "shadow_response_length": shadow_len,
        "length_divergence_ratio": round(length_divergence, 6),
        "keyword_overlap_score": round(overlap, 6),
        "structural_match": structural_match,
        "quality_gate_passed": gate_passed,
        "divergence_reason": divergence_reason,
    }


# ---------------------------------------------------------------------------
# Shadow Claude API call
# ---------------------------------------------------------------------------


def _call_shadow_claude(
    prompt: str,
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout_s: float,
    max_tokens: int,
) -> tuple[str, int] | None:
    """Call Claude (shadow model) via the Anthropic Messages API.

    Uses the Anthropic Messages API format (`/v1/messages`). When `base_url`
    is overridden via `SHADOW_CLAUDE_BASE_URL`, the server must support the
    Anthropic Messages API format — OpenAI-compatible endpoints are not
    supported.

    Args:
        prompt: The user prompt to send (already redacted by delegation_orchestrator).
        model: Claude model identifier (e.g., "claude-sonnet-4-6").
        api_key: Anthropic API key.
        base_url: API base URL (default: https://api.anthropic.com).
        timeout_s: HTTP timeout in seconds.
        max_tokens: Maximum number of tokens in the shadow response.

    Returns:
        Tuple of (response_text, latency_ms) on success, None on any error.
    """
    # Defense-in-depth: enforce HTTPS at the request level too.
    # Primary enforcement is in run_shadow_validation; this is a secondary guard
    # that protects against future callers that bypass the public API.
    if not base_url.startswith("https://") and not any(
        base_url.startswith(p) for p in _LOCAL_PREFIXES
    ):
        logger.debug(
            "Blocked non-HTTPS base_url in _call_shadow_claude: %s",
            base_url.split("://")[0] + "://...",
        )
        return None

    try:
        import httpx
    except ImportError:
        logger.debug("httpx not installed; shadow Claude call skipped")
        return None

    start_time = time.time()
    url = f"{base_url.rstrip('/')}/v1/messages"

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        with httpx.Client(timeout=timeout_s) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        content_blocks = data.get("content", [])
        if not content_blocks:
            logger.debug("Shadow Claude returned empty content")
            return None

        text = "".join(
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        )
        if not text:
            logger.debug("Shadow Claude returned no text content")
            return None

        latency_ms = int((time.time() - start_time) * 1000)
        return text, latency_ms

    except Exception as exc:
        logger.debug("Shadow Claude call failed: %s: %s", type(exc).__name__, exc)
        return None


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


def _emit_shadow_comparison_event(
    *,
    session_id: str,
    correlation_id: str,
    task_type: str,
    local_model: str,
    shadow_model: str,
    comparison: dict[str, Any],
    shadow_latency_ms: int,
    sample_rate: float,
    emitted_at: datetime,
    auto_disable_triggered: bool,
) -> None:
    """Emit onex.evt.omniclaude.delegation-shadow-comparison.v1 (fire-and-forget).

    This function never raises.  Failure to emit is logged at WARNING level and
    silently swallowed so that shadow validation never blocks or crashes.

    Args:
        session_id: Session identifier.
        correlation_id: Correlation ID for distributed tracing.
        task_type: TaskIntent value string.
        local_model: Model identifier of the delegated response.
        shadow_model: Model identifier of the shadow response.
        comparison: Dict returned by compare_responses().
        shadow_latency_ms: Wall-clock time for the shadow call.
        sample_rate: Configured sampling rate.
        emitted_at: Timestamp to use (injected by caller, no datetime.now()).
        auto_disable_triggered: Pre-computed by run_shadow_validation. True when
            this run is the last before auto-disable fires
            (consecutive_passing_days + 1 >= exit_window_days).
    """
    try:
        from uuid import UUID, uuid4

        from omniclaude.hooks.schemas import ModelDelegationShadowComparisonPayload
        from omniclaude.hooks.topics import TopicBase

        try:
            corr_uuid = UUID(correlation_id)
        except (ValueError, AttributeError):
            corr_uuid = uuid4()
            logger.debug(
                "correlation_id %r is not a UUID; generated placeholder %s",
                correlation_id,
                corr_uuid,
            )

        consecutive_passing_days = _get_consecutive_passing_days()
        exit_threshold = _get_exit_threshold()
        exit_window_days = _get_exit_window_days()

        # Truncate divergence_reason to schema max_length=500
        divergence_reason = comparison.get("divergence_reason")
        if divergence_reason and len(divergence_reason) > 500:
            divergence_reason = divergence_reason[:497] + "..."

        payload = ModelDelegationShadowComparisonPayload(
            session_id=session_id or "unknown",
            correlation_id=corr_uuid,
            emitted_at=emitted_at,
            task_type=task_type,
            local_model=local_model,
            shadow_model=shadow_model,
            local_response_length=comparison["local_response_length"],
            shadow_response_length=comparison["shadow_response_length"],
            length_divergence_ratio=comparison["length_divergence_ratio"],
            keyword_overlap_score=comparison["keyword_overlap_score"],
            structural_match=comparison["structural_match"],
            quality_gate_passed=comparison["quality_gate_passed"],
            divergence_reason=divergence_reason,
            shadow_latency_ms=shadow_latency_ms,
            sample_rate=sample_rate,
            consecutive_passing_days=consecutive_passing_days,
            exit_threshold=exit_threshold,
            exit_window_days=exit_window_days,
            auto_disable_triggered=auto_disable_triggered,
        )

        from emit_client_wrapper import emit_event  # type: ignore[import-not-found]

        emit_event(
            event_type=TopicBase.DELEGATION_SHADOW_COMPARISON,
            payload=payload.model_dump(mode="json"),
        )
        logger.debug(
            "Emitted shadow comparison event: task=%s gate_passed=%s "
            "overlap=%.3f divergence=%.3f correlation=%s",
            task_type,
            comparison["quality_gate_passed"],
            comparison["keyword_overlap_score"],
            comparison["length_divergence_ratio"],
            correlation_id,
        )

    except Exception as exc:
        logger.warning(
            "Shadow comparison event emission failed (non-critical): %s", exc
        )


# ---------------------------------------------------------------------------
# Background shadow validation worker
# ---------------------------------------------------------------------------


def _run_shadow_worker(
    *,
    prompt: str,
    local_response: str,
    local_model: str,
    session_id: str,
    correlation_id: str,
    task_type: str,
    sample_rate: float,
    shadow_model: str,
    api_key: str,
    base_url: str,
    timeout_s: float,
    max_tokens: int,
    emitted_at: datetime,
    auto_disable_triggered: bool,
) -> None:
    """Execute shadow validation in a background thread.

    Calls the shadow Claude model, compares outputs, and emits a divergence
    event.  All errors are caught and logged; this function never raises.

    Args:
        prompt: The redacted prompt sent to the local model.
        local_response: The response from the local (delegated) model.
        local_model: Model identifier of the local response.
        session_id: Session identifier.
        correlation_id: Correlation ID for distributed tracing.
        task_type: TaskIntent value.
        sample_rate: Sampling rate at which this check was triggered.
        shadow_model: Claude model identifier.
        api_key: Anthropic API key.
        base_url: API base URL.
        timeout_s: HTTP timeout for the shadow call.
        max_tokens: Maximum number of tokens in the shadow response.
        emitted_at: Timestamp for the comparison event.
        auto_disable_triggered: Pre-computed by run_shadow_validation. True when
            this run is the last before auto-disable fires.
    """
    try:
        shadow_result = _call_shadow_claude(
            prompt,
            model=shadow_model,
            api_key=api_key,
            base_url=base_url,
            timeout_s=timeout_s,
            max_tokens=max_tokens,
        )

        if shadow_result is None:
            logger.debug(
                "Shadow call failed or skipped for correlation=%s; no event emitted",
                correlation_id,
            )
            return

        shadow_response, shadow_latency_ms = shadow_result

        comparison = compare_responses(local_response, shadow_response)

        _emit_shadow_comparison_event(
            session_id=session_id,
            correlation_id=correlation_id,
            task_type=task_type,
            local_model=local_model,
            shadow_model=shadow_model,
            comparison=comparison,
            shadow_latency_ms=shadow_latency_ms,
            sample_rate=sample_rate,
            emitted_at=emitted_at,
            auto_disable_triggered=auto_disable_triggered,
        )

    except Exception as exc:
        logger.debug(
            "Shadow validation worker error (non-critical): %s: %s",
            type(exc).__name__,
            exc,
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_shadow_validation(
    *,
    prompt: str,
    local_response: str,
    local_model: str,
    session_id: str,
    correlation_id: str,
    task_type: str,
    emitted_at: datetime,
) -> bool:
    """Trigger async shadow validation for a delegated task (non-blocking).

    Checks feature flags, makes a deterministic sampling decision, then
    fires a background daemon thread to perform the shadow call and emit the
    comparison event.  The local model response is returned to the user
    immediately; this function returns as soon as the thread is started.

    Does not raise for infrastructure failures (feature flags, sampling, API
    errors, emit failures).  Raises ValueError if emitted_at is None — this
    is a programming error; callers must inject timestamps explicitly per repo
    invariant (no silent datetime.now() fallback allowed).

    Args:
        prompt: The redacted user prompt (already secret-scrubbed by the
            delegation orchestrator — do NOT pass the raw prompt here).
        local_response: Response text from the local (delegated) model.
        local_model: Model identifier string of the local model.
        session_id: Session identifier.
        correlation_id: Correlation ID for the delegation event.
        task_type: TaskIntent value (document, test, research).
        emitted_at: Timestamp for the comparison event.  Must be provided
            explicitly by the caller (e.g., datetime.now(UTC)).  No default
            is provided to ensure deterministic testing.

    Returns:
        True when a shadow validation thread was started, False otherwise
        (feature disabled, not sampled, missing config, etc.).

    Raises:
        ValueError: If emitted_at is None (callers must provide a timestamp).
    """
    if emitted_at is None:
        raise ValueError(
            "emitted_at must be provided explicitly (e.g., datetime.now(UTC)). "
            "No datetime.now() default is allowed per repo invariant."
        )

    # Compute auto_disable_triggered BEFORE the enabled check so the field can
    # truthfully reflect "this run is the last before auto-disable fires" even
    # when shadow validation is enabled.  The enabled check gates on
    # consecutive_days >= window, so if that passes we know the NEXT invocation
    # (consecutive_days + 1) will hit or exceed the window.
    try:
        _consecutive_days = max(
            0, int(os.environ.get("SHADOW_CONSECUTIVE_PASSING_DAYS", "0"))
        )
        _exit_window = max(
            1,
            int(
                os.environ.get(
                    "SHADOW_EXIT_WINDOW_DAYS", str(_DEFAULT_EXIT_WINDOW_DAYS)
                )
            ),
        )
    except (ValueError, TypeError):
        _consecutive_days = 0
        _exit_window = _DEFAULT_EXIT_WINDOW_DAYS
    _auto_disable_triggered = (_consecutive_days + 1) >= _exit_window

    try:
        if not _is_shadow_validation_enabled():
            logger.debug(
                "Shadow validation disabled; skipping for correlation=%s",
                correlation_id,
            )
            return False

        sample_rate = _get_sample_rate()
        if not _should_sample(correlation_id, sample_rate):
            logger.debug(
                "Shadow validation not sampled (rate=%.2f) for correlation=%s",
                sample_rate,
                correlation_id,
            )
            return False

        # Resolve shadow model configuration
        shadow_model = (
            os.environ.get("SHADOW_MODEL", _DEFAULT_SHADOW_MODEL).strip()
            or _DEFAULT_SHADOW_MODEL
        )

        api_key = os.environ.get(
            "SHADOW_CLAUDE_API_KEY", ""
        ).strip()  # pragma: allowlist secret
        if not api_key:
            logger.debug(
                "SHADOW_CLAUDE_API_KEY not set; shadow validation skipped for correlation=%s",
                correlation_id,
            )
            return False

        base_url = (
            os.environ.get("SHADOW_CLAUDE_BASE_URL", "").strip()
            or "https://api.anthropic.com"
        )

        # Security: Reject non-HTTPS base URLs unless they point to loopback.
        # _LOCAL_PREFIXES is defined at module level (see above).
        if not base_url.startswith("https://") and not any(
            base_url.startswith(p) for p in _LOCAL_PREFIXES
        ):
            logger.warning(
                "SHADOW_CLAUDE_BASE_URL uses non-HTTPS scheme; shadow validation skipped "
                "for security. Set SHADOW_CLAUDE_BASE_URL to an https:// URL."
            )
            return False

        try:
            timeout_s = float(
                os.environ.get("SHADOW_CALL_TIMEOUT_S", str(_DEFAULT_SHADOW_TIMEOUT_S))
            )
        except (ValueError, TypeError):
            timeout_s = _DEFAULT_SHADOW_TIMEOUT_S

        try:
            max_tokens = int(
                os.environ.get("SHADOW_MAX_TOKENS", str(_DEFAULT_SHADOW_MAX_TOKENS))
            )
        except (ValueError, TypeError):
            max_tokens = _DEFAULT_SHADOW_MAX_TOKENS

        # Closure pattern: api_key is NOT stored in thread.kwargs (which is introspectable).
        # It lives in the closure __closure__ cells — same lifetime, but not accessible
        # via thread._kwargs introspection or exception tracebacks that serialize thread state.
        _prompt = prompt
        _local_response = local_response
        _local_model = local_model
        _session_id = session_id
        _correlation_id = correlation_id
        _task_type = task_type
        _sample_rate = sample_rate
        _shadow_model = shadow_model
        _base_url = base_url
        _timeout_s = timeout_s
        _max_tokens = max_tokens
        _emitted_at = emitted_at
        _api_key_local = api_key  # captured by closure, not stored in thread dict
        _auto_disable = _auto_disable_triggered

        def _worker() -> None:
            _run_shadow_worker(
                api_key=_api_key_local,
                prompt=_prompt,
                local_response=_local_response,
                local_model=_local_model,
                session_id=_session_id,
                correlation_id=_correlation_id,
                task_type=_task_type,
                sample_rate=_sample_rate,
                shadow_model=_shadow_model,
                base_url=_base_url,
                timeout_s=_timeout_s,
                max_tokens=_max_tokens,
                emitted_at=_emitted_at,
                auto_disable_triggered=_auto_disable,
            )

        thread = threading.Thread(
            target=_worker,
            name=f"shadow-validation-{correlation_id[:8]}",
            daemon=True,  # Daemon threads do not prevent process exit
        )
        thread.start()
        logger.debug(
            "Shadow validation thread started: correlation=%s task=%s sample_rate=%.2f",
            correlation_id,
            task_type,
            sample_rate,
        )
        return True

    except Exception as exc:
        logger.debug(
            "run_shadow_validation unexpected error (non-critical): %s: %s",
            type(exc).__name__,
            exc,
        )
        return False

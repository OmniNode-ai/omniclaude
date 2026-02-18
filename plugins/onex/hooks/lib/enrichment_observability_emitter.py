"""Enrichment observability event emitter (OMN-2274).

Builds and emits ``onex.evt.omniclaude.context-enrichment.v1`` events per
enrichment channel after the enrichment pipeline completes.

Event fields (per enrichment):
    enrichment_type     -- channel name: "summarization", "code_analysis", "similarity"
    model_used          -- model identifier (from handler, or "" if unknown)
    latency_ms          -- wall-clock duration of the enrichment in milliseconds
    result_token_count  -- token count of the produced markdown (0 on failure)
    relevance_score     -- optional float [0.0, 1.0] from handler, or None
    fallback_used       -- True when handler fell back to a simpler strategy
    tokens_saved        -- original_tokens - result_token_count (summarization channel)
    was_dropped         -- True when the enrichment was produced but dropped by the token cap
    prompt_version      -- optional prompt template version string

Usage::

    from enrichment_observability_emitter import emit_enrichment_events

    emit_enrichment_events(
        session_id="...",
        correlation_id="...",
        results=raw_results,       # all completed _EnrichmentResult objects
        kept_names={"summarization", "code_analysis"},
    )

Design notes:
- Non-blocking: any emission failure is silently swallowed so the hook path
  is unaffected.
- Emission uses emit_client_wrapper.emit_event() via the socket daemon.
- ``was_dropped`` is True when the enrichment produced content but was
  excluded by _apply_token_cap (i.e. it is in raw_results but not in kept).
- ``tokens_saved`` applies only to the summarization channel: it is the
  difference between original_token_count (passed by caller) and the
  summarized result_token_count.  For all other channels it is 0.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional emit_event import at module scope for testability.
# Tests patch ``enrichment_observability_emitter.emit_event`` directly.
# ---------------------------------------------------------------------------
try:
    from emit_client_wrapper import emit_event
except ImportError:
    emit_event = None  # type: ignore[assignment]

# Event type registered in emit_client_wrapper.SUPPORTED_EVENT_TYPES
_EVENT_TYPE = "context.enrichment"


# ---------------------------------------------------------------------------
# Payload builder
# ---------------------------------------------------------------------------


def build_enrichment_event_payload(
    *,
    session_id: str,
    correlation_id: str,
    enrichment_type: str,
    model_used: str,
    latency_ms: float,
    result_token_count: int,
    relevance_score: float | None,
    fallback_used: bool,
    tokens_saved: int,
    was_dropped: bool,
    prompt_version: str,
) -> dict[str, Any]:
    """Build the payload dict for a single enrichment observability event.

    All values are explicitly typed; no defaults are applied here so
    callers must supply every field (easy to test deterministically).

    Args:
        session_id: The Claude Code session identifier.
        correlation_id: Trace correlation ID propagated from the hook.
        enrichment_type: Channel name ("summarization", "code_analysis", "similarity").
        model_used: Model identifier used by the handler, or "" if unknown.
        latency_ms: Wall-clock duration of the enrichment attempt in milliseconds.
        result_token_count: Approximate token count of the produced markdown.
            Zero when the enrichment failed or produced no content.
        relevance_score: Optional float in [0.0, 1.0] from the handler.
            None when the handler does not report a relevance score.
        fallback_used: True when the handler used a simpler fallback strategy.
        tokens_saved: Tokens saved by the summarization channel
            (original_token_count - result_token_count).  Zero for all other
            channels and when summarization produced no output.
        was_dropped: True when the enrichment ran successfully but was excluded
            by the token-cap drop policy (overflow).
        prompt_version: Prompt template version string from the handler, or "".

    Returns:
        Dict suitable for emission via emit_client_wrapper.emit_event().
    """
    return {
        "session_id": session_id,
        "correlation_id": correlation_id,
        "enrichment_type": enrichment_type,
        "model_used": model_used,
        "latency_ms": round(latency_ms, 3),
        "result_token_count": result_token_count,
        "relevance_score": relevance_score,
        "fallback_used": fallback_used,
        "tokens_saved": tokens_saved,
        "was_dropped": was_dropped,
        "prompt_version": prompt_version,
    }


# ---------------------------------------------------------------------------
# Metadata extraction helpers
# ---------------------------------------------------------------------------


def _extract_model_used(result: Any) -> str:
    """Extract model_used from an _EnrichmentResult, with safe fallback."""
    return str(getattr(result, "model_used", "") or "")


def _extract_relevance_score(result: Any) -> float | None:
    """Extract optional relevance_score from an _EnrichmentResult."""
    score = getattr(result, "relevance_score", None)
    if score is None:
        return None
    try:
        return float(score)
    except (TypeError, ValueError):
        return None


def _extract_fallback_used(result: Any) -> bool:
    """Extract fallback_used flag from an _EnrichmentResult."""
    return bool(getattr(result, "fallback_used", False))


def _extract_prompt_version(result: Any) -> str:
    """Extract prompt_version string from an _EnrichmentResult."""
    return str(getattr(result, "prompt_version", "") or "")


def _extract_latency_ms(result: Any) -> float:
    """Extract latency_ms from an _EnrichmentResult."""
    val = getattr(result, "latency_ms", None)
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass
    return 0.0


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def emit_enrichment_events(
    *,
    session_id: str,
    correlation_id: str,
    results: list[Any],
    kept_names: set[str],
    original_prompt_token_count: int = 0,
) -> int:
    """Emit one ``context.enrichment`` event per completed enrichment channel.

    Iterates over ``results`` (list of ``_EnrichmentResult`` objects from the
    runner) and emits a single observability event per item.  Results with an
    empty ``name`` are skipped.  Failed enrichments still emit events (with
    ``result_token_count=0``) for observability into failure rates.

    ``was_dropped`` is derived by checking whether the enrichment name is
    absent from ``kept_names`` (the set of names that survived the token cap).

    ``tokens_saved`` is calculated for the summarization channel only:
        tokens_saved = original_prompt_token_count - result.tokens

    For all other channels, tokens_saved is always 0.

    Args:
        session_id: Claude Code session identifier.
        correlation_id: Trace correlation ID from the hook.
        results: List of ``_EnrichmentResult`` objects from ``_run_all_enrichments``.
            May include both successful and failed results.
        kept_names: Set of enrichment names that survived the token cap drop.
        original_prompt_token_count: Token count of the raw user prompt before
            any summarization.  Used to compute ``tokens_saved`` for the
            summarization channel.

    Returns:
        Number of events successfully emitted.
    """
    if emit_event is None:
        logger.debug("emit_client_wrapper not available; enrichment events skipped")
        return 0

    emitted = 0

    for result in results:
        # Only emit for enrichments that attempted to run (success or failed)
        # Skip enrichments that were never started (no result at all)
        enrichment_type: str = getattr(result, "name", "") or ""
        if not enrichment_type:
            continue

        success: bool = bool(getattr(result, "success", False))
        result_token_count: int = int(getattr(result, "tokens", 0))  # noqa: secrets

        # was_dropped: ran and produced content but excluded by token cap
        was_dropped = success and (enrichment_type not in kept_names)

        # tokens_saved: only meaningful for summarization
        if enrichment_type == "summarization" and success and result_token_count > 0:
            tokens_saved = max(0, original_prompt_token_count - result_token_count)  # noqa: secrets
        else:
            tokens_saved = 0

        payload = build_enrichment_event_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            enrichment_type=enrichment_type,
            model_used=_extract_model_used(result),
            latency_ms=_extract_latency_ms(result),
            result_token_count=result_token_count,
            relevance_score=_extract_relevance_score(result),
            fallback_used=_extract_fallback_used(result),
            tokens_saved=tokens_saved,
            was_dropped=was_dropped,
            prompt_version=_extract_prompt_version(result),
        )

        try:
            ok = emit_event(_EVENT_TYPE, payload)
            if ok:
                emitted += 1
            else:
                logger.debug(
                    "Enrichment event emission failed for channel=%s", enrichment_type
                )
        except Exception as exc:
            logger.debug(
                "Enrichment event emission error for channel=%s: %s",
                enrichment_type,
                exc,
            )

    return emitted


__all__ = [
    "build_enrichment_event_payload",
    "emit_enrichment_events",
]

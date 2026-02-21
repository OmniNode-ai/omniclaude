"""Enrichment observability event emitter (OMN-2274, OMN-2441).

Builds and emits ``onex.evt.omniclaude.context-enrichment.v1`` events per
enrichment channel after the enrichment pipeline completes.

Canonical fields emitted (omnidash ContextEnrichmentEvent schema, OMN-2441):
    session_id          -- Claude Code session identifier
    timestamp           -- ISO-8601 UTC timestamp injected by the caller (parameter: ``emitted_at``)
    correlation_id      -- trace correlation ID propagated from the hook
    channel             -- enrichment channel: "summarization", "code_analysis", "similarity"
    model_name          -- model identifier (from handler, or "" if unknown)
    cache_hit           -- always False (cache tracking not yet implemented)
    outcome             -- "hit", "miss", "error", or "inflated"
    latency_ms          -- wall-clock duration of the enrichment in milliseconds
    tokens_before       -- token count of the original prompt (pre-enrichment)
    tokens_after        -- token count of the produced markdown (0 on failure)
    net_tokens_saved    -- tokens_before - tokens_after (summarization channel only)
    similarity_score    -- optional float [0.0, 1.0] from handler (similarity channel)
    quality_score       -- always None (quality tracking not yet implemented)
    repo                -- repository name derived from project_path
    agent_name          -- agent that triggered the enrichment

Legacy/backward-compat fields (retained for consumer migration, see TODO(OMN-2473)):
    enrichment_type     -- duplicate of ``channel`` under the old field name
    model_used          -- duplicate of ``model_name`` under the old field name
    result_token_count  -- duplicate of ``tokens_after`` under the old field name
    relevance_score     -- duplicate of ``similarity_score`` under the old field name
    tokens_saved        -- duplicate of ``net_tokens_saved`` under the old field name
    fallback_used       -- True when handler fell back to a simpler strategy (not in omnidash schema)
    was_dropped         -- True when the enrichment was produced but dropped by the token cap (not in omnidash schema)
    prompt_version      -- optional prompt template version string (not in omnidash schema)

Usage::

    from enrichment_observability_emitter import emit_enrichment_events

    emit_enrichment_events(
        session_id="...",
        correlation_id="...",
        results=raw_results,       # all completed _EnrichmentResult objects
        kept_names={"summarization", "code_analysis"},
        original_prompt_token_count=500,
        project_path="/path/to/repo",
        agent_name="polymorphic-agent",
    )

Design notes:
- Non-blocking: any emission failure is silently swallowed so the hook path
  is unaffected.
- Emission uses emit_client_wrapper.emit_event() via the socket daemon.
- ``was_dropped`` is True when the enrichment produced content but was
  excluded by _apply_token_cap (i.e. it is in raw_results but not in kept).
- ``outcome`` is derived from result state:
    - "hit"      when success=True and tokens > 0
    - "miss"     when success=True and tokens == 0
    - "error"    when success=False
    - "inflated" when success=True and tokens_after > tokens_before (summarization only)
- ``net_tokens_saved`` applies only to the summarization channel: it is the
  difference between tokens_before (original prompt count) and tokens_after
  (summarized result count).  For all other channels it is 0.
- Backward-compatible fields (enrichment_type, model_used, result_token_count,
  tokens_saved, relevance_score) are retained alongside the new canonical names
  so existing consumers are not broken.
  TODO(OMN-2473): Remove legacy fields once omnidash consumers migrate
  to the canonical schema (channel, model_name, tokens_after, net_tokens_saved,
  similarity_score).  Track migration progress against OMN-2441.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional emit_event import at module scope for testability.
# Tests patch ``enrichment_observability_emitter.emit_event`` directly.
# ---------------------------------------------------------------------------
try:
    from emit_client_wrapper import emit_event
except ImportError:
    emit_event = None

# Event type registered in emit_client_wrapper.SUPPORTED_EVENT_TYPES
_EVENT_TYPE = "context.enrichment"


# ---------------------------------------------------------------------------
# Outcome derivation
# ---------------------------------------------------------------------------


def _derive_outcome(
    *,
    success: bool,
    tokens_after: int,
    tokens_before: int,
    channel: str,
) -> str:
    """Derive the enrichment outcome from result state.

    Outcome values match omnidash ENRICHMENT_OUTCOMES:
        hit      -- enrichment succeeded and produced content
        miss     -- enrichment succeeded but produced no content
        error    -- enrichment failed
        inflated -- enrichment increased token count (context inflation alert)

    ``inflated`` is detected only for the summarization channel (the only channel
    that can reduce tokens).  For similarity and code_analysis, a higher
    token_after is the expected behaviour (they add context, not compress it).

    Note: the ``inflated`` outcome is only reachable when ``channel`` is
    ``"summarization"``; ``tokens_before`` has no effect for other channels.
    A caller passing ``tokens_before=500`` for ``"code_analysis"`` would never
    receive ``"inflated"`` even if ``tokens_after=600`` — the inflation check is
    unconditionally gated on ``channel == "summarization"``.

    Args:
        success: Whether the enrichment handler reported success.
        tokens_after: Token count of the enrichment output (0 on failure/miss).
        tokens_before: Original prompt token count (pre-enrichment).  Only
            consulted when ``channel == "summarization"``; ignored otherwise.
        channel: Enrichment channel name.

    Returns:
        One of "hit", "miss", "error", "inflated".
    """
    if not success:
        return "error"
    if tokens_after == 0:
        return "miss"
    # Context inflation: summarization channel increased token count
    if (
        channel == "summarization"
        and tokens_before > 0
        and tokens_after > tokens_before
    ):
        return "inflated"
    return "hit"


# ---------------------------------------------------------------------------
# Repo name helper
# ---------------------------------------------------------------------------


def _derive_repo(project_path: str) -> str | None:
    """Extract repository name from project_path.

    Returns the basename of the path (e.g. "omniclaude2" from
    "/Volumes/PRO-G40/Code/omniclaude2"), or None when project_path is empty.
    """
    if not project_path:
        return None
    return os.path.basename(project_path.rstrip("/")) or None


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
    net_tokens_saved: int,
    was_dropped: bool,
    prompt_version: str,
    success: bool,
    # Caller-injected timestamp (repository invariant: no datetime.now() defaults).
    # Required: callers must supply the timestamp so it is deterministic in tests.
    # emit_enrichment_events() captures datetime.now(UTC) once per batch and passes
    # it here; test callers pass a fixed datetime directly.
    emitted_at: datetime,
    # OMN-2441: omnidash-compatible fields (optional)
    tokens_before: int = 0,
    repo: str | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """Build the payload dict for a single enrichment observability event.

    Most arguments are required; ``emitted_at`` is required and must appear
    before the optional parameters (repository invariant: no ``datetime.now()``
    defaults inside builders).  ``tokens_before``, ``repo``, and ``agent_name``
    have defaults and may be omitted by callers.

    The payload includes both the original internal field names (for backward
    compatibility with any existing consumers) and the omnidash-canonical field
    names required by ``ContextEnrichmentEvent`` in omnidash's shared types.

    Per the repository invariant, callers must pass ``emitted_at`` explicitly
    so that the timestamp is deterministic in tests.  ``emit_enrichment_events``
    captures ``datetime.now(UTC)`` once per batch and passes the same instant
    to every per-channel call.  Test callers pass a fixed ``datetime`` directly.

    Args:
        session_id: The Claude Code session identifier.
        correlation_id: Trace correlation ID propagated from the hook.
        enrichment_type: Channel name ("summarization", "code_analysis", "similarity").
            Mapped to ``channel`` in the canonical payload.
        model_used: Model identifier used by the handler, or "" if unknown.
            Mapped to ``model_name`` in the canonical payload.
        latency_ms: Wall-clock duration of the enrichment attempt in milliseconds.
        result_token_count: Approximate token count of the produced markdown.
            Zero when the enrichment failed or produced no content.
            Mapped to ``tokens_after`` in the canonical payload.
        relevance_score: Optional float in [0.0, 1.0] from the handler.
            None when the handler does not report a relevance score.
            Mapped to ``similarity_score`` in the canonical payload.
        fallback_used: True when the handler used a simpler fallback strategy.
        net_tokens_saved: Tokens saved by the summarization channel
            (tokens_before - tokens_after, clamped to >= 0).  Zero for all
            other channels and when summarization produced no output.
            Emitted as ``net_tokens_saved`` in the canonical payload and as
            ``tokens_saved`` in the backward-compatible internal fields.
        was_dropped: True when the enrichment ran successfully but was excluded
            by the token-cap drop policy (overflow).
        prompt_version: Prompt template version string from the handler, or "".
        success: Whether the enrichment handler reported success.  Used to
            distinguish "miss" (success=True, tokens=0) from "error"
            (success=False).
        tokens_before: Original prompt token count before enrichment.  Used for
            the summarization channel to compute net_tokens_saved.  Zero for all
            other channels (they add context, not compress it).  Defaults to 0.
        repo: Repository name (basename of project_path).  None when unknown.
        agent_name: Agent that triggered the enrichment.  None when unknown.
        emitted_at: UTC timestamp for the event.  Required (repository invariant:
            no ``datetime.now()`` defaults inside builders).  Callers capture
            the timestamp once and pass it explicitly for deterministic testing.
            Must be timezone-aware; naive datetimes raise ``ValueError`` because
            omnidash consumers require an explicit UTC offset in the ISO-8601
            string (e.g. ``datetime.now(UTC)``, not ``datetime.now()``).

    Returns:
        Dict suitable for emission via emit_client_wrapper.emit_event().
    """
    # Guard: reject naive datetimes. A naive emitted_at produces a timestamp
    # string without a UTC offset (e.g. "2024-01-01T12:00:00" instead of
    # "2024-01-01T12:00:00+00:00"), which omnidash consumers reject.
    # Callers must pass a timezone-aware datetime (e.g. datetime.now(UTC)).
    if emitted_at.tzinfo is None:
        raise ValueError(
            "emitted_at must be timezone-aware (e.g. datetime.now(UTC)); "
            "naive datetimes produce invalid timestamps for omnidash consumers."
        )

    # Derive the outcome from result state using the explicit success flag so
    # that a legitimate "miss" (success=True, tokens=0) is not misclassified
    # as "error" (success=False).
    outcome = _derive_outcome(
        success=success,
        tokens_after=result_token_count,
        tokens_before=tokens_before,
        channel=enrichment_type,
    )

    return {
        # ---------------------------------------------------------------
        # Canonical omnidash ContextEnrichmentEvent fields (OMN-2441)
        # ---------------------------------------------------------------
        "timestamp": emitted_at.isoformat(),
        "correlation_id": correlation_id,
        "session_id": session_id,
        "channel": enrichment_type,  # omnidash field name
        "model_name": model_used,  # omnidash field name
        "cache_hit": False,  # not tracked yet
        "outcome": outcome,  # hit / miss / error / inflated
        "latency_ms": round(latency_ms, 3),
        "tokens_before": tokens_before,
        "tokens_after": result_token_count,  # omnidash field name
        "net_tokens_saved": net_tokens_saved,  # omnidash field name
        "similarity_score": relevance_score,  # omnidash field name
        "quality_score": None,  # not tracked yet
        "repo": repo,
        "agent_name": agent_name,
        # ---------------------------------------------------------------
        # Backward-compat fields retained for consumer migration only.
        # TODO(OMN-2473): Remove once omnidash consumers migrate to
        # the canonical schema above.  The following fields are intentionally
        # omitted from the canonical ContextEnrichmentEvent schema and are
        # present here for legacy consumers only:
        #   - fallback_used: internal handler detail, not part of omnidash schema
        #   - was_dropped: token-cap policy detail, not part of omnidash schema
        #   - prompt_version: handler-internal versioning, not part of omnidash schema
        # The remaining fields below (enrichment_type, model_used,
        # result_token_count, relevance_score, tokens_saved) are duplicates of
        # canonical fields under old names; remove after consumers migrate.
        # ---------------------------------------------------------------
        "enrichment_type": enrichment_type,
        "model_used": model_used,
        "result_token_count": result_token_count,
        "relevance_score": relevance_score,
        "fallback_used": fallback_used,
        "tokens_saved": net_tokens_saved,
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
    project_path: str = "",
    agent_name: str | None = None,
) -> int:
    """Emit one ``context.enrichment`` event per completed enrichment channel.

    Iterates over ``results`` (list of ``_EnrichmentResult`` objects from the
    runner) and emits a single observability event per item.  Results with an
    empty ``name`` are skipped.  Failed enrichments still emit events (with
    ``tokens_after=0``) for observability into failure rates.

    ``was_dropped`` is derived by checking whether the enrichment name is
    absent from ``kept_names`` (the set of names that survived the token cap).

    ``net_tokens_saved`` is calculated for the summarization channel only:
        net_tokens_saved = original_prompt_token_count - result.tokens

    For all other channels, net_tokens_saved is always 0.

    Args:
        session_id: Claude Code session identifier.
        correlation_id: Trace correlation ID from the hook.
        results: List of ``_EnrichmentResult`` objects from ``_run_all_enrichments``.
            May include both successful and failed results.
        kept_names: Set of enrichment names that survived the token cap drop.
        original_prompt_token_count: Token count of the raw user prompt before
            any summarization.  Used to compute ``net_tokens_saved`` for the
            summarization channel.
        project_path: Filesystem path to the project root.  Used to derive
            the ``repo`` field (basename of the path).
        agent_name: Agent that triggered the enrichment.  Passed through to
            the event payload as-is.

    Returns:
        Number of events successfully emitted.
    """
    if emit_event is None:
        logger.debug("emit_client_wrapper not available; enrichment events skipped")
        return 0

    # Capture the emission timestamp once for all events in this batch so that
    # all channels share the same wall-clock instant.  Note: datetime.now(UTC)
    # is called here (not inside the builder), satisfying the invariant that
    # build_enrichment_event_payload never generates its own timestamp.
    # Timestamp determinism is therefore only guaranteed when testing
    # build_enrichment_event_payload directly (where callers pass a fixed
    # emitted_at); tests of emit_enrichment_events will see a live clock value.
    # Consequence for omnidash consumers: all channels in a single batch share
    # the same timestamp (set once here), not the per-call values passed to
    # build_enrichment_event_payload in unit tests.
    now = datetime.now(UTC)
    repo = _derive_repo(project_path)
    emitted = 0

    for result in results:
        # Only emit for enrichments that attempted to run (success or failed)
        # Skip enrichments that were never started (no result at all)
        enrichment_type: str = getattr(result, "name", "") or ""
        if not enrichment_type:
            continue

        success: bool = bool(getattr(result, "success", False))
        result_token_count: int = int(getattr(result, "tokens", 0))  # noqa: secrets

        # was_dropped: ran and produced content but excluded by token cap.
        # Guard tokens_after > 0: a miss (tokens_after=0) with success=True should
        # not be flagged as dropped — there was nothing meaningful to drop.
        was_dropped = (
            success and (enrichment_type not in kept_names) and result_token_count > 0
        )

        # tokens_before: for summarization this is the original prompt size;
        # for other channels the concept doesn't apply (they add context)
        if enrichment_type == "summarization":
            tokens_before = original_prompt_token_count
        else:
            tokens_before = 0

        # net_tokens_saved: only meaningful for summarization
        if enrichment_type == "summarization" and success and result_token_count > 0:
            # Clamp to 0: when tokens_after > tokens_before the outcome is "inflated"
            # and net_tokens_saved is meaningless (tokens increased, not decreased).
            net_tokens_saved = max(0, original_prompt_token_count - result_token_count)  # noqa: secrets
        else:
            net_tokens_saved = 0

        payload = build_enrichment_event_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            enrichment_type=enrichment_type,
            model_used=_extract_model_used(result),
            latency_ms=_extract_latency_ms(result),
            result_token_count=result_token_count,
            relevance_score=_extract_relevance_score(result),
            fallback_used=_extract_fallback_used(result),
            net_tokens_saved=net_tokens_saved,
            was_dropped=was_dropped,
            prompt_version=_extract_prompt_version(result),
            success=success,
            emitted_at=now,
            tokens_before=tokens_before,
            repo=repo,
            agent_name=agent_name,
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

#!/usr/bin/env python3
"""Extraction pipeline event emitter (OMN-2344).

Emits the three extraction pipeline events required by the omnidash consumer:
  - context.utilization  → injection_effectiveness table
  - agent.match          → injection_effectiveness table (agent-match events)
  - latency.breakdown    → latency_breakdowns table

All three events include the ``cohort`` field required by the omnidash
``isExtractionBaseEvent()`` type guard.  Without ``cohort``, every message is
dropped by the consumer's validation layer.

CLI Usage::

    echo '{
        "session_id": "uuid",
        "correlation_id": "uuid",
        "agent_name": "polymorphic-agent",
        "agent_match_score": 0.95,
        "cohort": "treatment",
        "injection_occurred": true,
        "patterns_count": 3,
        "routing_time_ms": 45,
        "retrieval_time_ms": 120,
        "injection_time_ms": 30,
        "user_visible_latency_ms": 250,
        "cache_hit": false
    }' | python extraction_event_emitter.py

Design notes:
- Always exits with code 0 — hook compatibility requirement.
- Any emission failure is silently swallowed so the hook path is unaffected.
- ``utilization_score`` defaults to 0.0 (computed asynchronously post-response;
  not available at hook completion time).
- ``causation_id`` is generated as a new UUID per event.
- ``entity_id`` is derived from ``session_id`` (UUID parse or deterministic hash).
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional emit_event import — graceful degradation when daemon not running
# ---------------------------------------------------------------------------
try:
    from emit_client_wrapper import (
        emit_event as _emit_event,  # type: ignore[import-not-found]
    )
except ImportError:
    _emit_event = None


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_context_utilization_payload(
    *,
    session_id: str,
    correlation_id: str,
    cohort: str,
    injection_occurred: bool,
    agent_name: str | None,
    patterns_count: int,
    user_visible_latency_ms: int | None,
    cache_hit: bool,
    emitted_at: str,
) -> dict[str, Any]:
    """Build payload for context.utilization event.

    ``utilization_score`` is set to 0.0 because utilization detection
    requires comparing injected identifiers against Claude's response text,
    which is not available at hook completion time.  The field is present
    to satisfy the schema; a future async post-processing step could update it.
    """
    return {
        "session_id": session_id,
        "entity_id": _to_entity_id(session_id),
        "correlation_id": correlation_id,
        "causation_id": str(uuid.uuid4()),
        "emitted_at": emitted_at,
        "cohort": cohort,
        "injection_occurred": injection_occurred,
        "agent_name": agent_name,
        "user_visible_latency_ms": user_visible_latency_ms,
        "cache_hit": cache_hit,
        "patterns_count": patterns_count,
        # Utilization metrics — score unavailable at hook time (response not yet generated)
        "utilization_score": 0.0,
        "method": "timeout_fallback",
        "injected_count": 0,
        "reused_count": 0,
        "detection_duration_ms": 0,
    }


def build_agent_match_payload(
    *,
    session_id: str,
    correlation_id: str,
    cohort: str,
    agent_name: str,
    agent_match_score: float,
    routing_confidence: float,
    emitted_at: str,
) -> dict[str, Any]:
    """Build payload for agent.match event."""
    return {
        "session_id": session_id,
        "entity_id": _to_entity_id(session_id),
        "correlation_id": correlation_id,
        "causation_id": str(uuid.uuid4()),
        "emitted_at": emitted_at,
        "cohort": cohort,
        "selected_agent": agent_name,
        "expected_agent": None,
        "match_grade": "unknown",
        "agent_match_score": agent_match_score,
        "confidence": routing_confidence,
        "routing_method": "event_routing",
    }


def build_latency_breakdown_payload(
    *,
    session_id: str,
    correlation_id: str,
    cohort: str,
    routing_time_ms: int,
    retrieval_time_ms: int | None,
    injection_time_ms: int,
    user_visible_latency_ms: int | None,
    cache_hit: bool,
    emitted_at: str,
) -> dict[str, Any]:
    """Build payload for latency.breakdown event."""
    return {
        "session_id": session_id,
        "entity_id": _to_entity_id(session_id),
        "correlation_id": correlation_id,
        "causation_id": str(uuid.uuid4()),
        "emitted_at": emitted_at,
        "cohort": cohort,
        "routing_time_ms": routing_time_ms,
        "retrieval_time_ms": retrieval_time_ms,
        "injection_time_ms": injection_time_ms,
        "intelligence_request_ms": None,
        "total_hook_ms": user_visible_latency_ms or 0,
        "user_visible_latency_ms": user_visible_latency_ms,
        "cache_hit": cache_hit,
        "agent_load_ms": 0,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_entity_id(session_id: str) -> str:
    """Return session_id if it is a valid UUID, else a deterministic UUID string."""
    try:
        uuid.UUID(session_id)
        return session_id
    except (ValueError, AttributeError):
        import hashlib

        h = hashlib.sha256(session_id.encode()).hexdigest()[:32]
        return str(uuid.UUID(h))


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce value to float, returning default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce value to int, returning default on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Coerce value to bool from JSON-like input."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return bool(value) if value is not None else default


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------


def emit_extraction_events(data: dict[str, Any]) -> int:
    """Emit all three extraction events from a single data dict.

    Args:
        data: Dictionary with session context fields (see module docstring).

    Returns:
        Number of events successfully emitted (0-3).
    """
    if _emit_event is None:
        logger.debug("emit_client_wrapper not available; extraction events skipped")
        return 0

    session_id: str = str(data.get("session_id") or "")
    correlation_id: str = str(data.get("correlation_id") or str(uuid.uuid4()))
    cohort: str = str(data.get("cohort") or "treatment")
    agent_name: str | None = data.get("agent_name") or None
    agent_match_score: float = _safe_float(data.get("agent_match_score"), 0.0)
    routing_confidence: float = _safe_float(data.get("routing_confidence"), 0.0)
    injection_occurred: bool = _safe_bool(data.get("injection_occurred"), False)
    patterns_count: int = _safe_int(data.get("patterns_count"), 0)
    routing_time_ms: int = _safe_int(data.get("routing_time_ms"), 0)
    retrieval_time_ms: int | None = (
        _safe_int(data["retrieval_time_ms"])
        if data.get("retrieval_time_ms") is not None
        else None
    )
    injection_time_ms: int = _safe_int(data.get("injection_time_ms"), 0)
    user_visible_latency_ms: int | None = (
        _safe_int(data["user_visible_latency_ms"])
        if data.get("user_visible_latency_ms") is not None
        else None
    )
    cache_hit: bool = _safe_bool(data.get("cache_hit"), False)

    if not session_id:
        logger.debug("extraction_event_emitter: missing session_id, skipping")
        return 0

    emitted_at = datetime.now(UTC).isoformat()
    emitted = 0

    # 1. context.utilization
    try:
        payload = build_context_utilization_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            cohort=cohort,
            injection_occurred=injection_occurred,
            agent_name=agent_name,
            patterns_count=patterns_count,
            user_visible_latency_ms=user_visible_latency_ms,
            cache_hit=cache_hit,
            emitted_at=emitted_at,
        )
        if _emit_event("context.utilization", payload):
            emitted += 1
    except Exception as exc:
        logger.debug("context.utilization emission error: %s", exc)

    # 2. agent.match
    if agent_name:
        try:
            payload = build_agent_match_payload(
                session_id=session_id,
                correlation_id=correlation_id,
                cohort=cohort,
                agent_name=agent_name,
                agent_match_score=agent_match_score,
                routing_confidence=routing_confidence,
                emitted_at=emitted_at,
            )
            if _emit_event("agent.match", payload):
                emitted += 1
        except Exception as exc:
            logger.debug("agent.match emission error: %s", exc)

    # 3. latency.breakdown
    try:
        payload = build_latency_breakdown_payload(
            session_id=session_id,
            correlation_id=correlation_id,
            cohort=cohort,
            routing_time_ms=routing_time_ms,
            retrieval_time_ms=retrieval_time_ms,
            injection_time_ms=injection_time_ms,
            user_visible_latency_ms=user_visible_latency_ms,
            cache_hit=cache_hit,
            emitted_at=emitted_at,
        )
        if _emit_event("latency.breakdown", payload):
            emitted += 1
    except Exception as exc:
        logger.debug("latency.breakdown emission error: %s", exc)

    return emitted


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI: read JSON from stdin, emit extraction events, exit 0."""
    try:
        raw = sys.stdin.read()
        data: dict[str, Any] = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("extraction_event_emitter: invalid JSON on stdin: %s", exc)
        data = {}

    emit_extraction_events(data)
    # Always exit 0 — hook compatibility requirement
    sys.exit(0)


if __name__ == "__main__":
    main()


__all__ = [
    "build_context_utilization_payload",
    "build_agent_match_payload",
    "build_latency_breakdown_payload",
    "emit_extraction_events",
]

#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Phoenix (Arize) OTEL span exporter for manifest injection measurement.

Emits OpenTelemetry spans from omniclaude hooks to Arize Phoenix, which handles
storage and querying. No custom trace storage or UI is needed.

Design:
    - Uses OTLP HTTP directly to Phoenix (no separate collector in v1)
    - Async batch processor: non-blocking, bounded, drop-on-failure (R2)
    - Export errors are logged but never raised (hook must not crash)
    - Queue bounded at PHOENIX_QUEUE_MAX_SIZE, drops oldest when full

Configuration (via environment variables):
    PHOENIX_OTEL_ENDPOINT   OTLP HTTP endpoint (default: http://localhost:6006/v1/traces)
    PHOENIX_OTEL_ENABLED    Set to "0" or "false" to disable (default: enabled)
    PHOENIX_QUEUE_MAX_SIZE  Max span queue depth (default: 512)
    PHOENIX_EXPORT_TIMEOUT  Export timeout in seconds (default: 5)

Required span attributes (per OMN-2734 contract):
    session_id              str   - Claude Code session identifier
    correlation_id          str   - Distributed tracing correlation ID
    manifest_injected       bool  - Whether patterns were injected
    injected_pattern_count  int   - Number of patterns injected (0 for control/empty)
    agent_matched           bool  - Whether an agent was matched by the router
    selected_agent          str   - Name of selected agent (empty string if none)
    injection_latency_ms    float - End-to-end injection latency in milliseconds
    cohort                  str   - A/B cohort: "control" or "treatment"

Usage::

    from phoenix_otel_exporter import emit_injection_span

    # Non-blocking — always safe to call from hook context
    emit_injection_span(
        session_id="abc-123",
        correlation_id="xyz-456",
        manifest_injected=True,
        injected_pattern_count=3,
        agent_matched=True,
        selected_agent="polymorphic-agent",
        injection_latency_ms=42.5,
        cohort="treatment",
    )

Related:
    OMN-2734: Wire Phoenix as OTEL observability backend
    OMN-1888: Manifest Injection Effectiveness Measurement

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

_DEFAULT_ENDPOINT = "http://localhost:6006/v1/traces"
_DEFAULT_QUEUE_MAX = 512
_DEFAULT_TIMEOUT_S = 5

# =============================================================================
# OTEL SDK imports — graceful degradation when SDK not installed
# =============================================================================

try:
    from opentelemetry import trace as otel_trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


# =============================================================================
# Singleton tracer provider (lazy, thread-safe)
# =============================================================================

_provider_lock = threading.Lock()
_tracer_provider: Any = None  # TracerProvider | None
_tracer: Any = None  # Tracer | None
_provider_initialized = False


def _is_enabled() -> bool:
    """Return True unless explicitly disabled via PHOENIX_OTEL_ENABLED=false/0."""
    val = os.environ.get("PHOENIX_OTEL_ENABLED", "true").strip().lower()
    return val not in ("0", "false", "no", "off")


def _get_endpoint() -> str:
    return os.environ.get("PHOENIX_OTEL_ENDPOINT", _DEFAULT_ENDPOINT).strip()


def _get_queue_max() -> int:
    try:
        return int(os.environ.get("PHOENIX_QUEUE_MAX_SIZE", str(_DEFAULT_QUEUE_MAX)))
    except (ValueError, TypeError):
        return _DEFAULT_QUEUE_MAX


def _get_timeout() -> int:
    try:
        return int(os.environ.get("PHOENIX_EXPORT_TIMEOUT", str(_DEFAULT_TIMEOUT_S)))
    except (ValueError, TypeError):
        return _DEFAULT_TIMEOUT_S


def _get_tracer() -> Any:
    """Return the OTEL Tracer, initializing the provider on first call.

    Thread-safe lazy initialization. Returns None if OTEL SDK is unavailable
    or if Phoenix export is disabled.

    Returns:
        opentelemetry.trace.Tracer instance, or None on failure.
    """
    global _tracer_provider, _tracer, _provider_initialized

    if not _OTEL_AVAILABLE:
        return None

    if not _is_enabled():
        return None

    with _provider_lock:
        if _provider_initialized:
            return _tracer

        try:
            endpoint = _get_endpoint()
            timeout_s = _get_timeout()
            queue_max = _get_queue_max()

            resource = Resource.create(
                {
                    "service.name": "omniclaude",
                }
            )

            exporter = OTLPSpanExporter(
                endpoint=endpoint,
                timeout=timeout_s,
            )

            processor = BatchSpanProcessor(
                exporter,
                max_queue_size=queue_max,
                # Drop oldest when queue is full (non-blocking)
                max_export_batch_size=min(512, queue_max),
            )

            _tracer_provider = TracerProvider(resource=resource)
            _tracer_provider.add_span_processor(processor)
            otel_trace.set_tracer_provider(_tracer_provider)

            _tracer = otel_trace.get_tracer("omniclaude.hooks")

            logger.debug(
                "PhoenixOTEL: tracer initialized (endpoint=%s, queue_max=%d, timeout=%ds)",
                endpoint,
                queue_max,
                timeout_s,
            )

        except Exception as exc:
            logger.warning("PhoenixOTEL: initialization failed: %r", exc)
            _tracer = None

        _provider_initialized = True
        return _tracer


def reset_tracer() -> None:
    """Reset the cached tracer, forcing re-initialization on next call.

    Intended for testing. Not for production use.
    """
    global _tracer_provider, _tracer, _provider_initialized

    with _provider_lock:
        _tracer_provider = None
        _tracer = None
        _provider_initialized = False
        logger.debug("PhoenixOTEL: tracer reset")


# =============================================================================
# Public API
# =============================================================================


def emit_injection_span(
    *,
    session_id: str,
    correlation_id: str,
    manifest_injected: bool,
    injected_pattern_count: int,
    agent_matched: bool,
    selected_agent: str,
    injection_latency_ms: float,
    cohort: str,
) -> bool:
    """Emit a manifest injection OTEL span to Phoenix.

    Non-blocking: span is queued by the async BatchSpanProcessor and exported
    in a background thread. Export errors are logged but never raised.

    Args:
        session_id: Claude Code session identifier.
        correlation_id: Distributed tracing correlation ID.
        manifest_injected: True if patterns were successfully injected.
        injected_pattern_count: Number of patterns injected (0 for control).
        agent_matched: True if the router matched a specific agent.
        selected_agent: Name of the matched agent (empty string if none).
        injection_latency_ms: End-to-end injection latency in milliseconds.
        cohort: A/B cohort assignment: "control" or "treatment".

    Returns:
        True if span was successfully started and queued for export.
        False if OTEL SDK unavailable, disabled, or span creation failed.
    """
    tracer = _get_tracer()
    if tracer is None:
        logger.debug("PhoenixOTEL: tracer not available, span skipped")
        return False

    try:
        with tracer.start_as_current_span("manifest_injection") as span:
            span.set_attribute("session_id", session_id)
            span.set_attribute("correlation_id", correlation_id)
            span.set_attribute("manifest_injected", manifest_injected)
            span.set_attribute("injected_pattern_count", injected_pattern_count)
            span.set_attribute("agent_matched", agent_matched)
            span.set_attribute("selected_agent", selected_agent)
            span.set_attribute("injection_latency_ms", injection_latency_ms)
            span.set_attribute("cohort", cohort)

        logger.debug(
            "PhoenixOTEL: span queued (session=%s, cohort=%s, injected=%s, patterns=%d)",
            session_id[:8] if session_id else "",
            cohort,
            manifest_injected,
            injected_pattern_count,
        )
        return True

    except Exception as exc:
        # Export errors must never propagate to the hook (R2)
        logger.warning("PhoenixOTEL: span emission failed: %r", exc)
        return False


__all__ = [
    "emit_injection_span",
    "reset_tracer",
]

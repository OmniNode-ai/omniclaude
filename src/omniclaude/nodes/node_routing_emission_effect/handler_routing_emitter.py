# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Handler for routing decision event emission via the emit daemon.

Implements ProtocolRoutingEmitter by delegating to the emit daemon's
``emit_event`` function (or a caller-supplied callable).  The handler
follows the dual-emission pattern where the daemon fans out a single
``routing.decision`` event to both the public observability topic and
the restricted intelligence topic.

Topic Mapping (handled by the emit daemon's EventRegistry):
    routing.decision ->
        onex.evt.omniclaude.routing-decision.v1       (preview-safe, broad access)
        onex.cmd.omniintelligence.routing-decision.v1  (full data, restricted)

Emission is non-blocking: failures are logged and returned as
``ModelEmissionResult(success=False, ...)`` -- never raised.

Design Decisions:
    - Constructor injection for ``emit_fn`` keeps plugins/ off the import path
    - Fallback dynamic import of ``emit_client_wrapper.emit_event`` supports
      hook-script contexts where the module is on ``sys.path``
    - No-op emitter when daemon is unavailable preserves the "hooks never block"
      invariant

.. versionadded:: 0.3.0
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Final
from uuid import UUID

from omniclaude.nodes.node_routing_emission_effect.models import (
    ModelEmissionRequest,
    ModelEmissionResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Daemon semantic event type for routing decisions (maps to Kafka topics).
EVENT_TYPE_ROUTING_DECISION: Final[str] = "routing.decision"

#: Public observability topic (preview-safe, broad access).
TOPIC_EVT: Final[str] = "onex.evt.omniclaude.routing-decision.v1"

#: Restricted intelligence topic (full data).
TOPIC_CMD: Final[str] = "onex.cmd.omniintelligence.routing-decision.v1"

#: Both topics combined for result reporting.
DUAL_TOPICS: Final[tuple[str, ...]] = (TOPIC_EVT, TOPIC_CMD)

# ---------------------------------------------------------------------------
# Emit function type alias
# ---------------------------------------------------------------------------

#: Signature: ``(event_type: str, payload: dict[str, object]) -> bool``
EmitFn = Callable[[str, dict[str, object]], bool]


def _noop_emit(event_type: str, payload: dict[str, object]) -> bool:  # noqa: ARG001
    """No-op emitter used when the daemon is unavailable."""
    return False


def _resolve_default_emit_fn() -> EmitFn:
    """Try to import ``emit_event`` from the emit client wrapper.

    The ``emit_client_wrapper`` module lives under ``plugins/onex/hooks/lib/``
    and is normally on ``sys.path`` in hook-script contexts.  When running
    outside that context (tests, standalone usage) the import will fail and
    we fall back to the no-op emitter.

    Returns:
        The resolved emit function, or :func:`_noop_emit` on failure.
    """
    try:
        from emit_client_wrapper import emit_event  # type: ignore[import-untyped]

        logger.debug("Resolved emit_event from emit_client_wrapper")
        return emit_event  # type: ignore[return-value]
    except ImportError:
        logger.warning(
            "emit_client_wrapper not on sys.path; "
            "routing emission will be no-op until an emit_fn is injected"
        )
        return _noop_emit


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class HandlerRoutingEmitter:
    """Handler that emits routing decision events via the emit daemon.

    Implements ``ProtocolRoutingEmitter`` by delegating to the existing
    emit client wrapper for Kafka event emission.  The emit daemon
    handles fan-out to dual topics (observability + intelligence).

    Args:
        emit_fn: Optional callable with signature
            ``(event_type: str, payload: dict[str, object]) -> bool``.
            When *None*, the handler attempts a dynamic import of
            ``emit_event`` from ``emit_client_wrapper``; if that fails
            a no-op emitter is used.

    Example::

        # With explicit injection (preferred in tests)
        handler = HandlerRoutingEmitter(emit_fn=mock_emit)

        # With auto-resolved default (hook-script context)
        handler = HandlerRoutingEmitter()
    """

    def __init__(self, emit_fn: EmitFn | None = None) -> None:
        self._emit_fn: EmitFn = (
            emit_fn if emit_fn is not None else _resolve_default_emit_fn()
        )

    # -- ProtocolRoutingEmitter interface ------------------------------------

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing."""
        return "kafka"

    async def emit_routing_decision(
        self,
        request: ModelEmissionRequest,
        correlation_id: UUID | None = None,
    ) -> ModelEmissionResult:
        """Emit a routing decision event to configured Kafka topics.

        Constructs a payload from *request*, delegates to the emit daemon
        via ``emit_fn``, and returns a :class:`ModelEmissionResult`
        indicating success or failure.

        The emit daemon handles the actual dual-emission fan-out to:
            - ``onex.evt.omniclaude.routing-decision.v1`` (preview-safe)
            - ``onex.cmd.omniintelligence.routing-decision.v1`` (full data)

        Args:
            request: Emission request with routing decision data.
            correlation_id: Optional trace ID.  Falls back to
                ``request.correlation_id`` if *None*.

        Returns:
            :class:`ModelEmissionResult` with emission outcome.
            On failure, ``success`` is ``False`` and ``error`` is populated.
            This method **never** raises.
        """
        resolved_cid = (
            correlation_id if correlation_id is not None else request.correlation_id
        )
        start = time.monotonic()

        try:
            payload = self._build_payload(request, resolved_cid)
            emitted = self._emit_fn(EVENT_TYPE_ROUTING_DECISION, payload)
            elapsed_ms = (time.monotonic() - start) * 1000.0

            if emitted:
                return ModelEmissionResult(
                    success=True,
                    correlation_id=resolved_cid,
                    topics_emitted=DUAL_TOPICS,
                    error=None,
                    duration_ms=elapsed_ms,
                )

            return ModelEmissionResult(
                success=False,
                correlation_id=resolved_cid,
                topics_emitted=(),
                error="Emit daemon returned failure (daemon unavailable or event dropped)",
                duration_ms=elapsed_ms,
            )

        except Exception as exc:
            # Graceful degradation: emission failures must not propagate.
            elapsed_ms = (time.monotonic() - start) * 1000.0
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.debug("Routing emission failed: %s", error_msg)

            return ModelEmissionResult(
                success=False,
                correlation_id=resolved_cid,
                topics_emitted=(),
                error=error_msg[:1000],
                duration_ms=elapsed_ms,
            )

    # -- Internal helpers ----------------------------------------------------

    @staticmethod
    def _build_payload(
        request: ModelEmissionRequest,
        correlation_id: UUID,
    ) -> dict[str, object]:
        """Build the event payload for the emit daemon.

        The payload shape matches the existing emission format in
        ``route_via_events_wrapper._emit_routing_decision`` so the
        daemon's EventRegistry can process it without changes.

        Args:
            request: The emission request model.
            correlation_id: Resolved correlation ID.

        Returns:
            Dictionary payload ready for the emit daemon.
        """
        return {
            "correlation_id": str(correlation_id),
            "session_id": request.session_id,
            "selected_agent": request.selected_agent,
            "confidence": request.confidence,
            "confidence_breakdown": request.confidence_breakdown.model_dump(),
            "routing_policy": request.routing_policy,
            "routing_path": request.routing_path,
            "prompt_preview": request.prompt_preview,
            "prompt_length": request.prompt_length,
            "emitted_at": request.emitted_at.isoformat(),
        }


__all__ = [
    "HandlerRoutingEmitter",
    "EVENT_TYPE_ROUTING_DECISION",
    "TOPIC_EVT",
    "TOPIC_CMD",
    "DUAL_TOPICS",
    "EmitFn",
]

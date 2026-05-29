# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Default handler for NodeAgentRouter — wraps AgentRouter with typed models.

Implements ProtocolAgentRouter by:
1. Initializing AgentRouter from lib/core/agent_router.py (lazy, thread-safe)
2. Calling AgentRouter.route() with the request fields
3. Converting AgentRecommendation dataclass list -> ModelAgentRouterResult

Design:
    The AgentRouter is initialized lazily on first route() call.  This avoids
    importing the registry path resolution logic at import time, which would
    couple this handler to the filesystem at module load.

    AgentRouter uses its own internal result cache (ResultCache), so this
    handler does not add a second cache layer.

    Failure contract: route() never raises.  On AgentRouter initialization
    failure or routing exception, returns an empty ModelAgentRouterResult
    (routed=False) and logs the error.

Ticket: OMN-11599
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING
from uuid import UUID

from omniclaude.nodes.node_agent_router.models import (
    ModelAgentRecommendation,
    ModelAgentRouterRequest,
    ModelAgentRouterResult,
)

if TYPE_CHECKING:
    from omniclaude.lib.core.agent_router import AgentRouter

logger = logging.getLogger(__name__)


class HandlerAgentRouter:
    """Default routing handler that wraps AgentRouter with typed ONEX models.

    Thread-safe: the AgentRouter instance is initialized once under a lock.
    Subsequent route() calls use the cached instance.

    Args:
        registry_path: Optional path to agent registry YAML. Uses
            AgentRouter's default path resolution when None.

    Attributes:
        handler_key: Registry key for handler lookup.
    """

    handler_key: str = "default"

    def __init__(self, registry_path: str | None = None) -> None:
        self._registry_path = registry_path
        self._router: AgentRouter | None = None
        self._init_lock = threading.Lock()
        self._init_failed = False

    # ------------------------------------------------------------------
    # ProtocolAgentRouter implementation
    # ------------------------------------------------------------------

    async def route(
        self,
        request: ModelAgentRouterRequest,
        correlation_id: UUID | None = None,
    ) -> ModelAgentRouterResult:
        """Route a user prompt to best-matching agent(s).

        Delegates to AgentRouter.route() and converts the result to
        typed ONEX models.

        Args:
            request: Routing request with user text, context, and limits.
            correlation_id: Ignored (AgentRouter uses session context, not
                correlation IDs). Accepted to satisfy the protocol.

        Returns:
            ModelAgentRouterResult with ranked recommendations.
            Returns routed=False with empty recommendations on failure.
        """
        router = self._get_router()
        if router is None:
            logger.warning(
                "HandlerAgentRouter: AgentRouter unavailable, returning empty result"
            )
            return ModelAgentRouterResult(recommendations=(), routed=False)

        try:
            context = dict(request.context) if request.context else {}
            raw_recommendations = router.route(
                user_request=request.user_request,
                context=context,
                max_recommendations=request.max_recommendations,
            )
        except Exception:  # noqa: BLE001 — boundary: routing must degrade gracefully
            logger.exception(
                "HandlerAgentRouter: route() raised unexpectedly for: %s",
                request.user_request[:80],
            )
            return ModelAgentRouterResult(recommendations=(), routed=False)

        recommendations = tuple(
            self._convert_recommendation(rec) for rec in raw_recommendations
        )
        return ModelAgentRouterResult(
            recommendations=recommendations,
            routed=len(recommendations) > 0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_router(self) -> AgentRouter | None:
        """Return the cached AgentRouter, initializing it on first call.

        Thread-safe: uses a lock to prevent double-initialization.
        If initialization previously failed, returns None immediately.
        """
        with self._init_lock:
            if self._router is not None:
                return self._router
            if self._init_failed:
                return None

            try:
                from omniclaude.lib.core.agent_router import (  # noqa: PLC0415
                    AgentRouter,
                )

                self._router = AgentRouter(registry_path=self._registry_path)
                logger.debug("HandlerAgentRouter: AgentRouter initialized")
            except Exception:  # noqa: BLE001 — boundary: init failure returns None
                self._init_failed = True
                logger.exception(
                    "HandlerAgentRouter: AgentRouter initialization failed"
                )

        return self._router

    @staticmethod
    def _convert_recommendation(rec: object) -> ModelAgentRecommendation:
        """Convert an AgentRecommendation dataclass to a typed ONEX model.

        Args:
            rec: AgentRecommendation instance from AgentRouter.route().

        Returns:
            ModelAgentRecommendation with the same data.
        """
        # Access via attribute names — avoids importing AgentRecommendation
        # which would create a hard dep on the legacy lib module at import time.
        confidence = getattr(rec, "confidence", None)
        return ModelAgentRecommendation(
            agent_name=getattr(rec, "agent_name", ""),
            agent_title=getattr(rec, "agent_title", ""),
            confidence=_safe_float(getattr(confidence, "total", 0.0)),
            trigger_score=_safe_float(getattr(confidence, "trigger_score", 0.0)),
            context_score=_safe_float(getattr(confidence, "context_score", 0.0)),
            capability_score=_safe_float(getattr(confidence, "capability_score", 0.0)),
            historical_score=_safe_float(getattr(confidence, "historical_score", 0.0)),
            confidence_explanation=str(getattr(confidence, "explanation", "") or "")[
                :500
            ],
            reason=str(getattr(rec, "reason", "") or "")[:500],
            definition_path=str(getattr(rec, "definition_path", "") or ""),
        )


def _safe_float(value: object, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi], returning lo on invalid input."""
    try:
        return max(lo, min(hi, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return lo


__all__ = ["HandlerAgentRouter"]

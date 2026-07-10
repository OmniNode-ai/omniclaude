# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed contract-level fake for the deterministic agent-routing boundary.

The agent router (``omniclaude.lib.core.agent_router.AgentRouter`` and its hooks
runtime copy) is a *deterministic keyword / trigger-matching* component — it is
NOT an inference / LLM egress boundary. Unit tests for the routing *wrapper*
(``route_via_events_wrapper``), the routing *event client*
(``routing_event_client``), and the routing *handler* (``HandlerAgentRouter``)
need to control what the router returns — a fixed list of recommendations, an
empty list, or a raised error — without standing up the real registry-backed
router (which reads a YAML registry from disk and builds a TriggerMatcher /
CapabilityIndex / ConfidenceScorer).

``FakeAgentRouter`` implements the router's real call surface as an ordinary
Python object with real methods:

* ``route(user_request, context=None, max_recommendations=5)`` — returns the
  configured ``recommendations`` (a copy) or raises the configured ``route_exc``,
  matching ``AgentRouter.route()``'s signature (positional or keyword args).
* ``registry`` — the ``{"agents": {...}}`` mapping the wrapper reads via
  ``_build_agent_definitions``.

Because it is a real object (not a ``MagicMock`` assigned to the routing
boundary), it satisfies the ``no_faked_boundary`` detector's
``mock_assigned_to_boundary`` rule (OMN-13500). Calls are recorded on
``route_calls`` so tests can assert dispatch behavior without mock spies.
"""

from __future__ import annotations

from typing import Any


class FakeAgentRouter:
    """Real, typed test double for the deterministic ``AgentRouter``.

    Attributes:
        recommendations: List returned by ``route()`` (copied on return).
        registry: ``{"agents": {...}}`` mapping read by the routing wrapper.
        route_exc: If set, ``route()`` raises this instead of returning.
        route_calls: Recorded call kwargs, one dict per ``route()`` invocation.
    """

    def __init__(
        self,
        *,
        recommendations: list[Any] | None = None,
        registry: dict[str, Any] | None = None,
        route_exc: BaseException | None = None,
    ) -> None:
        self.recommendations: list[Any] = (
            list(recommendations) if recommendations is not None else []
        )
        self.registry: dict[str, Any] = (
            registry if registry is not None else {"agents": {}}
        )
        self.route_exc: BaseException | None = route_exc
        self.route_calls: list[dict[str, Any]] = []

    def route(
        self,
        user_request: str = "",
        context: dict[str, Any] | None = None,
        max_recommendations: int = 5,
        **kwargs: Any,
    ) -> list[Any]:
        """Return the configured recommendations (copy) or raise ``route_exc``.

        Mirrors ``AgentRouter.route()``; accepts the same positional/keyword
        args and records every call on ``route_calls``.
        """
        self.route_calls.append(
            {
                "user_request": user_request,
                "context": context,
                "max_recommendations": max_recommendations,
                **kwargs,
            }
        )
        if self.route_exc is not None:
            raise self.route_exc
        return list(self.recommendations)

    @property
    def route_call_count(self) -> int:
        """Number of times ``route()`` has been invoked."""
        return len(self.route_calls)

    @property
    def last_route_call(self) -> dict[str, Any]:
        """Recorded kwargs of the most recent ``route()`` call."""
        if not self.route_calls:
            raise AssertionError("FakeAgentRouter.route() was never called")
        return self.route_calls[-1]


__all__ = ["FakeAgentRouter"]

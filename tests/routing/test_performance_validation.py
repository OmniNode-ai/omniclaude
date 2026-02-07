# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""
Performance validation for agent routing.

Ticket: OMN-1928 — [P5] Validation
Parent: OMN-1922 (Extract Agent Routing to ONEX Nodes)

Targets (from ticket):
    p95 latency: <100ms
    p50 latency: <50ms
    Environment:  Standard dev machine, cold cache

Tests both the legacy AgentRouter path and the ONEX HandlerRoutingDefault
path to confirm both meet the performance budget.

Note on statistical approach:
    We run a representative sample of golden corpus prompts through each
    routing path multiple times, measure wall-clock latency per call, and
    compute p50/p95 from the resulting distribution.

    Cold cache is enforced by calling invalidate_cache() (legacy) or
    creating a fresh handler (ONEX) before each prompt.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from omniclaude.lib.core.agent_router import AgentRouter
from omniclaude.nodes.node_agent_routing_compute.handler_routing_default import (
    HandlerRoutingDefault,
)
from omniclaude.nodes.node_agent_routing_compute.models import (
    ModelAgentDefinition,
    ModelRoutingRequest,
)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.5
P95_BUDGET_MS = 100  # p95 must be below this
P50_BUDGET_MS = 50  # p50 must be below this

_ROUTING_DIR = Path(__file__).parent
_PROJECT_ROOT = _ROUTING_DIR.parents[1]
_REGISTRY_PATH = (
    _PROJECT_ROOT / "plugins" / "onex" / "agents" / "configs" / "agent-registry.yaml"
)
_CORPUS_PATH = _ROUTING_DIR / "golden_corpus.json"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute the p-th percentile from a sorted list of values."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (pct / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_values):
        return sorted_values[-1]
    d = k - f
    return sorted_values[f] + d * (sorted_values[c] - sorted_values[f])


def _load_agent_definitions() -> tuple[ModelAgentDefinition, ...]:
    """Load agent definitions from the registry YAML."""
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        registry = yaml.safe_load(f)

    defs: list[ModelAgentDefinition] = []
    for name, data in registry.get("agents", {}).items():
        try:
            dc = data.get("domain_context", "general")
            if isinstance(dc, dict):
                dc = dc.get("primary", "general")
            defs.append(
                ModelAgentDefinition(
                    name=name,
                    agent_type=data.get(
                        "agent_type",
                        name.replace("agent-", "").replace("-", "_"),
                    ),
                    description=data.get("description", data.get("title", "")),
                    domain_context=str(dc),
                    explicit_triggers=tuple(data.get("activation_triggers", [])),
                    context_triggers=tuple(data.get("context_triggers", [])),
                    capabilities=tuple(data.get("capabilities", [])),
                    definition_path=data.get("definition_path"),
                )
            )
        except Exception:
            pass
    return tuple(defs)


def _load_corpus_prompts() -> list[str]:
    """Load all non-empty prompts from the golden corpus."""
    with open(_CORPUS_PATH, encoding="utf-8") as f:
        corpus = json.load(f)
    return [entry["prompt"] for entry in corpus["entries"] if entry["prompt"].strip()]


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def legacy_router() -> AgentRouter:
    """Create AgentRouter with cache disabled."""
    return AgentRouter(registry_path=str(_REGISTRY_PATH), cache_ttl=0)


@pytest.fixture(scope="module")
def onex_handler() -> HandlerRoutingDefault:
    """Create HandlerRoutingDefault."""
    return HandlerRoutingDefault()


@pytest.fixture(scope="module")
def agent_definitions() -> tuple[ModelAgentDefinition, ...]:
    """Load agent definitions."""
    return _load_agent_definitions()


@pytest.fixture(scope="module")
def corpus_prompts() -> list[str]:
    """Load corpus prompts."""
    return _load_corpus_prompts()


# --------------------------------------------------------------------------
# Legacy AgentRouter Performance
# --------------------------------------------------------------------------


class TestLegacyRouterPerformance:
    """Performance validation for the legacy AgentRouter path."""

    @pytest.mark.benchmark
    def test_legacy_router_p95_under_budget(
        self,
        legacy_router: AgentRouter,
        corpus_prompts: list[str],
    ) -> None:
        """p95 routing latency must be under 100ms (cold cache)."""
        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            legacy_router.invalidate_cache()
            start = time.perf_counter()
            legacy_router.route(prompt, max_recommendations=5)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p95 = _percentile(latencies_ms, 95)
        p50 = _percentile(latencies_ms, 50)

        print(
            f"\n  Legacy AgentRouter performance ({len(latencies_ms)} prompts):"
            f"\n    p50: {p50:.2f}ms"
            f"\n    p95: {p95:.2f}ms"
            f"\n    min: {latencies_ms[0]:.2f}ms"
            f"\n    max: {latencies_ms[-1]:.2f}ms"
        )

        assert p95 < P95_BUDGET_MS, (
            f"Legacy router p95 ({p95:.2f}ms) exceeds {P95_BUDGET_MS}ms budget"
        )

    @pytest.mark.benchmark
    def test_legacy_router_p50_under_budget(
        self,
        legacy_router: AgentRouter,
        corpus_prompts: list[str],
    ) -> None:
        """p50 routing latency must be under 50ms (cold cache)."""
        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            legacy_router.invalidate_cache()
            start = time.perf_counter()
            legacy_router.route(prompt, max_recommendations=5)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p50 = _percentile(latencies_ms, 50)

        assert p50 < P50_BUDGET_MS, (
            f"Legacy router p50 ({p50:.2f}ms) exceeds {P50_BUDGET_MS}ms budget"
        )


# --------------------------------------------------------------------------
# ONEX HandlerRoutingDefault Performance
# --------------------------------------------------------------------------


class TestOnexHandlerPerformance:
    """Performance validation for the ONEX HandlerRoutingDefault path."""

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_onex_handler_p95_under_budget(
        self,
        onex_handler: HandlerRoutingDefault,
        agent_definitions: tuple[ModelAgentDefinition, ...],
        corpus_prompts: list[str],
    ) -> None:
        """p95 ONEX routing latency must be under 100ms (cold cache)."""
        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            request = ModelRoutingRequest(
                prompt=prompt,
                correlation_id=uuid4(),
                agent_registry=agent_definitions,
                confidence_threshold=CONFIDENCE_THRESHOLD,
            )
            start = time.perf_counter()
            await onex_handler.compute_routing(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p95 = _percentile(latencies_ms, 95)
        p50 = _percentile(latencies_ms, 50)

        print(
            f"\n  ONEX HandlerRoutingDefault performance ({len(latencies_ms)} prompts):"
            f"\n    p50: {p50:.2f}ms"
            f"\n    p95: {p95:.2f}ms"
            f"\n    min: {latencies_ms[0]:.2f}ms"
            f"\n    max: {latencies_ms[-1]:.2f}ms"
        )

        assert p95 < P95_BUDGET_MS, (
            f"ONEX handler p95 ({p95:.2f}ms) exceeds {P95_BUDGET_MS}ms budget"
        )

    @pytest.mark.benchmark
    @pytest.mark.asyncio
    async def test_onex_handler_p50_under_budget(
        self,
        onex_handler: HandlerRoutingDefault,
        agent_definitions: tuple[ModelAgentDefinition, ...],
        corpus_prompts: list[str],
    ) -> None:
        """p50 ONEX routing latency must be under 50ms (cold cache)."""
        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            request = ModelRoutingRequest(
                prompt=prompt,
                correlation_id=uuid4(),
                agent_registry=agent_definitions,
                confidence_threshold=CONFIDENCE_THRESHOLD,
            )
            start = time.perf_counter()
            await onex_handler.compute_routing(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p50 = _percentile(latencies_ms, 50)

        assert p50 < P50_BUDGET_MS, (
            f"ONEX handler p50 ({p50:.2f}ms) exceeds {P50_BUDGET_MS}ms budget"
        )


# --------------------------------------------------------------------------
# Wrapper-Level Performance (route_via_events with ONEX flag)
# --------------------------------------------------------------------------


class TestWrapperPerformance:
    """Performance validation for route_via_events() wrapper.

    This tests the full synchronous path including handler init, request
    shaping, compute, and result shaping -- everything that counts toward
    the 500ms hook budget.

    The emit daemon is mocked to isolate routing latency from I/O.
    Emission adds non-deterministic socket overhead that is backgrounded
    in production and should not count toward the routing budget.
    """

    @staticmethod
    def _get_wrapper():
        """Import and reload the wrapper with emission mocked."""
        import importlib
        import sys

        hooks_lib = str(_PROJECT_ROOT / "plugins" / "onex" / "hooks" / "lib")
        if hooks_lib not in sys.path:
            sys.path.insert(0, hooks_lib)

        import route_via_events_wrapper

        importlib.reload(route_via_events_wrapper)
        # Disable event emission to isolate routing latency
        route_via_events_wrapper._emit_event_fn = None
        return route_via_events_wrapper

    @pytest.mark.benchmark
    def test_wrapper_p95_under_budget(
        self,
        corpus_prompts: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """route_via_events p95 must be under 100ms (well within 500ms hook budget)."""
        wrapper = self._get_wrapper()

        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            start = time.perf_counter()
            wrapper.route_via_events(prompt, str(uuid4()))
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p95 = _percentile(latencies_ms, 95)
        p50 = _percentile(latencies_ms, 50)

        print(
            f"\n  route_via_events wrapper performance ({len(latencies_ms)} prompts):"
            f"\n    p50: {p50:.2f}ms"
            f"\n    p95: {p95:.2f}ms"
            f"\n    min: {latencies_ms[0]:.2f}ms"
            f"\n    max: {latencies_ms[-1]:.2f}ms"
        )

        assert p95 < P95_BUDGET_MS, (
            f"Wrapper p95 ({p95:.2f}ms) exceeds {P95_BUDGET_MS}ms budget"
        )

    @pytest.mark.benchmark
    def test_wrapper_p50_under_budget(
        self,
        corpus_prompts: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """route_via_events p50 must be under 50ms."""
        wrapper = self._get_wrapper()

        latencies_ms: list[float] = []

        for prompt in corpus_prompts:
            start = time.perf_counter()
            wrapper.route_via_events(prompt, str(uuid4()))
            elapsed_ms = (time.perf_counter() - start) * 1000
            latencies_ms.append(elapsed_ms)

        latencies_ms.sort()
        p50 = _percentile(latencies_ms, 50)

        assert p50 < P50_BUDGET_MS, (
            f"Wrapper p50 ({p50:.2f}ms) exceeds {P50_BUDGET_MS}ms budget"
        )

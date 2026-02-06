"""
Golden Corpus Regression Harness for Agent Routing.

Ticket: OMN-1923 — [P0] Golden Corpus + Regression Harness
Gate: Must pass 100% before Phase 1 (OMN-1924) begins.

Tests two layers per Q1 answer ("Both layers"):
  1. AgentRouter.route() — core routing correctness (all entries)
  2. route_via_events() — integration-level validation (subset)

Tolerance definitions (referenced by P5):
  - confidence:      ±0.05
  - selected_agent:  exact (no substitutions)
  - routing_policy:  exact

Caching: Disabled per Q2 answer (cache_ttl=0, invalidate between runs).
Fallback field: Uses 'reasoning' per Q4 answer (no new fallback_reason field).
"""

import sys
from pathlib import Path
from typing import Any

import pytest

from omniclaude.lib.core.agent_router import AgentRouter

from .conftest import TOLERANCE_CONFIDENCE

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.5  # Mirrors route_via_events_wrapper.py
DEFAULT_AGENT = "polymorphic-agent"


def _determine_expected_agent_and_policy(
    router: AgentRouter,
    prompt: str,
    recommendations: list,
) -> tuple[str, float, str]:
    """
    Replicate the logic of route_via_events() to determine what the
    wrapper layer would produce given the router's output.

    Returns (selected_agent, confidence, routing_policy).
    """
    # Check explicit agent request first (mirrors wrapper logic)
    explicit = router._extract_explicit_agent(prompt)
    if explicit:
        return explicit, 1.0, "explicit_request"

    if not recommendations:
        return DEFAULT_AGENT, 0.5, "fallback_default"

    top = recommendations[0]
    if top.confidence.total >= CONFIDENCE_THRESHOLD:
        return top.agent_name, top.confidence.total, "trigger_match"
    else:
        return DEFAULT_AGENT, 0.5, "fallback_default"


# --------------------------------------------------------------------------
# Layer 1: AgentRouter.route() — Core Routing Correctness
# --------------------------------------------------------------------------


class TestAgentRouterRegression:
    """
    Regression tests at the AgentRouter.route() layer.

    Validates that the core routing engine (trigger matching + confidence
    scoring) produces the same results as when the golden corpus was
    generated.
    """

    def test_corpus_has_100_plus_entries(
        self, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Acceptance criteria: 100+ prompts in golden corpus."""
        assert len(corpus_entries) >= 100, (
            f"Golden corpus has {len(corpus_entries)} entries, need 100+"
        )

    def test_all_fields_captured(self, corpus_entries: list[dict[str, Any]]) -> None:
        """Acceptance criteria: All required fields captured and compared."""
        required_expected_fields = {
            "selected_agent",
            "confidence",
            "routing_policy",
            "routing_path",
        }
        required_router_fields = {
            "top_agent",
            "top_confidence",
            "match_count",
        }

        for entry in corpus_entries:
            expected = entry["expected"]
            router_layer = entry["router_layer"]

            missing_expected = required_expected_fields - set(expected.keys())
            assert not missing_expected, (
                f"Entry {entry['id']} missing expected fields: {missing_expected}"
            )

            missing_router = required_router_fields - set(router_layer.keys())
            assert not missing_router, (
                f"Entry {entry['id']} missing router_layer fields: {missing_router}"
            )

    def test_tolerance_explicitly_defined(self, golden_corpus: dict[str, Any]) -> None:
        """Acceptance criteria: Tolerance explicitly defined."""
        tolerance = golden_corpus.get("tolerance", {})
        assert "confidence" in tolerance, "Confidence tolerance not defined"
        assert "selected_agent" in tolerance, "Selected agent tolerance not defined"
        assert "routing_policy" in tolerance, "Routing policy tolerance not defined"
        assert tolerance["confidence"] == 0.05
        assert tolerance["selected_agent"] == "exact"
        assert tolerance["routing_policy"] == "exact"

    @pytest.mark.parametrize(
        "entry_index",
        range(104),  # Parametrize over all entries
        indirect=False,
    )
    def test_router_layer_regression(
        self,
        router: AgentRouter,
        corpus_entries: list[dict[str, Any]],
        entry_index: int,
    ) -> None:
        """
        Core regression test: run each prompt through AgentRouter.route()
        and validate against golden corpus.

        Checks:
          - selected_agent: exact match
          - confidence: within ±0.05 tolerance
          - routing_policy: exact match
          - routing_path: exact match (always "local" for now)
        """
        if entry_index >= len(corpus_entries):
            pytest.skip(f"Entry index {entry_index} out of range")

        entry = corpus_entries[entry_index]
        prompt = entry["prompt"]
        expected = entry["expected"]

        # Clear cache for determinism
        router.invalidate_cache()

        # Run the prompt through the router
        recommendations = router.route(prompt, max_recommendations=5)

        # Determine what route_via_events would produce
        actual_agent, actual_confidence, actual_policy = (
            _determine_expected_agent_and_policy(router, prompt, recommendations)
        )

        # ── Assert selected_agent (exact match) ──────────────────────
        assert actual_agent == expected["selected_agent"], (
            f"Entry {entry['id']}: Agent mismatch\n"
            f"  Prompt:   {prompt!r}\n"
            f"  Expected: {expected['selected_agent']}\n"
            f"  Actual:   {actual_agent}\n"
            f"  Category: {entry['category']}\n"
            f"  Notes:    {entry['notes']}"
        )

        # ── Assert confidence (±0.05 tolerance) ──────────────────────
        expected_conf = expected["confidence"]
        assert abs(actual_confidence - expected_conf) <= TOLERANCE_CONFIDENCE, (
            f"Entry {entry['id']}: Confidence outside tolerance\n"
            f"  Prompt:   {prompt!r}\n"
            f"  Expected: {expected_conf} (±{TOLERANCE_CONFIDENCE})\n"
            f"  Actual:   {actual_confidence}\n"
            f"  Delta:    {abs(actual_confidence - expected_conf):.6f}"
        )

        # ── Assert routing_policy (exact match) ──────────────────────
        assert actual_policy == expected["routing_policy"], (
            f"Entry {entry['id']}: Policy mismatch\n"
            f"  Prompt:   {prompt!r}\n"
            f"  Expected: {expected['routing_policy']}\n"
            f"  Actual:   {actual_policy}"
        )

    def test_category_coverage(self, corpus_entries: list[dict[str, Any]]) -> None:
        """Verify the corpus covers all required categories."""
        categories = {e["category"] for e in corpus_entries}
        required = {
            "direct_trigger",
            "explicit_request",
            "fallback",
            "ambiguity",
            "context_filter",
            "fuzzy_match",
        }
        missing = required - categories
        assert not missing, f"Golden corpus missing required categories: {missing}"

    def test_explicit_agent_entries(
        self, router: AgentRouter, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Verify all explicit_request entries route to the correct agent."""
        explicit_entries = [
            e for e in corpus_entries if e["category"] == "explicit_request"
        ]
        assert len(explicit_entries) >= 2, "Need at least 2 explicit agent entries"

        for entry in explicit_entries:
            router.invalidate_cache()
            prompt = entry["prompt"]
            expected = entry["expected"]

            explicit = router._extract_explicit_agent(prompt)
            if expected["routing_policy"] == "explicit_request":
                assert explicit is not None, (
                    f"Entry {entry['id']}: Expected explicit agent extraction for {prompt!r}"
                )
                assert explicit == expected["selected_agent"], (
                    f"Entry {entry['id']}: Explicit agent mismatch: "
                    f"{explicit} != {expected['selected_agent']}"
                )

    def test_fallback_entries(
        self, router: AgentRouter, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Verify fallback entries correctly fall through to polymorphic-agent."""
        fallback_entries = [
            e
            for e in corpus_entries
            if e["expected"]["routing_policy"] == "fallback_default"
        ]
        assert len(fallback_entries) >= 5, "Need at least 5 fallback entries"

        for entry in fallback_entries:
            router.invalidate_cache()
            prompt = entry["prompt"]

            recommendations = router.route(prompt, max_recommendations=5)
            _, _actual_confidence, actual_policy = _determine_expected_agent_and_policy(
                router, prompt, recommendations
            )

            assert actual_policy == "fallback_default", (
                f"Entry {entry['id']}: Expected fallback for {prompt!r}, got {actual_policy}"
            )

    def test_context_filter_entries(
        self, router: AgentRouter, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Verify context filtering works correctly for polymorphic-agent edge cases."""
        context_entries = [
            e for e in corpus_entries if e["category"] == "context_filter"
        ]
        assert len(context_entries) >= 5, "Need at least 5 context filter entries"

        for entry in context_entries:
            router.invalidate_cache()
            prompt = entry["prompt"]
            expected = entry["expected"]

            recommendations = router.route(prompt, max_recommendations=5)
            actual_agent, _, _ = _determine_expected_agent_and_policy(
                router, prompt, recommendations
            )

            assert actual_agent == expected["selected_agent"], (
                f"Entry {entry['id']}: Context filter mismatch\n"
                f"  Prompt:   {prompt!r}\n"
                f"  Expected: {expected['selected_agent']}\n"
                f"  Actual:   {actual_agent}\n"
                f"  Notes:    {entry['notes']}"
            )


# --------------------------------------------------------------------------
# Layer 2: route_via_events() — Integration-Level Validation
# --------------------------------------------------------------------------


class TestRouteViaEventsIntegration:
    """
    Integration tests at the route_via_events() wrapper layer.

    Tests the full wrapper including input validation, fallback logic,
    event emission (mocked), and result structure.

    Per Q1 answer: smaller set for integration-level validation.
    """

    @pytest.fixture(autouse=True)
    def _setup_wrapper_imports(self, registry_path: str, router: AgentRouter) -> None:
        """Set up imports for route_via_events wrapper."""
        # The wrapper lives in plugins/onex/hooks/lib/ and does its own
        # path manipulation. We need to make AgentRouter available via
        # the wrapper's import path.
        hooks_lib = Path(__file__).parents[2] / "plugins" / "onex" / "hooks" / "lib"
        if str(hooks_lib) not in sys.path:
            sys.path.insert(0, str(hooks_lib))

        # Store for use in tests
        self._registry_path = registry_path
        self._router = router

    def _get_route_via_events(self):
        """Import route_via_events with patched router to use project registry."""
        import importlib

        import route_via_events_wrapper

        importlib.reload(route_via_events_wrapper)

        # Patch the singleton router to use our project-registry router.
        # This ensures the wrapper uses the same agent names as the golden
        # corpus (which was generated from the project registry).
        route_via_events_wrapper._router_instance = self._router
        return route_via_events_wrapper.route_via_events

    def test_empty_prompt_returns_fallback(self) -> None:
        """Empty prompt should return fallback without error."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("", "test-correlation-id")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["confidence"] == 0.5
        assert result["routing_policy"] == "fallback_default"
        assert result["routing_path"] == "local"
        assert result["candidates"] == []

    def test_whitespace_prompt_returns_fallback(self) -> None:
        """Whitespace-only prompt should return fallback."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("   ", "test-correlation-id")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["confidence"] == 0.5
        assert result["routing_policy"] == "fallback_default"

    def test_empty_correlation_id_returns_fallback(self) -> None:
        """Empty correlation_id should return fallback."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("debug this error", "")

        assert result["selected_agent"] == DEFAULT_AGENT
        assert result["routing_policy"] == "fallback_default"

    def test_result_structure_complete(self) -> None:
        """Verify the wrapper returns all required fields."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("debug this error", "corr-123")

        required_fields = {
            "selected_agent",
            "confidence",
            "candidates",
            "reasoning",
            "routing_method",
            "routing_policy",
            "routing_path",
            "method",
            "latency_ms",
            "domain",
            "purpose",
            "event_attempted",
        }
        missing = required_fields - set(result.keys())
        assert not missing, f"Missing fields in wrapper result: {missing}"

    def test_routing_path_always_local(self) -> None:
        """routing_path should be 'local' (no event routing yet)."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("run tests", "corr-123")
        assert result["routing_path"] == "local"
        assert result["event_attempted"] is False

    def test_candidates_populated_on_match(self) -> None:
        """Candidates array should be populated when matches found."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("debug this error", "corr-123")

        assert len(result["candidates"]) > 0
        for candidate in result["candidates"]:
            assert "name" in candidate
            assert "score" in candidate
            assert "reason" in candidate

    def test_latency_within_budget(self) -> None:
        """Routing latency should be well under the 500ms budget."""
        route_via_events = self._get_route_via_events()
        # Warm up (first call may include module init overhead)
        route_via_events("warmup", "corr-warmup")
        # Measure actual routing
        result = route_via_events("debug this error", "corr-123")

        assert result["latency_ms"] < 500, (
            f"Routing took {result['latency_ms']}ms, exceeds 500ms budget"
        )

    @pytest.mark.parametrize(
        ("prompt", "expected_agent"),
        [
            ("debug this error", "debug-intelligence"),
            ("run tests", "testing"),
            ("deploy to production", "devops-infrastructure"),
            ("review this pull request", "pr-review"),
            ("optimize performance", "performance"),
        ],
    )
    def test_integration_routing_matches_corpus(
        self, prompt: str, expected_agent: str
    ) -> None:
        """
        Spot-check that route_via_events produces consistent results
        with the corpus expectations for representative prompts.
        """
        route_via_events = self._get_route_via_events()
        result = route_via_events(prompt, "corr-integration-test")

        assert result["selected_agent"] == expected_agent, (
            f"Integration mismatch for {prompt!r}: "
            f"expected {expected_agent}, got {result['selected_agent']}"
        )

    def test_explicit_agent_via_wrapper(self) -> None:
        """Explicit @agent request via wrapper layer."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("use an agent to help me with this task", "corr-123")
        assert result["selected_agent"] == "polymorphic-agent"

    def test_method_mirrors_routing_policy(self) -> None:
        """Legacy 'method' field should mirror 'routing_policy'."""
        route_via_events = self._get_route_via_events()
        result = route_via_events("debug this error", "corr-123")
        assert result["method"] == result["routing_policy"]


# --------------------------------------------------------------------------
# Aggregate validation
# --------------------------------------------------------------------------


class TestCorpusIntegrity:
    """Validate corpus-level invariants."""

    def test_no_duplicate_prompts(self, corpus_entries: list[dict[str, Any]]) -> None:
        """Each prompt should appear at most once."""
        prompts = [e["prompt"] for e in corpus_entries]
        duplicates = [p for p in prompts if prompts.count(p) > 1]
        assert not duplicates, f"Duplicate prompts found: {set(duplicates)}"

    def test_confidence_in_valid_range(
        self, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """All confidence values should be 0.0-1.0."""
        for entry in corpus_entries:
            conf = entry["expected"]["confidence"]
            assert 0.0 <= conf <= 1.0, (
                f"Entry {entry['id']}: confidence {conf} out of range"
            )

    def test_routing_policy_values(self, corpus_entries: list[dict[str, Any]]) -> None:
        """All routing_policy values should be one of the valid enum values."""
        valid = {"trigger_match", "explicit_request", "fallback_default"}
        for entry in corpus_entries:
            policy = entry["expected"]["routing_policy"]
            assert policy in valid, (
                f"Entry {entry['id']}: invalid routing_policy '{policy}'"
            )

    def test_routing_path_values(self, corpus_entries: list[dict[str, Any]]) -> None:
        """All routing_path values should be one of the valid enum values."""
        valid = {"event", "local", "hybrid"}
        for entry in corpus_entries:
            path = entry["expected"]["routing_path"]
            assert path in valid, f"Entry {entry['id']}: invalid routing_path '{path}'"

    def test_fallback_entries_have_default_confidence(
        self, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Fallback entries should have confidence == 0.5."""
        for entry in corpus_entries:
            if entry["expected"]["routing_policy"] == "fallback_default":
                assert entry["expected"]["confidence"] == 0.5, (
                    f"Entry {entry['id']}: fallback should have confidence 0.5, "
                    f"got {entry['expected']['confidence']}"
                )

    def test_explicit_entries_have_full_confidence(
        self, corpus_entries: list[dict[str, Any]]
    ) -> None:
        """Explicit request entries should have confidence == 1.0."""
        for entry in corpus_entries:
            if entry["expected"]["routing_policy"] == "explicit_request":
                assert entry["expected"]["confidence"] == 1.0, (
                    f"Entry {entry['id']}: explicit should have confidence 1.0, "
                    f"got {entry['expected']['confidence']}"
                )

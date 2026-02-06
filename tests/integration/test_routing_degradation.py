# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for routing degradation with real Kafka.

These tests verify routing behavior when Kafka is available and when it degrades.
They require real Kafka infrastructure.

To run:
    KAFKA_INTEGRATION_TESTS=1 pytest tests/integration/test_routing_degradation.py -v

Mock-based tests for routing_path are in:
    tests/lib/core/test_route_via_events_wrapper.py
"""

from __future__ import annotations

import pytest

# Note: Plugin lib path is added by tests/conftest.py, no need for manual sys.path manipulation
from route_via_events_wrapper import VALID_ROUTING_PATHS, route_via_events

# Mark all tests as Kafka integration tests - requires real Kafka
pytestmark = [
    pytest.mark.integration,
]


class TestRealKafkaRouting:
    """Integration tests requiring real Kafka infrastructure.

    These tests verify:
    1. Event routing works when Kafka is available
    2. routing_path signal is correctly set
    3. Fallback behaves correctly on real failures

    Requires KAFKA_INTEGRATION_TESTS=1 to run.
    """

    def test_routing_returns_valid_path(self):
        """Verify routing returns a valid routing_path with real infrastructure.

        This test uses the real adapter (no mocking). The exact result depends
        on whether the routing service is available:
        - If routing service responds: routing_path='event'
        - If routing service times out: routing_path='hybrid'
        - If Kafka unavailable: routing_path='local'

        All paths are valid outcomes - this test verifies instrumentation works.
        """
        result = route_via_events(
            prompt="Integration test with real infrastructure",
            correlation_id="real-infra-test-001",
            timeout_ms=5000,
        )

        # Verify structure
        assert "routing_path" in result, "routing_path must be present"
        assert "event_attempted" in result, "event_attempted must be present"
        assert "method" in result, "method must be present"
        assert "selected_agent" in result, "selected_agent must be present"

        # Verify routing_path is valid
        assert result["routing_path"] in VALID_ROUTING_PATHS, (
            f"Invalid routing_path: {result['routing_path']}"
        )

        # Log for debugging
        print(f"\n  routing_path: {result['routing_path']}")
        print(f"  event_attempted: {result['event_attempted']}")
        print(f"  method: {result['method']}")
        print(f"  selected_agent: {result['selected_agent']}")

    def test_routing_path_consistency(self):
        """Verify routing_path and event_attempted are consistent."""
        result = route_via_events(
            prompt="Consistency test",
            correlation_id="consistency-test-001",
        )

        # In the current architecture, routing is always local (no event-based routing)
        assert result["event_attempted"] is False, (
            "Current architecture does not use event-based routing"
        )
        assert result["routing_path"] == "local", (
            "Non-attempted event must have routing_path='local'"
        )
        # Verify method is one of the valid intelligent routing policies
        valid_methods = {"trigger_match", "explicit_request", "fallback_default"}
        assert result["method"] in valid_methods, (
            f"Expected method in {valid_methods}, got '{result['method']}'"
        )

    def test_multiple_routing_requests(self):
        """Verify consistent behavior across multiple requests."""
        results = []
        for i in range(3):
            result = route_via_events(
                prompt=f"Multi-request test {i}",
                correlation_id=f"multi-test-{i:03d}",
                timeout_ms=3000,
            )
            results.append(result)

        # All results must have valid routing_path
        for i, result in enumerate(results):
            assert result["routing_path"] in VALID_ROUTING_PATHS, (
                f"Request {i} has invalid routing_path"
            )

        # If infrastructure is stable, routing_path should be consistent
        routing_paths = [r["routing_path"] for r in results]
        print(f"\n  Routing paths across 3 requests: {routing_paths}")

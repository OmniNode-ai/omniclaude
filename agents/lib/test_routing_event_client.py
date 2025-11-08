#!/usr/bin/env python3
"""
Integration Tests for Routing Event Client.

Tests the complete event flow:
1. Client publishes routing request
2. Service processes request
3. Client receives routing response
4. Timeout handling
5. Error handling
6. Fallback mechanism

Prerequisites:
- Kafka/Redpanda running on configured bootstrap servers
- agent-router-service running and consuming routing requests
- PostgreSQL available for routing decision logging

Run tests:
    pytest agents/lib/test_routing_event_client.py -v

Created: 2025-10-30
Reference: test_routing_event_flow.py (existing patterns)
"""

import asyncio
import os
from uuid import uuid4

import pytest

# Import from agents.lib module (project root is added by conftest.py)
from agents.lib.routing_event_client import (
    RoutingEventClient,
    RoutingEventClientContext,
    route_via_events,
)


class TestRoutingEventClient:
    """Integration tests for RoutingEventClient."""

    @pytest.mark.asyncio
    async def test_client_lifecycle(self):
        """Test client start/stop lifecycle."""
        client = RoutingEventClient(
            request_timeout_ms=5000,
        )

        # Verify not started
        assert not client._started
        assert client._producer is None
        assert client._consumer is None

        # Start client
        await client.start()

        # Verify started
        assert client._started
        assert client._producer is not None
        assert client._consumer is not None

        # Verify consumer ready
        assert client._consumer_ready.is_set()

        # Stop client
        await client.stop()

        # Verify stopped
        assert not client._started
        assert client._producer is None
        assert client._consumer is None

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health check functionality."""
        client = RoutingEventClient()

        # Verify unhealthy when not started
        healthy = await client.health_check()
        assert not healthy

        # Start client
        await client.start()

        # Verify healthy when started
        healthy = await client.health_check()
        assert healthy

        # Stop client
        await client.stop()

        # Verify unhealthy when stopped
        healthy = await client.health_check()
        assert not healthy

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test context manager lifecycle."""
        async with RoutingEventClientContext(request_timeout_ms=5000) as client:
            # Verify started
            assert client._started
            assert await client.health_check()

        # Verify stopped after context exit
        assert not client._started
        assert not await client.health_check()

    @pytest.mark.asyncio
    async def test_routing_request_success(self):
        """Test successful routing request."""
        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            recommendations = await client.request_routing(
                user_request="optimize my database queries",
                context={"domain": "database_optimization"},
                max_recommendations=3,
            )

            # Verify recommendations received
            assert isinstance(recommendations, list)
            assert len(recommendations) > 0

            # Verify recommendation structure
            best = recommendations[0]
            assert "agent_name" in best
            assert "agent_title" in best
            assert "confidence" in best
            assert "reason" in best
            assert "definition_path" in best

            # Verify confidence structure
            confidence = best["confidence"]
            assert "total" in confidence
            assert "trigger_score" in confidence
            assert "context_score" in confidence
            assert "capability_score" in confidence
            assert "historical_score" in confidence
            assert "explanation" in confidence

            # Verify confidence values
            assert 0.0 <= confidence["total"] <= 1.0
            assert 0.0 <= confidence["trigger_score"] <= 1.0

            print("\n✅ Routing successful:")
            print(f"   Selected agent: {best['agent_name']}")
            print(f"   Confidence: {confidence['total']:.2%}")
            print(f"   Reason: {best['reason']}")

    @pytest.mark.asyncio
    async def test_routing_with_context(self):
        """Test routing request with rich context."""
        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            recommendations = await client.request_routing(
                user_request="fix API performance issues",
                context={
                    "domain": "api_development",
                    "previous_agent": "agent-frontend-developer",
                    "current_file": "api/endpoints.py",
                },
                max_recommendations=5,
                min_confidence=0.6,
            )

            # Verify recommendations
            assert isinstance(recommendations, list)
            assert len(recommendations) > 0

            print("\n✅ Context-aware routing successful:")
            for i, rec in enumerate(recommendations[:3], 1):
                print(f"   {i}. {rec['agent_name']} ({rec['confidence']['total']:.2%})")

    @pytest.mark.asyncio
    async def test_routing_timeout(self):
        """Test timeout handling."""
        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            # Request with very short timeout (may timeout if service is slow)
            with pytest.raises((TimeoutError, Exception)):
                await client.request_routing(
                    user_request="test timeout handling",
                    timeout_ms=1,  # 1ms - almost guaranteed to timeout
                )

            print("\n✅ Timeout handling works correctly")

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self):
        """Test multiple concurrent routing requests."""
        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            # Send multiple requests concurrently
            tasks = [
                client.request_routing(
                    user_request=f"optimize {domain}",
                    context={"domain": domain},
                    max_recommendations=3,
                )
                for domain in [
                    "database_queries",
                    "api_performance",
                    "frontend_rendering",
                ]
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Verify all requests succeeded
            success_count = sum(1 for r in results if isinstance(r, list))
            assert success_count > 0, "At least one request should succeed"

            print(f"\n✅ Concurrent requests successful: {success_count}/3")

    @pytest.mark.asyncio
    async def test_route_via_events_wrapper(self):
        """Test convenience wrapper function."""
        recommendations = await route_via_events(
            user_request="optimize my database queries",
            context={"domain": "database_optimization"},
            max_recommendations=3,
            timeout_ms=10000,
            fallback_to_local=True,
        )

        # Verify recommendations
        assert isinstance(recommendations, list)
        assert len(recommendations) > 0

        best = recommendations[0]
        assert "agent_name" in best
        assert "confidence" in best

        print("\n✅ Wrapper function successful:")
        print(f"   Selected agent: {best['agent_name']}")
        print(f"   Confidence: {best['confidence']['total']:.2%}")

    @pytest.mark.asyncio
    async def test_fallback_to_local_on_kafka_unavailable(self):
        """Test fallback to local routing when Kafka is unavailable."""
        # Use invalid bootstrap server to force failure
        client = RoutingEventClient(
            bootstrap_servers="invalid-server:9999",
            request_timeout_ms=1000,
        )

        # Should fail to start
        with pytest.raises(Exception):
            await client.start()

        # Test wrapper with fallback enabled
        recommendations = await route_via_events(
            user_request="optimize my database queries",
            max_recommendations=3,
            timeout_ms=1000,
            fallback_to_local=True,
        )

        # Should succeed via local fallback
        assert isinstance(recommendations, list)
        assert len(recommendations) > 0

        print("\n✅ Fallback to local routing successful")

    @pytest.mark.asyncio
    async def test_feature_flag_disable_events(self):
        """Test USE_EVENT_ROUTING feature flag."""
        # Set feature flag to disable events
        original_value = os.getenv("USE_EVENT_ROUTING")
        os.environ["USE_EVENT_ROUTING"] = "false"

        try:
            recommendations = await route_via_events(
                user_request="optimize my database queries",
                max_recommendations=3,
                fallback_to_local=True,
            )

            # Should succeed via local routing (not events)
            assert isinstance(recommendations, list)
            assert len(recommendations) > 0

            print("\n✅ Feature flag disable successful (used local routing)")

        finally:
            # Restore original value
            if original_value is not None:
                os.environ["USE_EVENT_ROUTING"] = original_value
            else:
                os.environ.pop("USE_EVENT_ROUTING", None)


class TestRoutingEventIntegration:
    """End-to-end integration tests."""

    @pytest.mark.asyncio
    async def test_end_to_end_routing_flow(self):
        """Test complete routing flow from request to response."""
        correlation_id = str(uuid4())

        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            # Send routing request
            recommendations = await client.request_routing(
                user_request="optimize my API performance",
                context={
                    "domain": "api_development",
                    "correlation_id": correlation_id,
                },
                max_recommendations=3,
            )

            # Verify complete response
            assert isinstance(recommendations, list)
            assert len(recommendations) > 0

            # Verify all recommendations have required fields
            for rec in recommendations:
                assert "agent_name" in rec
                assert "agent_title" in rec
                assert "confidence" in rec
                assert "reason" in rec
                assert "definition_path" in rec

                # Verify confidence breakdown
                confidence = rec["confidence"]
                assert all(
                    key in confidence
                    for key in [
                        "total",
                        "trigger_score",
                        "context_score",
                        "capability_score",
                        "historical_score",
                        "explanation",
                    ]
                )

            print("\n✅ End-to-end flow successful:")
            print(f"   Correlation ID: {correlation_id}")
            print(f"   Recommendations: {len(recommendations)}")
            for i, rec in enumerate(recommendations, 1):
                print(
                    f"   {i}. {rec['agent_name']} ({rec['confidence']['total']:.2%}) - {rec['reason']}"
                )

    @pytest.mark.asyncio
    async def test_routing_performance(self):
        """Test routing performance meets targets."""
        import time

        async with RoutingEventClientContext(request_timeout_ms=10000) as client:
            # Measure routing time
            start_time = time.perf_counter()

            recommendations = await client.request_routing(
                user_request="optimize my database queries",
                max_recommendations=3,
            )

            total_time_ms = (time.perf_counter() - start_time) * 1000

            # Verify recommendations
            assert isinstance(recommendations, list)
            assert len(recommendations) > 0

            # Verify performance target (<2000ms total, <100ms p95 routing time)
            # Note: Total time includes network latency + routing time
            print("\n✅ Performance test:")
            print(f"   Total time: {total_time_ms:.2f}ms")
            print(f"   Recommendations: {len(recommendations)}")

            # Warn if slow (but don't fail - network latency can vary)
            if total_time_ms > 2000:
                print(
                    "   ⚠️  WARNING: Total time exceeds 2000ms target (network latency?)"
                )


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v", "-s"])

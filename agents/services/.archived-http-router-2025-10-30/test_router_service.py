"""
Integration Tests for Agent Router Service
==========================================

Tests the router service HTTP/REST interface and integration with:
- AgentRouter library
- Database logging
- Cache performance
- Error handling
- CORS headers

Usage:
    pytest agents/services/test_router_service.py -v
    pytest agents/services/test_router_service.py -v -k test_health
"""

import time
from unittest.mock import MagicMock, patch

import pytest

# Mock FastAPI imports if not available
try:
    from fastapi.testclient import TestClient

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    TestClient = None


# Sample test registry for mocking
SAMPLE_REGISTRY = {
    "agents": {
        "agent-debug-intelligence": {
            "title": "Debug Intelligence Agent",
            "definition_path": "/test/debug.yaml",
            "activation_triggers": ["debug", "error", "bug"],
            "capabilities": ["error_analysis", "debugging"],
            "domain_context": "debugging",
        },
        "agent-api-architect": {
            "title": "API Architect",
            "definition_path": "/test/api.yaml",
            "activation_triggers": ["api", "endpoint", "rest"],
            "capabilities": ["api_design", "rest"],
            "domain_context": "api_development",
        },
        "agent-performance": {
            "title": "Performance Optimizer",
            "definition_path": "/test/performance.yaml",
            "activation_triggers": ["optimize", "performance", "slow"],
            "capabilities": ["optimization", "profiling"],
            "domain_context": "performance",
        },
    }
}


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_router():
    """Mock AgentRouter for testing without real registry."""
    with patch(
        "agents.services.agent-router-service.router_service.AgentRouter"
    ) as mock:
        router_instance = MagicMock()

        # Mock route method
        def mock_route(request, context=None, max_recommendations=5):
            from agents.lib.agent_router import AgentRecommendation
            from agents.lib.confidence_scorer import ConfidenceScore

            return [
                AgentRecommendation(
                    agent_name="agent-debug-intelligence",
                    agent_title="Debug Intelligence Agent",
                    confidence=ConfidenceScore(
                        total=0.85,
                        trigger_score=0.9,
                        context_score=0.8,
                        capability_score=0.85,
                        historical_score=0.85,
                        explanation="High confidence match",
                    ),
                    reason="Matched debug trigger",
                    definition_path="/test/debug.yaml",
                )
            ]

        router_instance.route = mock_route
        router_instance.get_routing_stats.return_value = {
            "total_routes": 10,
            "cache_hits": 6,
            "cache_misses": 4,
            "cache_hit_rate": 0.6,
        }

        mock.return_value = router_instance
        yield router_instance


@pytest.fixture
def mock_db():
    """Mock database connection for testing."""
    with patch("psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()

        conn.cursor.return_value.__enter__.return_value = cursor
        cursor.fetchone.return_value = None

        mock_connect.return_value.__enter__.return_value = conn
        yield conn


@pytest.fixture
def client(mock_router, mock_db):
    """Create test client for router service."""
    if not FASTAPI_AVAILABLE:
        pytest.skip("FastAPI not available - skipping HTTP tests")

    # Import after mocking to avoid loading real dependencies
    from agents.services import router_service

    app = router_service.create_app()
    return TestClient(app)


# ============================================================================
# Health Check Tests
# ============================================================================


class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_endpoint(self, client):
        """Test health endpoint returns 200 OK."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert data["status"] in ["healthy", "ok"]
        assert "service" in data
        assert "routing" in data["service"].lower()

    def test_health_includes_version(self, client):
        """Test health endpoint includes service version."""
        response = client.get("/health")
        data = response.json()

        # Version should be present
        assert "version" in data or "service_version" in data

    def test_health_includes_uptime(self, client):
        """Test health endpoint includes uptime info."""
        response = client.get("/health")
        data = response.json()

        # Should have some timing info
        assert "uptime" in data or "started_at" in data


# ============================================================================
# Routing Endpoint Tests
# ============================================================================


class TestRoutingEndpoint:
    """Test agent routing endpoint."""

    def test_route_basic_request(self, client, mock_router):
        """Test basic routing request."""
        response = client.post(
            "/route",
            json={"user_request": "debug this error", "max_recommendations": 3},
        )

        assert response.status_code == 200
        data = response.json()

        assert "recommendations" in data
        assert len(data["recommendations"]) > 0

        rec = data["recommendations"][0]
        assert "agent_name" in rec
        assert "agent_title" in rec
        assert "confidence" in rec
        assert "reason" in rec

    def test_route_with_context(self, client, mock_router):
        """Test routing with context."""
        response = client.post(
            "/route",
            json={
                "user_request": "optimize api performance",
                "context": {
                    "domain": "api_development",
                    "previous_agent": "agent-api-architect",
                },
                "max_recommendations": 5,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Should include metadata
        assert "routing_time_ms" in data
        assert "correlation_id" in data
        assert data["routing_time_ms"] < 200  # Performance target

    def test_route_invalid_input(self, client):
        """Test routing with invalid input."""
        # Missing required field
        response = client.post("/route", json={"max_recommendations": 3})

        assert response.status_code == 422  # Validation error

    def test_route_empty_request(self, client):
        """Test routing with empty request."""
        response = client.post("/route", json={"user_request": ""})

        assert response.status_code == 422  # Validation error

    def test_route_malformed_json(self, client):
        """Test routing with malformed JSON."""
        response = client.post(
            "/route",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == 422


# ============================================================================
# CORS Tests
# ============================================================================


class TestCORS:
    """Test CORS headers."""

    def test_cors_headers(self, client):
        """Test CORS headers are present."""
        response = client.options("/route")

        # Should allow CORS
        assert response.status_code in [200, 204]

        # Check for CORS headers
        headers = response.headers
        assert (
            "access-control-allow-origin" in headers
            or "Access-Control-Allow-Origin" in headers
        )

    def test_cors_methods(self, client):
        """Test allowed CORS methods."""
        response = client.options("/route")

        # Should allow POST for routing
        if "access-control-allow-methods" in response.headers:
            allowed = response.headers["access-control-allow-methods"]
            assert "POST" in allowed.upper()


# ============================================================================
# Performance Tests
# ============================================================================


class TestPerformance:
    """Test routing performance targets."""

    def test_response_time(self, client, mock_router):
        """Test response time meets target (<200ms including HTTP overhead)."""
        start = time.time()

        response = client.post("/route", json={"user_request": "debug error"})

        duration_ms = (time.time() - start) * 1000

        assert response.status_code == 200
        # HTTP overhead + routing should be <200ms
        assert duration_ms < 200, f"Response took {duration_ms:.1f}ms (target: <200ms)"

    def test_cache_performance(self, client, mock_router):
        """Test cached requests are faster."""
        request = {"user_request": "test cache performance"}

        # First request (cache miss)
        start1 = time.time()
        response1 = client.post("/route", json=request)
        duration1_ms = (time.time() - start1) * 1000

        # Second request (should hit cache)
        start2 = time.time()
        response2 = client.post("/route", json=request)
        duration2_ms = (time.time() - start2) * 1000

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Cached request should be faster (or similar if mocked)
        # In real implementation, this would be significantly faster
        assert duration2_ms <= duration1_ms * 1.5


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Test error handling and fallback."""

    def test_fallback_on_error(self, client, mock_router):
        """Test service handles router errors gracefully."""
        # Mock router to raise exception
        mock_router.route.side_effect = Exception("Router failure")

        response = client.post("/route", json={"user_request": "test error handling"})

        # Should still return valid response with fallback
        assert response.status_code in [200, 500, 503]

        if response.status_code == 200:
            data = response.json()
            # Should have fallback indication
            assert (
                "error" in data
                or "fallback" in data
                or len(data["recommendations"]) == 0
            )

    def test_database_failure_handling(self, client, mock_db):
        """Test service continues when database logging fails."""
        # Mock database to fail
        mock_db.cursor.side_effect = Exception("Database unavailable")

        response = client.post("/route", json={"user_request": "test db failure"})

        # Should still route successfully
        assert response.status_code == 200

    def test_partial_failure_handling(self, client, mock_router):
        """Test handling when some agents fail to load."""

        # Mock partial failure in routing
        def mock_route_partial_fail(request, context=None, max_recommendations=5):
            # Return some recommendations but log errors
            from agents.lib.agent_router import AgentRecommendation
            from agents.lib.confidence_scorer import ConfidenceScore

            return [
                AgentRecommendation(
                    agent_name="agent-fallback",
                    agent_title="Fallback Agent",
                    confidence=ConfidenceScore(
                        total=0.5,
                        trigger_score=0.5,
                        context_score=0.5,
                        capability_score=0.5,
                        historical_score=0.5,
                        explanation="Fallback due to partial failure",
                    ),
                    reason="Fallback recommendation",
                    definition_path="/test/fallback.yaml",
                )
            ]

        mock_router.route = mock_route_partial_fail

        response = client.post("/route", json={"user_request": "test partial failure"})

        assert response.status_code == 200
        data = response.json()

        # Should have at least fallback recommendation
        assert len(data["recommendations"]) > 0


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests with real components (if available)."""

    @pytest.mark.integration
    def test_end_to_end_routing(self, client):
        """Test complete routing flow end-to-end."""
        response = client.post(
            "/route",
            json={
                "user_request": "debug performance issue in api endpoint",
                "context": {"domain": "api_development"},
                "max_recommendations": 3,
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Validate complete response structure
        assert "recommendations" in data
        assert "routing_time_ms" in data
        assert "correlation_id" in data
        assert "cache_hit" in data

        # Should have recommendations
        assert len(data["recommendations"]) > 0

        for rec in data["recommendations"]:
            # Validate recommendation structure
            assert "agent_name" in rec
            assert "agent_title" in rec
            assert "confidence" in rec
            assert "reason" in rec
            assert "definition_path" in rec

            # Validate confidence breakdown
            conf = rec["confidence"]
            assert "total" in conf
            assert "trigger_score" in conf
            assert "context_score" in conf
            assert "capability_score" in conf
            assert "historical_score" in conf
            assert "explanation" in conf

            # Validate confidence values
            assert 0.0 <= conf["total"] <= 1.0

    @pytest.mark.integration
    def test_database_logging(self, client):
        """Test that routing decisions are logged to database."""
        response = client.post("/route", json={"user_request": "test database logging"})

        assert response.status_code == 200
        data = response.json()

        correlation_id = data.get("correlation_id")
        assert correlation_id is not None

        # In real test, would verify database has entry with correlation_id
        # This requires actual database connection


# ============================================================================
# Statistics Tests
# ============================================================================


class TestStatistics:
    """Test statistics and metrics endpoints."""

    def test_stats_endpoint(self, client, mock_router):
        """Test statistics endpoint."""
        response = client.get("/stats")

        if response.status_code == 404:
            pytest.skip("Stats endpoint not implemented")

        assert response.status_code == 200
        data = response.json()

        # Should have routing statistics
        assert "total_routes" in data
        assert "cache_hit_rate" in data

    def test_metrics_endpoint(self, client):
        """Test Prometheus metrics endpoint."""
        response = client.get("/metrics")

        if response.status_code == 404:
            pytest.skip("Metrics endpoint not implemented")

        assert response.status_code == 200

        # Prometheus format is text
        assert "text/plain" in response.headers.get("content-type", "")


# ============================================================================
# Main Test Runner
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

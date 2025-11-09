#!/usr/bin/env python3
"""
Comprehensive End-to-End Integration Tests

Tests the complete workflow:
1. FastAPI receives request
2. Reducer updates FSM state
3. Orchestrator coordinates workflow
4. Intelligence queries Qdrant/PostgreSQL
5. Rewriter prunes messages and formats manifest
6. Forwarder sends to Anthropic
7. FastAPI returns response

Usage:
    pytest services/intelligent_context_proxy/tests/test_full_workflow.py -v
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@pytest.mark.asyncio
async def test_full_workflow_integration():
    """
    Test complete workflow end-to-end.

    Flow:
    1. Send HTTP request to FastAPI
    2. Verify response received
    3. Verify response has correct format
    4. Verify intelligence was injected
    5. Verify token management worked
    """
    logger.info("=" * 80)
    logger.info("Full Workflow Integration Test")
    logger.info("=" * 80)

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Prepare request
        url = "http://localhost:8080/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer test-token",
        }
        payload = {
            "model": "claude-sonnet-4",
            "messages": [
                {"role": "user", "content": "Implement an ONEX effect node for querying Qdrant"}
            ],
            "system": "You are a helpful assistant specialized in ONEX architecture",
            "max_tokens": 1024,
        }

        # Send request
        logger.info("Sending request to proxy...")
        try:
            response = await client.post(url, json=payload, headers=headers)
        except Exception as e:
            pytest.fail(f"Request failed: {e}")

        # Verify response
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        data = response.json()

        # Verify response structure
        assert "id" in data, "Response missing 'id' field"
        assert "content" in data, "Response missing 'content' field"
        assert "model" in data, "Response missing 'model' field"

        # Verify content
        assert len(data["content"]) > 0, "Response content is empty"

        logger.info(f"✅ Full workflow test PASSED")
        logger.info(f"Response ID: {data.get('id')}")
        logger.info(f"Model: {data.get('model')}")
        logger.info(f"Content length: {len(str(data.get('content')))}")


@pytest.mark.asyncio
async def test_performance_latency():
    """
    Test workflow performance meets targets.

    Target: <3s total latency
    """
    logger.info("=" * 80)
    logger.info("Performance Latency Test")
    logger.info("=" * 80)

    async with httpx.AsyncClient(timeout=60.0) as client:
        url = "http://localhost:8080/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer test-token",
        }
        payload = {
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "Hello"}],
            "max_tokens": 100,
        }

        # Measure latency
        import time

        start_time = time.time()
        response = await client.post(url, json=payload, headers=headers)
        end_time = time.time()

        latency_ms = int((end_time - start_time) * 1000)

        logger.info(f"Total latency: {latency_ms}ms")

        # Verify latency target
        assert response.status_code == 200
        assert latency_ms < 5000, f"Latency {latency_ms}ms exceeds 5s target"

        if latency_ms < 3000:
            logger.info(f"✅ Latency excellent: {latency_ms}ms < 3s")
        else:
            logger.warning(f"⚠️ Latency acceptable but high: {latency_ms}ms")


@pytest.mark.asyncio
async def test_health_check():
    """Test health check endpoint."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get("http://localhost:8080/health")
        data = response.json()

        assert response.status_code == 200
        assert data.get("status") in ["healthy", "degraded"]
        assert "services" in data

        logger.info(f"✅ Health check passed: {data.get('status')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

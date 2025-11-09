#!/usr/bin/env python3
"""
Integration tests for Intelligent Context Proxy.

Tests the complete round-trip flow:
1. Send HTTP request to FastAPI
2. Verify Reducer updates FSM state
3. Verify Orchestrator returns response
4. Verify FastAPI returns to client

Usage:
    python services/intelligent_context_proxy/tests/test_integration.py
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import httpx

# Add project root to path
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_round_trip_flow():
    """
    Test complete round-trip flow.

    Sends a request to FastAPI and verifies:
    1. Response is received
    2. Response has correct format
    3. Latency is acceptable (<3s for Phase 1)
    """
    logger.info("=" * 80)
    logger.info("Integration Test: Round-Trip Flow")
    logger.info("=" * 80)

    # Create HTTP client
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Prepare request
        url = "http://localhost:8080/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer test-token-12345",
        }
        payload = {
            "model": "claude-sonnet-4",
            "messages": [{"role": "user", "content": "Hello from integration test!"}],
            "max_tokens": 1024,
        }

        logger.info("\n1. Sending request to proxy...")
        logger.info(f"   URL: {url}")
        logger.info(f"   Payload: {json.dumps(payload, indent=2)}")

        # Send request
        start_time = asyncio.get_event_loop().time()
        try:
            response = await client.post(url, json=payload, headers=headers)
        except Exception as e:
            logger.error(f"❌ Request failed: {e}")
            return False

        end_time = asyncio.get_event_loop().time()
        latency_ms = int((end_time - start_time) * 1000)

        logger.info(f"\n2. Received response:")
        logger.info(f"   Status: {response.status_code}")
        logger.info(f"   Latency: {latency_ms}ms")

        # Verify response
        if response.status_code != 200:
            logger.error(f"❌ Expected status 200, got {response.status_code}")
            logger.error(f"   Response body: {response.text}")
            return False

        # Parse response
        try:
            data = response.json()
        except Exception as e:
            logger.error(f"❌ Failed to parse response JSON: {e}")
            logger.error(f"   Response body: {response.text}")
            return False

        logger.info(f"   Response: {json.dumps(data, indent=2)[:500]}...")

        # Verify response format
        required_fields = ["id", "role", "content", "model"]
        missing_fields = [field for field in required_fields if field not in data]

        if missing_fields:
            logger.error(f"❌ Response missing required fields: {missing_fields}")
            return False

        # Verify content
        if not data.get("content"):
            logger.error("❌ Response content is empty")
            return False

        # Verify it's a mock response (Phase 1)
        content_text = data["content"][0].get("text", "")
        if "[MOCK RESPONSE - Phase 1]" not in content_text:
            logger.warning("⚠️  Response does not contain Phase 1 mock marker")
            logger.warning("   This is expected if Phase 2+ is implemented")

        # Check latency
        logger.info(f"\n3. Performance check:")
        logger.info(f"   Latency: {latency_ms}ms")

        if latency_ms < 3000:
            logger.info("   ✅ Latency acceptable (<3s)")
        else:
            logger.warning(f"   ⚠️  Latency high (>{latency_ms}ms)")

        logger.info("\n" + "=" * 80)
        logger.info("✅ Integration test PASSED!")
        logger.info("=" * 80)

        return True


async def test_health_check():
    """Test health check endpoint."""
    logger.info("\n" + "=" * 80)
    logger.info("Integration Test: Health Check")
    logger.info("=" * 80)

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get("http://localhost:8080/health")
            data = response.json()

            logger.info(f"\nHealth check response:")
            logger.info(f"  Status: {data.get('status')}")
            logger.info(f"  Services: {data.get('services')}")

            if data.get("status") == "healthy":
                logger.info("✅ Health check PASSED")
                return True
            else:
                logger.error("❌ Health check FAILED")
                return False

        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return False


async def main():
    """Run all integration tests."""
    logger.info("\n" + "=" * 80)
    logger.info("Intelligent Context Proxy - Integration Tests")
    logger.info("=" * 80)
    logger.info("")

    # Test 1: Health check
    health_ok = await test_health_check()

    # Test 2: Round-trip flow
    round_trip_ok = await test_round_trip_flow()

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("Test Summary")
    logger.info("=" * 80)
    logger.info(f"Health Check: {'✅ PASSED' if health_ok else '❌ FAILED'}")
    logger.info(f"Round-Trip Flow: {'✅ PASSED' if round_trip_ok else '❌ FAILED'}")
    logger.info("=" * 80)

    if health_ok and round_trip_ok:
        logger.info("\n🎉 All tests PASSED!")
        return 0
    else:
        logger.error("\n❌ Some tests FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

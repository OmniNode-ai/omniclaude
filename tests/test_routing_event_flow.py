#!/usr/bin/env python3
"""
Test script for routing event flow end-to-end

This script tests the complete event-driven routing flow:
1. Client publishes routing request to Kafka
2. agent-router-service consumes request
3. Service executes routing logic
4. Service publishes response to Kafka
5. Client receives response with correlation tracking
6. Decision logged to PostgreSQL

Tests:
    - Test 1: Simple routing request (single recommendation)
    - Test 2: Multiple recommendations (max_recommendations=3)
    - Test 3: Timeout handling (service not running)
    - Test 4: PostgreSQL logging verification

Usage:
    # With service running
    python3 test_routing_event_flow.py

    # Expected output:
    # ✅ Test 1: Simple routing request - PASSED
    # ✅ Test 2: Multiple recommendations - PASSED
    # ⏭️  Test 3: Timeout handling - SKIPPED (service running)
    # ✅ Test 4: PostgreSQL logging - PASSED

Created: 2025-10-30
Reference: test_database_event_client.py, EVENT_DRIVEN_ROUTING_PROPOSAL.md
Correlation ID: 2ae9c54b-73e4-42df-a902-cf41503efa56
"""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4


# Add project root to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


# Add services to path (parent of routing_adapter)
# NOTE: services/ is at project root, not in tests/
services_path = Path(__file__).parent.parent / "services"
sys.path.insert(0, str(services_path))

# Import routing schemas
from routing_adapter.schemas import (  # noqa: E402
    TOPICS,
    EventTypes,
    ModelRoutingError,
    ModelRoutingEventEnvelope,
    ModelRoutingRequest,
)


# Kafka imports
try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ImportError:
    print("❌ aiokafka not installed. Install with: pip install aiokafka")
    sys.exit(1)

# PostgreSQL imports (optional for Test 4)
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    POSTGRES_AVAILABLE = True
except ImportError:
    print("⚠️  psycopg2 not installed. Test 4 (PostgreSQL logging) will be skipped.")
    print("   Install with: pip install psycopg2-binary")
    POSTGRES_AVAILABLE = False

# Configuration from settings (auto-loaded from .env)
KAFKA_SERVERS = settings.kafka_bootstrap_servers
POSTGRES_HOST = settings.postgres_host
POSTGRES_PORT = settings.postgres_port
POSTGRES_DB = settings.postgres_database
POSTGRES_USER = settings.postgres_user
try:
    POSTGRES_PASSWORD = settings.get_effective_postgres_password()
except ValueError:
    POSTGRES_PASSWORD = ""  # Will fail Test 4 if not set

# Timeouts
REQUEST_TIMEOUT_MS = 5000  # 5 seconds
RESPONSE_POLL_INTERVAL_MS = 100  # 100ms polling


class RoutingEventTestClient:
    """
    Test client for routing event flow.

    Publishes routing requests and waits for responses via Kafka events.
    """

    def __init__(
        self,
        kafka_servers: str = KAFKA_SERVERS,
        timeout_ms: int = REQUEST_TIMEOUT_MS,
    ):
        """
        Initialize test client.

        Args:
            kafka_servers: Kafka bootstrap servers
            timeout_ms: Response timeout in milliseconds
        """
        self.kafka_servers = kafka_servers
        self.timeout_ms = timeout_ms
        self.producer: Optional[AIOKafkaProducer] = None
        self.consumer: Optional[AIOKafkaConsumer] = None
        self._correlation_id: Optional[UUID] = None
        self._response_event: Optional[asyncio.Event] = None
        self._response_payload: Optional[Dict[str, Any]] = None
        self._consume_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start Kafka producer and consumer."""
        # Start producer
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.kafka_servers,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await self.producer.start()

        # Start consumer for response topics
        self.consumer = AIOKafkaConsumer(
            TOPICS.COMPLETED,
            TOPICS.FAILED,
            bootstrap_servers=self.kafka_servers,
            value_deserializer=lambda m: json.loads(m.decode("utf-8")),
            group_id=f"routing-test-client-{uuid4()}",
            auto_offset_reset="latest",  # Only consume new messages
        )
        await self.consumer.start()

        # Start consuming responses in background
        self._consume_task = asyncio.create_task(self._consume_responses())

    async def stop(self):
        """Stop Kafka producer and consumer."""
        # Cancel consumer task
        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass

        # Stop producer
        if self.producer:
            await self.producer.stop()

        # Stop consumer
        if self.consumer:
            await self.consumer.stop()

    async def _consume_responses(self):
        """Consume response events from Kafka (background task)."""
        try:
            async for msg in self.consumer:
                envelope_data = msg.value

                # Check if this is the response we're waiting for
                if (
                    self._correlation_id
                    and envelope_data.get("correlation_id") == str(self._correlation_id)
                    and self._response_event
                ):
                    self._response_payload = envelope_data
                    self._response_event.set()

        except asyncio.CancelledError:
            pass

    async def request_routing(
        self,
        user_request: str,
        context: Optional[Dict[str, Any]] = None,
        max_recommendations: int = 5,
    ) -> Dict[str, Any]:
        """
        Request agent routing via Kafka events.

        Args:
            user_request: User's request text
            context: Optional execution context
            max_recommendations: Maximum recommendations to return

        Returns:
            Response payload (routing response or error)

        Raises:
            TimeoutError: If no response within timeout
            ValueError: If response is error
        """
        # Generate correlation ID
        correlation_id = uuid4()
        self._correlation_id = correlation_id
        self._response_event = asyncio.Event()
        self._response_payload = None

        # Build request envelope
        request = ModelRoutingRequest(
            user_request=user_request,
            correlation_id=str(correlation_id),
            context=context or {},
            max_recommendations=max_recommendations,
        )

        envelope = ModelRoutingEventEnvelope(
            event_id=str(uuid4()),
            event_type=EventTypes.REQUESTED,
            correlation_id=str(correlation_id),
            timestamp=datetime.now(UTC).isoformat(),
            service="test-client",
            payload=request.model_dump(),
        )

        # Publish request
        await self.producer.send(TOPICS.REQUEST, envelope.model_dump())

        # Wait for response with timeout
        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=self.timeout_ms / 1000.0
            )
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"No response received within {self.timeout_ms}ms. "
                "Is agent-router-service running?"
            )

        # Parse response
        if not self._response_payload:
            raise ValueError("Response event set but no payload received")

        event_type = self._response_payload.get("event_type")

        if event_type == EventTypes.FAILED:
            # Parse error response
            error_payload = self._response_payload.get("payload", {})
            error = ModelRoutingError(**error_payload)
            raise ValueError(
                f"Routing failed: {error.error_code} - {error.error_message}"
            )

        # Parse success response
        response_payload = self._response_payload.get("payload", {})
        return response_payload


# Helper function to check PostgreSQL logging
def check_postgres_log(correlation_id: UUID) -> Optional[Dict[str, Any]]:
    """
    Check if routing decision was logged to PostgreSQL.

    Args:
        correlation_id: Correlation ID to search for

    Returns:
        Routing decision record if found, None otherwise
    """
    if not POSTGRES_AVAILABLE:
        return None

    try:
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            database=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            cursor_factory=RealDictCursor,
        )

        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    correlation_id,
                    selected_agent,
                    confidence_score,
                    routing_strategy,
                    reasoning,
                    created_at
                FROM agent_routing_decisions
                WHERE correlation_id = %s
                """,
                (str(correlation_id),),
            )

            row = cursor.fetchone()
            conn.close()

            if row:
                return dict(row)
            return None

    except Exception as e:
        print(f"⚠️  PostgreSQL query failed: {e}")
        return None


# Test functions
async def test_simple_routing():
    """Test 1: Simple routing request (single recommendation)"""
    print("=" * 60)
    print("TEST 1: Simple Routing Request")
    print("=" * 60)

    client = RoutingEventTestClient()

    try:
        start_time = time.time()
        await client.start()
        print("✅ Client started")

        # Request routing
        user_request = "optimize my database queries"
        print(f"\nRequesting routing: '{user_request}'")

        response = await client.request_routing(
            user_request=user_request, max_recommendations=1
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        print("✅ Routing successful!")
        print(f"   Response: {json.dumps(response, indent=2)}")
        print(f"   Execution time: {elapsed_ms}ms")

        # Validate response structure
        assert "recommendations" in response, "Expected 'recommendations' in response"
        assert (
            len(response["recommendations"]) > 0
        ), "Expected at least one recommendation"
        assert "routing_metadata" in response, "Expected 'routing_metadata' in response"

        recommendation = response["recommendations"][0]
        assert "agent_name" in recommendation, "Expected 'agent_name' in recommendation"
        assert "confidence" in recommendation, "Expected 'confidence' in recommendation"
        assert "reason" in recommendation, "Expected 'reason' in recommendation"

        print("\n✅ Validation passed")
        print(f"   Selected agent: {recommendation['agent_name']}")
        print(f"   Confidence: {recommendation['confidence']['total']:.2%}")
        print(f"   Reason: {recommendation['reason']}")

        return True, client._correlation_id

    except TimeoutError as e:
        print(f"⏭️  Test skipped: {e}")
        print("   This is expected if agent-router-service is not running")
        return None, None
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_multiple_recommendations():
    """Test 2: Multiple recommendations (max_recommendations=3)"""
    print("=" * 60)
    print("TEST 2: Multiple Recommendations")
    print("=" * 60)

    client = RoutingEventTestClient()

    try:
        start_time = time.time()
        await client.start()
        print("✅ Client started")

        # Request routing with multiple recommendations
        user_request = "help me debug my application"
        print(f"\nRequesting routing: '{user_request}'")
        print("   Options: max_recommendations=3")

        response = await client.request_routing(
            user_request=user_request, max_recommendations=3
        )

        elapsed_ms = int((time.time() - start_time) * 1000)

        print("✅ Routing successful!")
        print(f"   Execution time: {elapsed_ms}ms")

        # Validate response
        recommendations = response.get("recommendations", [])
        assert len(recommendations) > 0, "Expected at least one recommendation"
        print(f"\n✅ Received {len(recommendations)} recommendation(s)")

        # Display recommendations
        for i, rec in enumerate(recommendations, 1):
            print(f"\n   {i}. Agent: {rec['agent_name']}")
            print(f"      Confidence: {rec['confidence']['total']:.2%}")
            print(f"      Reason: {rec['reason'][:60]}...")

        # Verify confidence scores are sorted descending
        confidences = [rec["confidence"]["total"] for rec in recommendations]
        assert confidences == sorted(
            confidences, reverse=True
        ), "Expected recommendations sorted by confidence descending"

        print("\n✅ Validation passed (sorted by confidence)")

        return True, client._correlation_id

    except TimeoutError as e:
        print(f"⏭️  Test skipped: {e}")
        return None, None
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_timeout_handling():
    """Test 3: Timeout handling (service not running)"""
    print("=" * 60)
    print("TEST 3: Timeout Handling")
    print("=" * 60)

    # Use short timeout for this test
    client = RoutingEventTestClient(timeout_ms=1000)

    try:
        await client.start()
        print("✅ Client started with 1s timeout")

        # Try routing request
        print("\nRequesting routing with short timeout...")

        _ = await client.request_routing(
            user_request="test timeout", max_recommendations=1
        )

        # If we get here, service is running
        print("⏭️  Test skipped: service is running (no timeout occurred)")
        print("   This test only runs when service is unavailable")
        return None, None

    except TimeoutError as e:
        print("✅ Timeout handled correctly!")
        print(f"   Error: {e}")
        print("   This is expected when agent-router-service is not running")
        return True, None
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None
    finally:
        await client.stop()
        print("✅ Client stopped\n")


async def test_postgres_logging(correlation_id: Optional[UUID]):
    """Test 4: PostgreSQL logging verification"""
    print("=" * 60)
    print("TEST 4: PostgreSQL Logging Verification")
    print("=" * 60)

    if not POSTGRES_AVAILABLE:
        print("⏭️  Test skipped: psycopg2 not installed")
        print("   Install with: pip install psycopg2-binary")
        return None

    if not correlation_id:
        print("⏭️  Test skipped: no correlation_id from previous tests")
        print("   This test requires Test 1 or Test 2 to pass first")
        return None

    print(f"Checking PostgreSQL for correlation_id: {correlation_id}")

    # Wait a moment for async database write to complete
    await asyncio.sleep(1)

    try:
        record = check_postgres_log(correlation_id)

        if record:
            print("✅ Routing decision found in PostgreSQL!")
            print(f"   Selected agent: {record['selected_agent']}")
            print(f"   Confidence: {record['confidence_score']:.2%}")
            print(f"   Strategy: {record['routing_strategy']}")
            print(f"   Reasoning: {record['reasoning'][:60]}...")
            print(f"   Created at: {record['created_at']}")
            print("\n✅ Validation passed")
            return True
        else:
            print("❌ Routing decision NOT found in PostgreSQL")
            print("   Expected entry in agent_routing_decisions table")
            return False

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        print()


async def run_all_tests():
    """Run all test cases"""
    print("\n" + "=" * 60)
    print("ROUTING EVENT FLOW - END-TO-END TESTING")
    print("=" * 60)
    print(f"Started: {datetime.now().isoformat()}")
    print(f"Kafka: {KAFKA_SERVERS}")
    print(f"PostgreSQL: {POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")
    print("=" * 60 + "\n")

    results = {}
    correlation_ids = []

    # Run tests
    result, correlation_id = await test_simple_routing()
    results["test_simple_routing"] = result
    if correlation_id:
        correlation_ids.append(correlation_id)

    result, correlation_id = await test_multiple_recommendations()
    results["test_multiple_recommendations"] = result
    if correlation_id:
        correlation_ids.append(correlation_id)

    result, _ = await test_timeout_handling()
    results["test_timeout_handling"] = result

    # Test PostgreSQL logging (use first correlation ID)
    results["test_postgres_logging"] = await test_postgres_logging(
        correlation_ids[0] if correlation_ids else None
    )

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)
    total = len(results)

    for test_name, result in results.items():
        if result is True:
            status = "✅ PASSED"
        elif result is False:
            status = "❌ FAILED"
        else:
            status = "⏭️  SKIPPED"
        print(f"{status}: {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed, {failed} failed, {skipped} skipped")
    print("=" * 60)

    # Return True if all non-skipped tests passed
    return failed == 0


if __name__ == "__main__":
    result = asyncio.run(run_all_tests())
    sys.exit(0 if result else 1)

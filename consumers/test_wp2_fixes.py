#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Test script for WP2 fixes: Kafka retry logic and health check thread safety

Tests:
1. C2: Kafka infinite retry loop prevention
2. M6: Health check race condition prevention
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from kafka import KafkaProducer

# Add src to path for omniclaude.hooks.topics
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from omniclaude.hooks.topics import TopicBase

# Add consumers to path
sys.path.insert(0, str(Path(__file__).parent))


def test_poison_message_handling():
    """Test C2: Verify consumer handles poison messages with retry limits."""
    print("\n" + "=" * 70)
    print("TEST C2: Poison Message Handling with Retry Limits")
    print("=" * 70)

    # Initialize Kafka producer
    producer = KafkaProducer(
        bootstrap_servers=["localhost:9092"],
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    print("\n1. Sending valid message to establish baseline...")
    valid_message = {
        "correlation_id": "test-valid-001",
        "agent_name": "test-agent",
        "action_type": "test",
        "action_name": "baseline_test",
        "action_details": {"test": "valid"},
        "debug_mode": True,
        "duration_ms": 100,
        "timestamp": "2025-01-01T00:00:00Z",
    }
    producer.send(TopicBase.AGENT_ACTIONS, value=valid_message)
    producer.flush()
    print("✅ Valid message sent")

    print("\n2. Sending poison message (malformed JSON structure)...")
    # Send message that will fail database insertion
    poison_message = {
        "correlation_id": "test-poison-001",
        "agent_name": "test-agent",
        "action_type": None,  # This will cause insertion failure
        "action_name": {"invalid": "structure"},  # Wrong type
        "action_details": "not_a_dict",  # Wrong type
        "duration_ms": "not_an_int",  # Wrong type
    }
    producer.send(TopicBase.AGENT_ACTIONS, value=poison_message)
    producer.flush()
    print("✅ Poison message sent")

    print("\n3. Monitoring consumer behavior for 30 seconds...")
    print("Expected behavior:")
    print("  - Retry 1/3 with 100ms backoff")
    print("  - Retry 2/3 with 200ms backoff")
    print("  - Retry 3/3 with 400ms backoff")
    print("  - Send to DLQ after 3rd retry")
    print("  - Commit offset to move past poison message")
    print("  - Continue processing (no infinite loop)")

    time.sleep(30)

    print("\n4. Checking consumer health after poison message...")
    try:
        response = requests.get("http://localhost:8080/health", timeout=5)
        if response.status_code == 200:
            print("✅ Consumer still healthy after poison message")
            print(f"   Response: {response.json()}")
        else:
            print(f"❌ Consumer unhealthy: {response.status_code}")
            print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"❌ Health check failed: {e}")

    print("\n5. Checking consumer metrics...")
    try:
        response = requests.get("http://localhost:8080/metrics", timeout=5)
        if response.status_code == 200:
            metrics = response.json()
            print("✅ Metrics retrieved:")
            print(f"   Messages consumed: {metrics['messages_consumed']}")
            print(f"   Messages inserted: {metrics['messages_inserted']}")
            print(f"   Messages failed: {metrics['messages_failed']}")
            print(f"   Batches processed: {metrics['batches_processed']}")
        else:
            print(f"❌ Metrics retrieval failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Metrics request failed: {e}")

    producer.close()

    print("\n✅ C2 TEST COMPLETE")
    print("Manual verification required:")
    print("  1. Check consumer logs for retry messages (100ms, 200ms, 400ms backoffs)")
    print("  2. Verify DLQ topic 'agent-observability-dlq' received poison message")
    print("  3. Verify consumer moved past poison message (processed next message)")
    print("  4. Verify consumer didn't enter infinite loop")


def test_concurrent_health_checks():
    """Test M6: Verify health check thread safety under concurrent load."""
    print("\n" + "=" * 70)
    print("TEST M6: Concurrent Health Check Thread Safety")
    print("=" * 70)

    num_concurrent_requests = 100
    health_url = "http://localhost:8080/health"

    print(f"\n1. Launching {num_concurrent_requests} concurrent health checks...")

    results = {"success": 0, "failed": 0, "errors": []}

    with ThreadPoolExecutor(max_workers=50) as executor:
        futures = [
            executor.submit(requests.get, health_url, timeout=5)
            for _ in range(num_concurrent_requests)
        ]

        for future in as_completed(futures):
            try:
                response = future.result()
                if response.status_code in (200, 503):
                    results["success"] += 1
                else:
                    results["failed"] += 1
                    results["errors"].append(
                        f"Unexpected status: {response.status_code}"
                    )
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(str(e))

    print("\n2. Results:")
    print(f"   Successful responses: {results['success']}/{num_concurrent_requests}")
    print(f"   Failed requests: {results['failed']}/{num_concurrent_requests}")

    if results["errors"]:
        print("\n   Errors encountered:")
        for error in set(results["errors"][:10]):  # Show unique errors, max 10
            print(f"     - {error}")

    if results["success"] == num_concurrent_requests:
        print("\n✅ M6 TEST PASSED: All concurrent health checks succeeded")
    else:
        print(
            f"\n❌ M6 TEST FAILED: {results['failed']} requests failed (see errors above)"
        )

    print("\n3. Testing health check during shutdown simulation...")
    print("   (Manual test: Send SIGTERM to consumer during health checks)")
    print("   Expected: Consistent 503 responses after shutdown initiated")

    print("\n✅ M6 TEST COMPLETE")
    print("Manual verification required:")
    print("  1. No AttributeError in consumer logs")
    print("  2. No race condition errors in consumer logs")
    print("  3. All responses either 200 (healthy) or 503 (unhealthy), no crashes")


def main():
    """Run all WP2 tests."""
    print("\n" + "=" * 70)
    print("WORK PACKAGE 2: Kafka Consumer Reliability & Health Check Safety")
    print("=" * 70)
    print("\nPrerequisites:")
    print("  1. Kafka broker running on localhost:9092")
    print("  2. PostgreSQL running on localhost:5436")
    print("  3. agent_actions_consumer.py running with WP2 fixes")
    print("  4. Consumer health check on http://localhost:8080/health")

    input("\nPress Enter to start tests or Ctrl+C to cancel...")

    try:
        # Test C2: Poison message handling
        test_poison_message_handling()

        print("\n" + "=" * 70)
        input("\nPress Enter to continue to M6 health check tests...")

        # Test M6: Concurrent health checks
        test_concurrent_health_checks()

        print("\n" + "=" * 70)
        print("ALL WP2 TESTS COMPLETE")
        print("=" * 70)
        print("\nSummary:")
        print("  ✅ C2: Poison message retry logic tested")
        print("  ✅ M6: Concurrent health check safety tested")
        print("\nReview consumer logs for detailed retry behavior and confirm:")
        print("  1. Exponential backoff applied (100ms, 200ms, 400ms)")
        print("  2. Offset committed after max retries")
        print("  3. No infinite loops on poison messages")
        print("  4. No race conditions in health checks")

    except KeyboardInterrupt:
        print("\n\nTests cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Test suite failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

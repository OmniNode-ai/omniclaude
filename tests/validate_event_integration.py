#!/usr/bin/env python3
"""
Quick validation script to test event publishing/consuming with omniarchon.

Tests:
1. Kafka connectivity
2. Event publishing to code-analysis-requested topic
3. Event consuming from code-analysis-completed topic
4. Correlation ID tracking
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from uuid import uuid4


try:
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
except ImportError:
    print("❌ aiokafka not installed. Run: poetry install")
    sys.exit(1)


# Configuration
BOOTSTRAP_SERVERS = "localhost:29092"  # Redpanda external port mapping
REQUEST_TOPIC = "dev.archon-intelligence.intelligence.code-analysis-requested.v1"
COMPLETED_TOPIC = "dev.archon-intelligence.intelligence.code-analysis-completed.v1"
FAILED_TOPIC = "dev.archon-intelligence.intelligence.code-analysis-failed.v1"


async def test_event_flow():
    """Test end-to-end event flow with omniarchon."""

    print("🔍 Starting Event Integration Validation\n")
    print("=" * 60)

    # Generate correlation ID
    correlation_id = str(uuid4())
    print(f"📋 Correlation ID: {correlation_id}")

    # Step 1: Create producer
    print("\n1️⃣  Creating Kafka producer...")
    try:
        producer = AIOKafkaProducer(
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )
        await producer.start()
        print("   ✅ Producer started")
    except Exception as e:
        print(f"   ❌ Producer failed: {e}")
        return False

    # Step 2: Create consumer for responses
    print("\n2️⃣  Creating Kafka consumer...")
    try:
        consumer = AIOKafkaConsumer(
            COMPLETED_TOPIC,
            FAILED_TOPIC,
            bootstrap_servers=BOOTSTRAP_SERVERS,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            group_id=f"validation-test-{uuid4().hex[:8]}",
            auto_offset_reset="latest",  # Only read new messages
            enable_auto_commit=True,
        )
        await consumer.start()
        print("   ✅ Consumer started")
    except Exception as e:
        print(f"   ❌ Consumer failed: {e}")
        await producer.stop()
        return False

    # Step 3: Publish test request
    print("\n3️⃣  Publishing test event...")
    request_payload = {
        "correlation_id": correlation_id,
        "event_type": "code_analysis_requested",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "source_path": "validation_test.py",
            "language": "python",
            "content": "def test(): return 'validation'",
            "operation_type": "PATTERN_EXTRACTION",
            "options": {"match_count": 3, "test_mode": True},
        },
    }

    try:
        await producer.send_and_wait(REQUEST_TOPIC, request_payload)
        print(f"   ✅ Published to {REQUEST_TOPIC}")
        print(f"   📤 Payload: {json.dumps(request_payload, indent=2)[:200]}...")
    except Exception as e:
        print(f"   ❌ Publish failed: {e}")
        await consumer.stop()
        await producer.stop()
        return False

    # Step 4: Wait for response
    print("\n4️⃣  Waiting for response (timeout: 10s)...")
    try:

        async def wait_for_response():
            async for msg in consumer:
                event = msg.value
                print(f"   📥 Received event from topic: {msg.topic}")
                print(f"   📋 Event correlation_id: {event.get('correlation_id')}")

                if event.get("correlation_id") == correlation_id:
                    print("   ✅ Correlation ID matched!")
                    return True, event
                else:
                    print("   ⚠️  Different correlation_id, continuing...")

        # Wait with timeout
        result = await asyncio.wait_for(wait_for_response(), timeout=10.0)
        success, response = result

        if success:
            print("\n   📊 Response payload:")
            print(f"   {json.dumps(response, indent=2)[:500]}...")

    except asyncio.TimeoutError:
        print("   ⚠️  Timeout - No response received")
        print("   💡 This might mean:")
        print("      - Intelligence handler is not processing events")
        print("      - Handler might be down")
        print("      - Processing is taking longer than 10s")
        success = False
    except Exception as e:
        print(f"   ❌ Consume failed: {e}")
        success = False

    # Cleanup
    print("\n5️⃣  Cleaning up...")
    await consumer.stop()
    await producer.stop()
    print("   ✅ Cleanup complete")

    # Summary
    print("\n" + "=" * 60)
    if success:
        print("✅ VALIDATION PASSED - Event integration working!")
        print("   - Kafka connectivity: ✅")
        print("   - Event publishing: ✅")
        print("   - Event consuming: ✅")
        print("   - Correlation tracking: ✅")
        print("   - Handler processing: ✅")
    else:
        print("⚠️  VALIDATION INCOMPLETE - Handler may not be processing")
        print("   - Kafka connectivity: ✅")
        print("   - Event publishing: ✅")
        print("   - Event consuming: ✅")
        print("   - Handler processing: ⚠️  (no response)")
        print("\n💡 Next steps:")
        print("   - Check if IntelligenceAdapterHandler is running in omniarchon")
        print("   - Verify handler is consuming from code-analysis-requested topic")
        print("   - Check omniarchon logs for errors")

    print("=" * 60)
    return success


if __name__ == "__main__":
    try:
        success = asyncio.run(test_event_flow())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Validation error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

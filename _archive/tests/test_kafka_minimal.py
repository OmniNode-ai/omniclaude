#!/usr/bin/env python3
"""Minimal Kafka producer test with verbose debugging"""

import json

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

# Test 1: AdminClient to check broker connectivity
print("=" * 60)
print("TEST 1: AdminClient connectivity test")
print("=" * 60)

admin_config = {
    "bootstrap.servers": "localhost:29092",
    "socket.timeout.ms": 10000,
}

print(f"Config: {admin_config}")

try:
    admin = AdminClient(admin_config)
    metadata = admin.list_topics(timeout=10)
    print("✓ Successfully connected!")
    print(f"✓ Found {len(metadata.topics)} topics:")
    for topic_name in list(metadata.topics.keys())[:5]:
        print(f"  - {topic_name}")
except Exception as e:
    print(f"✗ AdminClient failed: {e}")
    import traceback

    traceback.print_exc()

# Test 2: Producer with delivery callback
print("\n" + "=" * 60)
print("TEST 2: Producer with delivery callback")
print("=" * 60)

delivery_results = []


def delivery_callback(err, msg):
    if err:
        delivery_results.append(("error", str(err)))
        print(f"✗ Delivery failed: {err}")
    else:
        print(f"✓ Message delivered to {msg.topic()} [{msg.partition()}] @ offset {msg.offset()}")
        delivery_results.append(("success", msg.topic()))


producer_config = {
    "bootstrap.servers": "localhost:29092",
    "client.id": "minimal-test-producer",
    "socket.keepalive.enable": True,
    "api.version.request": True,
    "socket.timeout.ms": 30000,
    "message.timeout.ms": 30000,
    "debug": "broker,topic,msg",  # Verbose debugging
}

print(f"Config: {json.dumps({k: v for k, v in producer_config.items() if k != 'debug'}, indent=2)}")

try:
    producer = Producer(producer_config)

    test_message = {
        "test": "minimal_producer_test",
        "timestamp": "2025-10-18T12:00:00Z",
    }

    print(f"\nProducing message: {test_message}")
    producer.produce(
        topic="dev.omniclaude.docs.evt.documentation-changed.v1",
        value=json.dumps(test_message).encode("utf-8"),
        callback=delivery_callback,
    )

    print("Flushing producer (10s timeout)...")
    remaining = producer.flush(10)

    if remaining > 0:
        print(f"✗ WARNING: {remaining} messages still in queue after flush")
    else:
        print("✓ All messages flushed successfully")

    print(f"\nDelivery results: {delivery_results}")

    if delivery_results:
        status, details = delivery_results[0]
        if status == "success":
            print("✓ TEST PASSED: Message delivered successfully")
        else:
            print(f"✗ TEST FAILED: {details}")
    else:
        print("✗ TEST FAILED: No delivery confirmation received")

except Exception as e:
    print(f"✗ Producer failed: {e}")
    import traceback

    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST COMPLETE")
print("=" * 60)

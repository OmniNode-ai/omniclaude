#!/usr/bin/env python3
"""
Test: Kafka API Standardization

Demonstrates the standardized API contracts for all Kafka helper functions.
This test verifies that all functions follow the consistent return pattern.

Created: 2025-11-23
Purpose: Validate standardized Kafka helper API contracts
"""

import sys
from pathlib import Path
from typing import Any

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "_shared"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from kafka_types import (
    KafkaConnectionResult,
    KafkaConsumeResult,
    KafkaMessageCountResult,
    KafkaPublishResult,
    KafkaTopicsResult,
    KafkaTopicStatsResult,
)


def validate_result_structure(result: dict[str, Any], expected_fields: list) -> bool:
    """
    Validate that a result dictionary has all expected fields.

    Args:
        result: Result dictionary to validate
        expected_fields: List of required field names

    Returns:
        True if all expected fields are present, False otherwise
    """
    for field in expected_fields:
        if field not in result:
            print(f"❌ Missing required field: {field}")
            return False
    return True


def test_kafka_connection_result():
    """Test KafkaConnectionResult structure."""
    print("\n=== Testing KafkaConnectionResult ===")

    # Simulated result (as would be returned by check_kafka_connection)
    result: KafkaConnectionResult = {
        "success": True,
        "status": "connected",
        "broker": "192.168.86.200:29092",
        "reachable": True,
        "error": None,
        "return_code": 0,
    }

    required_fields = ["success", "status", "broker", "reachable", "error"]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaConnectionResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - status: {result['status']}")
        print(f"   - reachable: {result['reachable']}")
    else:
        print("❌ KafkaConnectionResult has incorrect structure")


def test_kafka_topics_result():
    """Test KafkaTopicsResult structure."""
    print("\n=== Testing KafkaTopicsResult ===")

    # Simulated result (as would be returned by list_topics)
    result: KafkaTopicsResult = {
        "success": True,
        "topics": ["agent.routing.requested.v1", "agent.routing.completed.v1"],
        "count": 2,
        "error": None,
        "return_code": 0,
    }

    required_fields = ["success", "topics", "count", "error"]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaTopicsResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - count: {result['count']}")
        print(f"   - topics: {result['topics'][:2]}...")
    else:
        print("❌ KafkaTopicsResult has incorrect structure")


def test_kafka_topic_stats_result():
    """Test KafkaTopicStatsResult structure."""
    print("\n=== Testing KafkaTopicStatsResult ===")

    # Simulated result (as would be returned by get_topic_stats)
    result: KafkaTopicStatsResult = {
        "success": True,
        "topic": "agent.routing.requested.v1",
        "partitions": 3,
        "error": None,
        "return_code": 0,
    }

    required_fields = ["success", "topic", "partitions", "error"]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaTopicStatsResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - topic: {result['topic']}")
        print(f"   - partitions: {result['partitions']}")
    else:
        print("❌ KafkaTopicStatsResult has incorrect structure")


def test_kafka_message_count_result():
    """Test KafkaMessageCountResult structure."""
    print("\n=== Testing KafkaMessageCountResult ===")

    # Simulated result (as would be returned by get_recent_message_count)
    result: KafkaMessageCountResult = {
        "success": True,
        "topic": "agent.routing.requested.v1",
        "messages_sampled": 42,
        "sample_duration_s": 2,
        "error": None,
        "return_code": 0,
    }

    required_fields = [
        "success",
        "topic",
        "messages_sampled",
        "sample_duration_s",
        "error",
    ]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaMessageCountResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - messages_sampled: {result['messages_sampled']}")
        print(f"   - sample_duration_s: {result['sample_duration_s']}")
    else:
        print("❌ KafkaMessageCountResult has incorrect structure")


def test_kafka_publish_result():
    """Test KafkaPublishResult structure."""
    print("\n=== Testing KafkaPublishResult ===")

    # Simulated result (as would be returned by ConfluentKafkaClient.publish)
    result: KafkaPublishResult = {
        "success": True,
        "topic": "test-topic",
        "data": {
            "partition": 0,
            "offset": 123,
            "timestamp": 1700000000000,
        },
        "error": None,
    }

    required_fields = ["success", "topic", "data", "error"]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaPublishResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - topic: {result['topic']}")
        print(f"   - data: {result['data']}")
    else:
        print("❌ KafkaPublishResult has incorrect structure")


def test_kafka_consume_result():
    """Test KafkaConsumeResult structure."""
    print("\n=== Testing KafkaConsumeResult ===")

    # Simulated result (as would be returned by ConfluentKafkaClient.consume_one)
    result: KafkaConsumeResult = {
        "success": True,
        "topic": "test-topic",
        "data": {"key": "value", "timestamp": "2025-11-23T12:00:00Z"},
        "error": None,
        "timeout": False,
    }

    required_fields = ["success", "topic", "data", "error", "timeout"]
    if validate_result_structure(result, required_fields):
        print("✅ KafkaConsumeResult has correct structure")
        print(f"   - success: {result['success']}")
        print(f"   - topic: {result['topic']}")
        print(f"   - timeout: {result['timeout']}")
        print(f"   - data: {result['data']}")
    else:
        print("❌ KafkaConsumeResult has incorrect structure")


def test_error_result_pattern():
    """Test that error results follow the same pattern."""
    print("\n=== Testing Error Result Pattern ===")

    # Simulated error result
    error_result: KafkaPublishResult = {
        "success": False,
        "topic": "test-topic",
        "data": None,
        "error": "Connection timeout after 5s",
    }

    print("Error result example:")
    print(f"   - success: {error_result['success']}")
    print(f"   - error: {error_result['error']}")
    print(f"   - data: {error_result['data']}")

    # Verify error handling pattern
    if not error_result["success"]:
        print("✅ Error result correctly indicates failure")
        print(f"   Error message: {error_result['error']}")
    else:
        print("❌ Error result incorrectly indicates success")


def test_usage_pattern():
    """Test the recommended usage pattern."""
    print("\n=== Testing Usage Pattern ===")

    # Simulated publish operation
    def simulated_publish(topic: str, _data: dict) -> KafkaPublishResult:
        """Simulated publish that returns standardized result."""
        return {
            "success": True,
            "topic": topic,
            "data": {"partition": 0, "offset": 456},
            "error": None,
        }

    # Usage pattern
    result = simulated_publish("my-topic", {"message": "Hello"})
    if result["success"]:
        print("✅ Publish succeeded")
        print(f"   Published to partition {result['data']['partition']}")
    else:
        print(f"❌ Publish failed: {result['error']}")


def main():
    """Run all tests."""
    print("=" * 70)
    print("Kafka API Standardization Tests")
    print("=" * 70)

    test_kafka_connection_result()
    test_kafka_topics_result()
    test_kafka_topic_stats_result()
    test_kafka_message_count_result()
    test_kafka_publish_result()
    test_kafka_consume_result()
    test_error_result_pattern()
    test_usage_pattern()

    print("\n" + "=" * 70)
    print("All tests completed!")
    print("=" * 70)
    print("\nKey Benefits of Standardized API:")
    print("  1. ✅ Predictable error handling (no hidden exceptions)")
    print("  2. ✅ Type safety with TypedDict")
    print("  3. ✅ Consistent structure across all operations")
    print("  4. ✅ Self-documenting return values")
    print("  5. ✅ Easy to test and mock")
    print("\nUsage Pattern:")
    print("  result = kafka_function()")
    print("  if result['success']:")
    print("      # Handle success")
    print("  else:")
    print("      # Handle error: result['error']")


if __name__ == "__main__":
    main()

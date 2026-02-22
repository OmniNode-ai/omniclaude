#!/usr/bin/env python3
"""
Kafka Type Definitions - Standardized return types for Kafka operations

Provides TypedDict definitions for consistent API contracts across all
Kafka helper functions and clients.

Created: 2025-11-23
Purpose: Prevent tech debt from inconsistent return patterns
"""

from typing import Any, TypedDict


class KafkaConnectionResult(TypedDict):
    """
    Result from Kafka connection check operations.

    Fields:
        success: True if operation succeeded, False otherwise
        status: Connection status ("connected", "error", "timeout")
        broker: Bootstrap server address
        reachable: Whether broker is reachable
        error: Error message if operation failed (None on success)
        return_code: Process return code if applicable (None for non-process errors)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    status: str
    broker: str
    reachable: bool
    error: str | None
    return_code: int | None


class KafkaTopicsResult(TypedDict):
    """
    Result from topic listing operations.

    Fields:
        success: True if operation succeeded, False otherwise
        topics: List of topic names (empty list on failure)
        count: Number of topics found
        error: Error message if operation failed (None on success)
        return_code: Process return code if applicable (None for non-process errors)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    topics: list[str]
    count: int
    error: str | None
    return_code: int | None


class KafkaTopicStatsResult(TypedDict):
    """
    Result from topic statistics operations.

    Fields:
        success: True if operation succeeded, False otherwise
        topic: Topic name
        partitions: Number of partitions
        error: Error message if operation failed (None on success)
        return_code: Process return code if applicable (None for non-process errors)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    topic: str
    partitions: int
    error: str | None
    return_code: int | None


class KafkaConsumerGroupsResult(TypedDict):
    """
    Result from consumer group listing operations.

    Fields:
        success: True if operation succeeded, False otherwise
        groups: List of consumer group names (empty list on failure)
        count: Number of consumer groups found
        error: Error message if operation failed (None on success)
        implemented: Whether the operation is implemented (False for placeholder)
        return_code: Process return code if applicable (None for non-process errors)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    groups: list[str]
    count: int
    error: str | None
    implemented: bool
    return_code: int | None


class KafkaMessageCountResult(TypedDict):
    """
    Result from message count sampling operations.

    Fields:
        success: True if operation succeeded, False otherwise
        topic: Topic name
        messages_sampled: Number of messages found (0 on failure)
        sample_duration_s: Sampling duration in seconds
        error: Error message if operation failed (None on success)
        return_code: Process return code if applicable (None for non-process errors)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.

        Distinguishes between:
        - "0 messages found" (success=True, messages_sampled=0)
        - "operation failed" (success=False, error contains details)
    """

    success: bool
    topic: str
    messages_sampled: int
    sample_duration_s: int
    error: str | None
    return_code: int | None


class KafkaPublishResult(TypedDict):
    """
    Result from message publishing operations.

    Fields:
        success: True if message published, False otherwise
        topic: Topic name
        data: Publish metadata on success (partition, offset, timestamp)
        error: Error message if publish failed (None on success)

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    topic: str
    data: dict[str, Any] | None
    error: str | None


class KafkaConsumeResult(TypedDict):
    """
    Result from message consumption operations.

    Fields:
        success: True if message consumed, False otherwise
        topic: Topic name
        data: Message payload on success (None if no message or error)
        error: Error message if consume failed (None on success)
        timeout: Whether operation timed out waiting for message

    Note:
        All fields are always present. Optional types indicate the value may be None,
        not that the key may be missing.
    """

    success: bool
    topic: str
    data: dict[str, Any] | None
    error: str | None
    timeout: bool


# API Contract Documentation

"""
KAFKA HELPER API CONTRACT
=========================

All Kafka helper functions follow this standardized contract:

1. **Return Type**: Always return a TypedDict (never raise exceptions to caller)

2. **Success Indication**: All results include a 'success' boolean field
   - success=True: Operation completed successfully
   - success=False: Operation failed (check 'error' field for details)

3. **Error Handling**: All results include an 'error' field
   - error=None: No error occurred
   - error="description": Error description for debugging

4. **Data Fields**: Context-specific fields based on operation type
   - Always use consistent field names across functions
   - Use Optional types for fields that may be absent

5. **Type Safety**: All functions have complete type hints
   - Parameters: Fully typed with defaults where applicable
   - Return types: Specific TypedDict for each operation

6. **Documentation**: All functions have docstrings documenting:
   - Purpose and behavior
   - Parameters and their types
   - Return value structure
   - Examples of usage

USAGE EXAMPLES
==============

Connection Check:
    result = check_kafka_connection()
    if result["success"]:
        print(f"Connected to {result['broker']}")
    else:
        print(f"Connection failed: {result['error']}")

Topic Listing:
    result = list_topics()
    if result["success"]:
        print(f"Found {result['count']} topics: {result['topics']}")
    else:
        print(f"Failed to list topics: {result['error']}")

Message Publishing:
    result = publish_message("my-topic", {"key": "value"})
    if result["success"]:
        print(f"Published to partition {result['data']['partition']}")
    else:
        print(f"Publish failed: {result['error']}")

Message Consumption:
    result = consume_message("my-topic", timeout_sec=5.0)
    if result["success"] and result["data"]:
        print(f"Received: {result['data']}")
    elif result.get("timeout"):
        print("No message available within timeout")
    else:
        print(f"Consume failed: {result['error']}")

MIGRATION GUIDE
===============

Old Pattern (Exception-based):
    try:
        client.publish("topic", data)
        print("Success")
    except RuntimeError as e:
        print(f"Failed: {e}")

New Pattern (Result-based):
    result = publish_message("topic", data)
    if result["success"]:
        print("Success")
    else:
        print(f"Failed: {result['error']}")

Benefits:
    - Explicit error handling (no hidden exceptions)
    - Type-safe result inspection
    - Consistent patterns across all functions
    - Easy to test and mock
    - Self-documenting return values
"""

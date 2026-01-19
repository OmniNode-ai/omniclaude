#!/usr/bin/env python3
"""
Shared Kafka publisher module for skill scripts.

Provides singleton Kafka producer with lazy loading and caching to eliminate
code duplication across 5+ agent-tracking and routing skills.

This module consolidates common Kafka producer creation logic that was previously
duplicated in:
- skills/agent-tracking/log-agent-action/execute_kafka.py
- skills/agent-tracking/log-performance-metrics/execute_kafka.py
- skills/agent-tracking/log-routing-decision/execute_kafka.py
- skills/agent-tracking/log-transformation/execute_kafka.py
- skills/routing/request-agent-routing/execute_kafka.py

Usage:
    from shared_lib.kafka_publisher import get_kafka_producer, should_log_debug

    # Check if debug logging is enabled
    if should_log_debug():
        producer = get_kafka_producer()
        producer.send('my-topic', value={'key': 'value'})

Features:
    - Singleton pattern to prevent connection/memory leaks
    - Lazy import to avoid errors if kafka-python not installed
    - JSON serialization built-in
    - Performance optimization (compression, batching)
    - Proper cleanup with close_kafka_producer()

Created: 2025-11-16
Correlation ID: 1b24e91e-c470-46db-896b-be0d6cdec9c6
Version: 1.0.0
"""

import json
import os
import sys

# Import centralized Kafka configuration
from kafka_config import get_kafka_bootstrap_servers

# Lazy-loaded Kafka types (imported only when needed)
# Type hints only - actual import happens in get_kafka_producer()
try:
    from kafka import KafkaProducer as KafkaProducerClass
except ImportError:
    KafkaProducerClass = None  # Type hint placeholder when kafka-python not installed

# Global state for singleton pattern
KafkaProducer: type | None = None
_producer_instance: KafkaProducerClass | None = None


def should_log_debug() -> bool:
    """
    Check if debug logging is enabled via DEBUG environment variable.

    Checks for truthy values: "true", "1", "yes", "on" (case-insensitive).

    Returns:
        bool: True if debug logging is enabled, False otherwise

    Examples:
        >>> os.environ['DEBUG'] = 'true'
        >>> should_log_debug()
        True

        >>> os.environ['DEBUG'] = 'false'
        >>> should_log_debug()
        False

        >>> os.environ.pop('DEBUG', None)
        >>> should_log_debug()
        False

    Notes:
        - Used by skills to conditionally enable Kafka logging
        - Can be overridden by --debug-mode flag in skill scripts
        - Environment variable is case-insensitive
    """
    debug_env = os.environ.get("DEBUG", "").lower()
    return debug_env in ("true", "1", "yes", "on")


def get_kafka_producer():
    """
    Get or create Kafka producer (singleton pattern).

    Lazy imports kafka-python to avoid import errors if not installed.
    Returns cached producer instance to prevent connection/memory leaks.

    The producer is configured with:
    - JSON value serialization (automatic encoding)
    - GZIP compression for network efficiency
    - Message batching (10ms linger, 16KB batches)
    - Balanced reliability (acks=1, 3 retries)
    - Up to 5 in-flight requests for throughput

    Returns:
        KafkaProducer: Singleton Kafka producer instance

    Raises:
        ImportError: If kafka-python is not installed

    Examples:
        >>> producer = get_kafka_producer()
        >>> producer.send('my-topic', value={'key': 'value'})
        <FutureRecordMetadata ...>

        >>> # Second call returns cached instance
        >>> producer2 = get_kafka_producer()
        >>> producer is producer2
        True

    Notes:
        - Automatically uses get_kafka_bootstrap_servers() for broker config
        - Creates instance on first call, returns cached instance thereafter
        - Call close_kafka_producer() on graceful shutdown to cleanup
        - Thread-safe for single-threaded event loops

    Performance:
        - Compression: GZIP (~60-70% size reduction)
        - Batching: 10ms linger time, 16KB batch size
        - Reliability: acks=1 (leader acknowledgment)
        - Throughput: Up to 5 in-flight requests
    """
    global KafkaProducer, _producer_instance

    # Return cached instance if available
    if _producer_instance is not None:
        return _producer_instance

    # Import KafkaProducer class if not already imported
    if KafkaProducer is None:
        try:
            from kafka import KafkaProducer
        except ImportError:
            raise ImportError(
                "kafka-python not installed. Install with: pip install kafka-python"
            )

    # Get Kafka brokers from centralized configuration
    brokers = get_kafka_bootstrap_servers().split(",")

    # Create producer with JSON serialization
    producer = KafkaProducer(
        bootstrap_servers=brokers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        # Performance settings
        compression_type="gzip",
        linger_ms=10,  # Batch messages for 10ms
        batch_size=16384,  # 16KB batches
        # Reliability settings
        acks=1,  # Wait for leader acknowledgment (balance of speed/reliability)
        retries=3,
        max_in_flight_requests_per_connection=5,
    )

    # Cache the instance for reuse
    _producer_instance = producer

    return producer


def close_kafka_producer() -> None:
    """
    Close and cleanup the cached Kafka producer instance.

    Should be called on graceful shutdown to properly close connections
    and flush pending messages.

    Examples:
        >>> producer = get_kafka_producer()
        >>> # ... use producer ...
        >>> close_kafka_producer()
        >>> # Subsequent calls to get_kafka_producer() will create new instance

    Notes:
        - Safe to call even if no producer exists (idempotent)
        - Errors during close are logged but not raised
        - Resets global _producer_instance to None
        - Next call to get_kafka_producer() will create fresh instance

    Error Handling:
        - Catches all exceptions during close to prevent shutdown failures
        - Logs errors to stderr but doesn't raise
        - Always resets _producer_instance regardless of errors
    """
    global _producer_instance

    if _producer_instance is not None:
        try:
            _producer_instance.close()
        except Exception as e:
            # Log error but don't raise - this is cleanup code
            print(f"Error closing Kafka producer: {e}", file=sys.stderr)
        finally:
            _producer_instance = None


__all__ = [
    "should_log_debug",
    "get_kafka_producer",
    "close_kafka_producer",
]

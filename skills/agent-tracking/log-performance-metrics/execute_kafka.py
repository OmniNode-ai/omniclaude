#!/usr/bin/env python3
"""
Log Performance Metrics Skill - Kafka Version

Publishes router performance metrics to Kafka for async, non-blocking logging
with multiple consumers (PostgreSQL, dashboards, analytics).

Usage:
  /log-performance-metrics --query "optimize API performance" --duration-ms 45 --cache-hit false --candidates 5

Options:
  --query: Query text that was routed (required)
  --duration-ms: Routing duration in milliseconds (required)
  --cache-hit: Whether result was from cache (required, true/false)
  --candidates: Number of candidate agents evaluated (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --strategy: Trigger match strategy used (optional)
  --confidence-components: JSON object with confidence breakdown (optional)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id, parse_json_param

# Kafka imports (lazy loaded)
KafkaProducer = None
_producer_instance = None  # Cached producer instance for singleton pattern


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


def get_kafka_producer():
    """
    Get or create Kafka producer (singleton pattern).
    Lazy imports kafka-python to avoid import errors if not installed.
    Returns cached producer instance to prevent connection/memory leaks.
    """
    global KafkaProducer, _producer_instance

    # Return cached instance if available
    if _producer_instance is not None:
        return _producer_instance

    # Import KafkaProducer class if not already imported
    if KafkaProducer is None:
        try:
            from kafka import KafkaProducer as KP

            KafkaProducer = KP
        except ImportError:
            raise ImportError(
                "kafka-python not installed. Install with: pip install kafka-python"
            )

    # Get Kafka brokers from environment
    brokers = os.environ.get("KAFKA_BROKERS", "localhost:29102").split(",")

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


def publish_to_kafka(event: dict, topic: str = "router-performance-metrics") -> bool:
    """
    Publish event to Kafka topic.

    Args:
        event: Event dictionary to publish
        topic: Kafka topic name

    Returns:
        True if published successfully, False otherwise
    """
    try:
        producer = get_kafka_producer()

        # Use correlation_id for partitioning (maintains ordering per correlation)
        partition_key = event.get("correlation_id", "").encode("utf-8")

        # Publish async
        future = producer.send(topic, value=event, key=partition_key)

        # Wait up to 1 second for send to complete
        future.get(timeout=1.0)

        return True

    except Exception as e:
        # Log error but don't fail - this is observability, not critical path
        error_msg = f"Failed to publish to Kafka: {e}"
        print(error_msg, file=sys.stderr)
        return False


def log_performance_metrics_kafka(args):
    """Log performance metrics to Kafka."""

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse cache_hit boolean
    cache_hit = parse_boolean(args.cache_hit)

    # Parse confidence components JSON
    confidence_components = (
        parse_json_param(args.confidence_components)
        if hasattr(args, "confidence_components") and args.confidence_components
        else {}
    )

    # Validate duration (must be < 1000ms per schema constraint)
    duration_ms = int(args.duration_ms)
    if duration_ms < 0 or duration_ms >= 1000:
        error = {
            "success": False,
            "error": f"Routing duration must be between 0 and 999ms, got {duration_ms}",
        }
        print(json.dumps(error), file=sys.stderr)
        return 1

    # Build event
    event = {
        "correlation_id": correlation_id,
        "query_text": args.query,
        "routing_duration_ms": duration_ms,
        "cache_hit": cache_hit,
        "trigger_match_strategy": (
            args.strategy if hasattr(args, "strategy") and args.strategy else None
        ),
        "confidence_components": confidence_components,
        "candidates_evaluated": int(args.candidates),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Publish to Kafka
    success = publish_to_kafka(event, topic="router-performance-metrics")

    if success:
        output = {
            "success": True,
            "correlation_id": correlation_id,
            "query_text": args.query,
            "routing_duration_ms": duration_ms,
            "cache_hit": cache_hit,
            "candidates_evaluated": int(args.candidates),
            "published_to": "kafka",
            "topic": "router-performance-metrics",
        }
        print(json.dumps(output, indent=2))
        return 0
    else:
        # Kafka publish failed - could fall back to direct DB here
        error = {
            "success": False,
            "error": "Failed to publish to Kafka",
            "fallback": "Consider implementing direct DB fallback",
        }
        print(json.dumps(error), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log router performance metrics to Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--query", required=True, help="Query text that was routed")
    parser.add_argument(
        "--duration-ms",
        required=True,
        type=int,
        help="Routing duration in milliseconds",
    )
    parser.add_argument(
        "--cache-hit", required=True, help="Whether result was from cache (true/false)"
    )
    parser.add_argument(
        "--candidates",
        required=True,
        type=int,
        help="Number of candidate agents evaluated",
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--strategy", help="Trigger match strategy used")
    parser.add_argument(
        "--confidence-components", help="JSON object with confidence breakdown"
    )

    args = parser.parse_args()

    return log_performance_metrics_kafka(args)


if __name__ == "__main__":
    sys.exit(main())

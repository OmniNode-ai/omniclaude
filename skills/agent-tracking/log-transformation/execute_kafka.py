#!/usr/bin/env python3
"""
Log Transformation Skill - Kafka Version

Publishes agent transformation events to Kafka for async, non-blocking logging
with multiple consumers (PostgreSQL, dashboards, analytics).

Usage:
  /log-transformation --from-agent agent-workflow-coordinator --to-agent agent-api-architect --success true --duration-ms 85

Options:
  --from-agent: Source agent name (required)
  --to-agent: Target agent name (required)
  --success: Whether transformation succeeded (required, true/false)
  --duration-ms: Transformation duration in milliseconds (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --reason: Transformation reason/description (optional)
  --confidence: Routing confidence score that led to transformation (optional, 0.0-1.0)
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id

# Kafka imports (lazy loaded)
KafkaProducer = None


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


def get_kafka_producer():
    """
    Get or create Kafka producer (singleton pattern).
    Lazy imports kafka-python to avoid import errors if not installed.
    """
    global KafkaProducer

    if KafkaProducer is None:
        try:
            from kafka import KafkaProducer as KP

            KafkaProducer = KP
        except ImportError:
            raise ImportError(
                "kafka-python not installed. Install with: pip install kafka-python"
            )

    # Get Kafka brokers from environment
    brokers = os.environ.get("KAFKA_BROKERS", "localhost:9092").split(",")

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

    return producer


def publish_to_kafka(event: dict, topic: str = "agent-transformation-events") -> bool:
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


def log_transformation_kafka(args):
    """Log transformation event to Kafka."""

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse success boolean
    success = parse_boolean(args.success)

    # Validate confidence if provided
    confidence = None
    if hasattr(args, "confidence") and args.confidence:
        confidence = float(args.confidence)
        if confidence < 0.0 or confidence > 1.0:
            error = {
                "success": False,
                "error": f"Confidence score must be between 0.0 and 1.0, got {confidence}",
            }
            print(json.dumps(error), file=sys.stderr)
            return 1

    # Build event
    event = {
        "correlation_id": correlation_id,
        "source_agent": args.from_agent,
        "target_agent": args.to_agent,
        "transformation_reason": (
            args.reason if hasattr(args, "reason") and args.reason else None
        ),
        "confidence_score": confidence,
        "transformation_duration_ms": int(args.duration_ms),
        "success": success,
        "timestamp": datetime.utcnow().isoformat(),
    }

    # Publish to Kafka
    success_publish = publish_to_kafka(event, topic="agent-transformation-events")

    if success_publish:
        output = {
            "success": True,
            "correlation_id": correlation_id,
            "source_agent": args.from_agent,
            "target_agent": args.to_agent,
            "transformation_success": success,
            "duration_ms": int(args.duration_ms),
            "published_to": "kafka",
            "topic": "agent-transformation-events",
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
        description="Log agent transformation event to Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--from-agent", required=True, help="Source agent name")
    parser.add_argument("--to-agent", required=True, help="Target agent name")
    parser.add_argument(
        "--success", required=True, help="Whether transformation succeeded (true/false)"
    )
    parser.add_argument(
        "--duration-ms",
        required=True,
        type=int,
        help="Transformation duration in milliseconds",
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--reason", help="Transformation reason/description")
    parser.add_argument(
        "--confidence", type=float, help="Routing confidence score (0.0-1.0)"
    )

    args = parser.parse_args()

    return log_transformation_kafka(args)


if __name__ == "__main__":
    sys.exit(main())

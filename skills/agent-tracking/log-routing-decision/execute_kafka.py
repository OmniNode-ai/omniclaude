#!/usr/bin/env python3
"""
Log Routing Decision Skill - Kafka Version

Publishes routing decisions to Kafka for async, non-blocking logging with
multiple consumers (PostgreSQL, dashboards, analytics).

Usage:
  /log-routing-decision --agent AGENT_NAME --confidence 0.95 --strategy enhanced_fuzzy_matching --latency-ms 45

Options:
  --agent: Selected agent name (required)
  --confidence: Confidence score 0.0-1.0 (required)
  --strategy: Routing strategy used (required)
  --latency-ms: Routing latency in milliseconds (required)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --user-request: Original user request text (optional)
  --alternatives: JSON array of alternative agents considered (optional)
  --reasoning: Reasoning for agent selection (optional)
  --context: JSON object with additional context (optional)

Project context (optional):
  --project-path: Absolute path to project directory (optional)
  --project-name: Project name (optional)
  --session-id: Claude session ID (optional)
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

# Add lib to path for kafka_config
sys.path.insert(0, str(Path.home() / ".claude" / "lib"))
from kafka_config import get_kafka_bootstrap_servers


# Load .env file from project directory
def load_env_file():
    """Load environment variables from project .env file."""
    # Calculate project root from this file's location (skills/agent-tracking/log-routing-decision/)
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env_paths = [
        project_root / ".env",
        Path.home() / "Code" / "omniclaude" / ".env",
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        # Only set if not already in environment
                        if key not in os.environ:
                            os.environ[key] = value.strip('"').strip("'")
            return


# Load .env on import
load_env_file()

# Kafka imports (lazy loaded)
KafkaProducer = None
_producer_instance = None  # Cached producer instance for singleton pattern


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


def publish_to_kafka(event: dict, topic: str = "agent-routing-decisions") -> bool:
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


def log_routing_decision_kafka(args):
    """Log routing decision to Kafka."""

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse JSON parameters
    alternatives = (
        parse_json_param(args.alternatives)
        if hasattr(args, "alternatives") and args.alternatives
        else []
    )
    context = (
        parse_json_param(args.context)
        if hasattr(args, "context") and args.context
        else {}
    )

    # Add correlation_id to context
    context["correlation_id"] = correlation_id

    # Validate confidence score
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
        "user_request": (
            args.user_request
            if hasattr(args, "user_request") and args.user_request
            else ""
        ),
        "selected_agent": args.agent,
        "confidence_score": confidence,
        "alternatives": alternatives,
        "reasoning": (
            args.reasoning if hasattr(args, "reasoning") and args.reasoning else None
        ),
        "routing_strategy": args.strategy,
        "context": context,
        "routing_time_ms": int(args.latency_ms),
        "project_path": (
            args.project_path
            if hasattr(args, "project_path") and args.project_path
            else None
        ),
        "project_name": (
            args.project_name
            if hasattr(args, "project_name") and args.project_name
            else None
        ),
        "session_id": (
            args.session_id if hasattr(args, "session_id") and args.session_id else None
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Publish to Kafka
    success = publish_to_kafka(event, topic="agent-routing-decisions")

    if success:
        output = {
            "success": True,
            "correlation_id": correlation_id,
            "selected_agent": args.agent,
            "confidence_score": confidence,
            "routing_strategy": args.strategy,
            "routing_time_ms": int(args.latency_ms),
            "published_to": "kafka",
            "topic": "agent-routing-decisions",
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
        description="Log agent routing decision to Kafka",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Selected agent name")
    parser.add_argument(
        "--confidence", required=True, type=float, help="Confidence score (0.0-1.0)"
    )
    parser.add_argument("--strategy", required=True, help="Routing strategy used")
    parser.add_argument(
        "--latency-ms", required=True, type=int, help="Routing latency in milliseconds"
    )

    # Optional arguments
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument("--user-request", help="Original user request text")
    parser.add_argument("--alternatives", help="JSON array of alternative agents")
    parser.add_argument("--reasoning", help="Reasoning for agent selection")
    parser.add_argument("--context", help="JSON object with additional context")

    # Project context arguments
    parser.add_argument("--project-path", help="Absolute path to project directory")
    parser.add_argument("--project-name", help="Project name")
    parser.add_argument("--session-id", help="Claude session ID")

    args = parser.parse_args()

    return log_routing_decision_kafka(args)


if __name__ == "__main__":
    sys.exit(main())

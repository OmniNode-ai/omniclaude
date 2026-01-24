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
from datetime import UTC, datetime
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id, parse_json_param

# Add shared_lib to path for kafka_config and kafka_publisher
# Path: execute_kafka.py -> log-performance-metrics/ -> agent-tracking/ -> skills/ -> claude-artifacts/ -> omniclaude/
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent.parent / "shared_lib")
)
from kafka_publisher import get_kafka_producer


# Load .env file from project directory
# TODO: This load_env_file() function is duplicated across all agent-tracking skills:
#   - log-transformation/execute_kafka.py
#   - log-performance-metrics/execute_kafka.py
#   - log-agent-action/execute_kafka.py
#   - log-routing-decision/execute_kafka.py
# Consider consolidating into plugins/onex/skills/_shared/env_loader.py
def load_env_file():
    """Load environment variables from project .env file."""
    # Calculate project root from this file's location (skills/agent-tracking/log-performance-metrics/)
    project_root = Path(__file__).parent.parent.parent.parent.parent.resolve()
    env_paths = [
        project_root / ".env",
        Path.home() / "Code" / "omniclaude" / ".env",
    ]

    for env_path in env_paths:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as f:
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


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


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
        "timestamp": datetime.now(UTC).isoformat(),
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

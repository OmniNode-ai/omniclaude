#!/usr/bin/env python3
"""
Log Agent Action Skill - Kafka Version

Publishes agent actions to Kafka for async, non-blocking logging with
multiple consumers (PostgreSQL, dashboards, analytics).

Usage:
  /log-agent-action --agent AGENT_NAME --action-type TYPE --action-name NAME --details JSON

Options:
  --agent: Agent name performing the action (required)
  --action-type: Type of action (tool_call|decision|error|success) (required)
  --action-name: Specific action name (required)
  --details: JSON object with action-specific details (optional)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --debug-mode: Force debug logging regardless of DEBUG env var (optional)
  --duration-ms: How long the action took in milliseconds (optional)
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


def should_log_debug() -> bool:
    """Check if debug logging is enabled."""
    debug_env = os.environ.get("DEBUG", "").lower()
    return debug_env in ("true", "1", "yes", "on")


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


def close_kafka_producer():
    """
    Close and cleanup the cached Kafka producer instance.
    Should be called on graceful shutdown to properly close connections.
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


def publish_to_kafka(event: dict, topic: str = "agent-actions") -> bool:
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


def log_agent_action_kafka(args):
    """Log agent action to Kafka."""

    # Check if we should log (debug mode)
    force_debug = getattr(args, "debug_mode", False)
    if not force_debug and not should_log_debug():
        # Silent skip in non-debug mode
        output = {
            "success": True,
            "skipped": True,
            "reason": "debug_mode_disabled",
            "message": "Action logging skipped (DEBUG mode not enabled)",
        }
        print(json.dumps(output, indent=2))
        return 0

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse JSON details
    details = {}
    if hasattr(args, "details") and args.details:
        details = parse_json_param(args.details)
        if details is None:
            details = {}

    # Build event
    event = {
        "correlation_id": correlation_id,
        "agent_name": args.agent,
        "action_type": args.action_type,
        "action_name": args.action_name,
        "action_details": details,
        "debug_mode": True,
        "duration_ms": (
            int(args.duration_ms)
            if hasattr(args, "duration_ms") and args.duration_ms
            else None
        ),
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
        "working_directory": (
            args.working_directory
            if hasattr(args, "working_directory") and args.working_directory
            else None
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Publish to Kafka
    success = publish_to_kafka(event, topic="agent-actions")

    if success:
        output = {
            "success": True,
            "correlation_id": correlation_id,
            "agent_name": args.agent,
            "action_type": args.action_type,
            "action_name": args.action_name,
            "debug_mode": True,
            "published_to": "kafka",
            "topic": "agent-actions",
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
        description="Log agent action to Kafka (debug mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Agent name performing action")
    parser.add_argument(
        "--action-type",
        required=True,
        choices=["tool_call", "decision", "error", "success"],
        help="Type of action",
    )
    parser.add_argument("--action-name", required=True, help="Specific action name")

    # Optional arguments
    parser.add_argument("--details", help="JSON object with action details")
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument(
        "--debug-mode",
        action="store_true",
        help="Force debug logging (override DEBUG env var)",
    )
    parser.add_argument(
        "--duration-ms", type=int, help="Action duration in milliseconds"
    )

    # Project context arguments
    parser.add_argument("--project-path", help="Absolute path to project directory")
    parser.add_argument("--project-name", help="Project name")
    parser.add_argument("--working-directory", help="Current working directory")

    args = parser.parse_args()

    return log_agent_action_kafka(args)


if __name__ == "__main__":
    sys.exit(main())

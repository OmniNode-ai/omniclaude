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
from datetime import datetime, timezone
from pathlib import Path


# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import get_correlation_id


# Add shared_lib to path for kafka_config and kafka_publisher
# Path: execute_kafka.py -> log-transformation/ -> agent-tracking/ -> skills/ -> claude-artifacts/ -> omniclaude/
sys.path.insert(
    0, str(Path(__file__).parent.parent.parent.parent.parent / "shared_lib")
)
from kafka_config import get_kafka_bootstrap_servers
from kafka_publisher import get_kafka_producer


# Add agents/lib to path for transformation_validator
agents_lib_path = Path(__file__).parent.parent.parent.parent.parent / "agents" / "lib"
if agents_lib_path.exists():
    sys.path.insert(0, str(agents_lib_path))
    from transformation_validator import validate_transformation


# Load .env file from project directory
def load_env_file():
    """Load environment variables from project .env file."""
    # Calculate project root from this file's location (skills/agent-tracking/log-transformation/)
    project_root = Path(__file__).parent.parent.parent.parent.parent.resolve()
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


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


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

    # Check for forbidden "Direct execution" bypass patterns
    reason = args.reason if hasattr(args, "reason") and args.reason else ""

    # CRITICAL: Detect routing bypass attempts
    forbidden_patterns = [
        "direct execution",
        "skip routing",
        "bypass routing",
        "without routing",
        "skipping router",
    ]

    reason_lower = reason.lower() if reason else ""
    for pattern in forbidden_patterns:
        if pattern in reason_lower:
            error = {
                "success": False,
                "error": (
                    f"ROUTING BYPASS DETECTED: Transformation reason contains forbidden pattern '{pattern}'. "
                    f"The polymorphic agent MUST run router.route() for ALL tasks. "
                    f"See agents/polymorphic-agent.md § 'ANTI-PATTERNS: What NOT to Do' for details. "
                    f"Reason provided: {reason}"
                ),
                "from_agent": args.from_agent,
                "to_agent": args.to_agent,
                "forbidden_pattern": pattern,
                "bypass_rate_target": "0%",
            }
            print(json.dumps(error), file=sys.stderr)
            return 1

    # Validate self-transformation using shared validator
    # Only validate if transformation_validator is available
    if "validate_transformation" in globals():
        validation_result = validate_transformation(
            from_agent=args.from_agent,
            to_agent=args.to_agent,
            reason=reason,
            confidence=confidence,
        )

        # Check if validation failed
        if not validation_result.is_valid:
            error = {
                "success": False,
                "error": f"Self-transformation validation failed: {validation_result.error_message}",
                "from_agent": args.from_agent,
                "to_agent": args.to_agent,
                "confidence": confidence,
                "metrics": validation_result.metrics,
            }
            print(json.dumps(error), file=sys.stderr)
            return 1

        # Print warning if present
        if validation_result.warning_message:
            print(f"WARNING: {validation_result.warning_message}", file=sys.stderr)

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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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

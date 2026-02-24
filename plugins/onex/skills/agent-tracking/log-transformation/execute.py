#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Log Transformation Skill - Track agent transformation events in PostgreSQL

Logs agent transformation events when the workflow coordinator transforms
from one agent identity to another during task execution.

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
import sys
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
)


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


def log_transformation(args):
    """Log a transformation event to the database."""

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
            return handle_db_error(
                ValueError(
                    f"Confidence score must be between 0.0 and 1.0, got {confidence}"
                ),
                "log_transformation",
            )

    # Prepare SQL
    sql = """
    INSERT INTO agent_transformation_events (
        source_agent,
        target_agent,
        transformation_reason,
        confidence_score,
        transformation_duration_ms,
        success
    ) VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id, created_at
    """

    params = (
        args.from_agent,
        args.to_agent,
        args.reason if hasattr(args, "reason") and args.reason else None,
        confidence,
        int(args.duration_ms),
        success,
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            output = {
                "success": True,
                "transformation_id": str(row["id"]),
                "correlation_id": correlation_id,
                "source_agent": args.from_agent,
                "target_agent": args.to_agent,
                "transformation_success": success,
                "duration_ms": int(args.duration_ms),
                "created_at": row["created_at"].isoformat(),
            }
            print(json.dumps(output, indent=2))
            return 0
        else:
            error = {"success": False, "error": "No result returned from database"}
            print(json.dumps(error), file=sys.stderr)
            return 1

    except Exception as e:
        error_info = handle_db_error(e, "log_transformation")
        print(json.dumps(error_info), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent transformation event to PostgreSQL",
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

    return log_transformation(args)


if __name__ == "__main__":
    sys.exit(main())

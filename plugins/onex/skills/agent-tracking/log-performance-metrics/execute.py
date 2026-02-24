#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Log Performance Metrics Skill - Track router performance metrics in PostgreSQL

Logs router performance metrics including routing duration, cache hits,
trigger match strategies, and confidence components.

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
import sys
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
)


def parse_boolean(value: str) -> bool:
    """Parse boolean value from string."""
    if isinstance(value, bool):
        return value
    return value.lower() in ("true", "1", "yes", "y")


def log_performance_metrics(args):
    """Log performance metrics to the database."""

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
        return handle_db_error(
            ValueError(
                f"Routing duration must be between 0 and 999ms, got {duration_ms}"
            ),
            "log_performance_metrics",
        )

    # Prepare SQL
    sql = """
    INSERT INTO router_performance_metrics (
        query_text,
        routing_duration_ms,
        cache_hit,
        trigger_match_strategy,
        confidence_components,
        candidates_evaluated
    ) VALUES (%s, %s, %s, %s, %s, %s)
    RETURNING id, created_at
    """

    params = (
        args.query,
        duration_ms,
        cache_hit,
        args.strategy if hasattr(args, "strategy") and args.strategy else None,
        json.dumps(confidence_components),
        int(args.candidates),
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            output = {
                "success": True,
                "metric_id": str(row["id"]),
                "correlation_id": correlation_id,
                "query_text": args.query,
                "routing_duration_ms": duration_ms,
                "cache_hit": cache_hit,
                "candidates_evaluated": int(args.candidates),
                "created_at": row["created_at"].isoformat(),
            }
            print(json.dumps(output, indent=2))
            return 0
        else:
            error = {"success": False, "error": "No result returned from database"}
            print(json.dumps(error), file=sys.stderr)
            return 1

    except Exception as e:
        error_info = handle_db_error(e, "log_performance_metrics")
        print(json.dumps(error_info), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log router performance metrics to PostgreSQL",
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

    return log_performance_metrics(args)


if __name__ == "__main__":
    sys.exit(main())

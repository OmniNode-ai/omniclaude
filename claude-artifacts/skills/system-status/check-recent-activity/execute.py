#!/usr/bin/env python3
"""
Check Recent Activity - Recent agent executions and system activity

Usage:
    python3 execute.py [--limit 20] [--since 5m] [--include-errors]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from constants import (
        DEFAULT_ACTIVITY_LIMIT,
        MAX_LIMIT,
        MIN_LIMIT,
    )
    from db_helper import execute_query
    from status_formatter import format_json
    from timeframe_helper import parse_timeframe
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def validate_limit(value: str) -> int:
    """Validate --limit parameter is within acceptable range.

    Args:
        value: String value from argparse

    Returns:
        Validated integer value

    Raises:
        argparse.ArgumentTypeError: If value is out of bounds
    """
    ivalue: int = int(value)
    if not (MIN_LIMIT <= ivalue <= MAX_LIMIT):
        raise argparse.ArgumentTypeError(
            f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}"
        )
    return ivalue


def main() -> int:
    parser = argparse.ArgumentParser(description="Check recent activity")
    parser.add_argument(
        "--limit",
        type=validate_limit,
        default=DEFAULT_ACTIVITY_LIMIT,
        help=f"Number of records ({MIN_LIMIT}-{MAX_LIMIT})",
    )
    parser.add_argument(
        "--since", default="5m", help="Time period (5m, 15m, 1h, 24h, 7d)"
    )
    parser.add_argument("--include-errors", action="store_true", help="Include errors")
    args = parser.parse_args()

    # Validate and parse timeframe
    try:
        interval = parse_timeframe(args.since)
    except ValueError as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1

    result = {"timeframe": args.since}

    try:
        # Manifest injections
        manifest_query = """
            SELECT
                COUNT(*) as count,
                AVG(total_query_time_ms) as avg_query_time_ms,
                AVG(patterns_count) as avg_patterns_count,
                SUM(CASE WHEN is_fallback THEN 1 ELSE 0 END) as fallbacks
            FROM agent_manifest_injections
            WHERE created_at > NOW() - INTERVAL %s
        """
        manifest_result = execute_query(manifest_query, params=(interval,))
        if manifest_result["success"] and manifest_result["rows"]:
            row = manifest_result["rows"][0]
            result["manifest_injections"] = {
                "count": row["count"] or 0,
                "avg_query_time_ms": round(float(row["avg_query_time_ms"] or 0), 1),
                "avg_patterns_count": round(float(row["avg_patterns_count"] or 0), 1),
                "fallbacks": row["fallbacks"] or 0,
            }

        # Routing decisions
        routing_query = """
            SELECT
                COUNT(*) as count,
                AVG(routing_time_ms) as avg_routing_time_ms,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL %s
        """
        routing_result = execute_query(routing_query, params=(interval,))
        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            result["routing_decisions"] = {
                "count": row["count"] or 0,
                "avg_routing_time_ms": round(float(row["avg_routing_time_ms"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2),
            }

        # Agent actions
        actions_query = """
            SELECT
                action_type,
                COUNT(*) as count
            FROM agent_actions
            WHERE created_at > NOW() - INTERVAL %s
            GROUP BY action_type
        """
        actions_result = execute_query(actions_query, params=(interval,))
        if actions_result["success"]:
            actions = {
                row["action_type"]: row["count"] for row in actions_result["rows"]
            }
            result["agent_actions"] = {
                "tool_calls": actions.get("tool_call", 0),
                "decisions": actions.get("decision", 0),
                "errors": actions.get("error", 0),
                "successes": actions.get("success", 0),
            }

        # Recent errors if requested
        if args.include_errors:
            errors_query = """
                SELECT
                    agent_name,
                    action_details->>'error' as error,
                    created_at
                FROM agent_actions
                WHERE action_type = 'error'
                AND created_at > NOW() - INTERVAL %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            errors_result = execute_query(errors_query, params=(interval, args.limit))
            if errors_result["success"]:
                result["recent_errors"] = [
                    {
                        "agent": row["agent_name"],
                        "error": row["error"],
                        "time": str(row["created_at"]),
                    }
                    for row in errors_result["rows"]
                ]

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

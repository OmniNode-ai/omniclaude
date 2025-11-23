#!/usr/bin/env python3
"""
Skill: check-agent-performance
Purpose: Check agent routing and execution performance metrics

Description:
    Analyzes agent routing decisions, execution metrics, and transformation
    statistics over a specified timeframe. Provides insights into routing
    efficiency, confidence scores, and agent usage patterns.

Usage:
    python3 execute.py [--timeframe TIMEFRAME] [--top-agents N]

    Options:
        --timeframe TIMEFRAME    Time period to analyze (5m, 15m, 1h, 24h, 7d)
                                Default: 1h
        --top-agents N           Number of top agents to display
                                Default: 10

Output:
    JSON object with the following structure:
    {
        "timeframe": "1h",
        "routing": {
            "total_decisions": 142,
            "avg_routing_time_ms": 7.8,
            "avg_confidence": 0.92,
            "threshold_violations": 2
        },
        "top_agents": [
            {
                "agent": "agent-api",
                "count": 45,
                "avg_confidence": 0.94
            }
        ],
        "transformations": {
            "total": 12,
            "success_rate": 0.92,
            "avg_duration_ms": 1842.5
        }
    }

Exit Codes:
    0: Healthy - all systems nominal
    1: Degraded - performance issues detected (threshold violations)
    2: Critical - cannot fetch metrics or database error

Examples:
    # Check last hour of performance (default)
    python3 execute.py

    # Check last 24 hours
    python3 execute.py --timeframe 24h

    # Check last 5 minutes with top 5 agents
    python3 execute.py --timeframe 5m --top-agents 5

Created: 2025-11-12
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from db_helper import execute_query
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)

try:
    from timeframe_helper import parse_timeframe
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def validate_limit(value):
    """Validate LIMIT value to prevent SQL injection and DoS attacks.

    Args:
        value: String value from argparse

    Returns:
        int: Validated integer value (1-100)

    Raises:
        argparse.ArgumentTypeError: If value is outside valid range
    """
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer: {value}")

    if not (1 <= ivalue <= 100):
        raise argparse.ArgumentTypeError(
            f"Value must be between 1 and 100 (got {ivalue})"
        )

    return ivalue


def main():
    parser = argparse.ArgumentParser(description="Check agent performance")
    parser.add_argument(
        "--timeframe", default="1h", help="Time period (5m, 15m, 1h, 24h, 7d)"
    )
    parser.add_argument(
        "--top-agents",
        type=validate_limit,
        default=10,
        help="Number of top agents (1-100, default: 10)",
    )
    args = parser.parse_args()

    # Validate timeframe (SQL injection protection)
    try:
        interval = parse_timeframe(args.timeframe)
    except ValueError as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1

    try:
        result = {"timeframe": args.timeframe}

        # Get routing statistics
        routing_query = """
            SELECT
                COUNT(*) as total_decisions,
                AVG(routing_time_ms) as avg_routing_time_ms,
                AVG(confidence_score) as avg_confidence,
                COUNT(CASE WHEN routing_time_ms > 100 THEN 1 END) as threshold_violations
            FROM agent_routing_decisions
            WHERE created_at > NOW() - %s::interval
        """
        routing_result = execute_query(routing_query, (interval,))

        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            result["routing"] = {
                "total_decisions": row["total_decisions"] or 0,
                "avg_routing_time_ms": round(float(row["avg_routing_time_ms"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2),
                "threshold_violations": row["threshold_violations"] or 0,
            }
        else:
            result["routing_error"] = routing_result.get("error", "Unknown error")
            result["routing_query_failed"] = True

        # Get top agents
        top_agents_query = """
            SELECT
                selected_agent as agent,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - %s::interval
            GROUP BY selected_agent
            ORDER BY count DESC
            LIMIT %s
        """
        top_result = execute_query(top_agents_query, (interval, args.top_agents))

        if top_result["success"]:
            result["top_agents"] = [
                {
                    "agent": row["agent"],
                    "count": row["count"],
                    "avg_confidence": round(float(row["avg_confidence"]), 2),
                }
                for row in top_result["rows"]
            ]
        else:
            result["top_agents_error"] = top_result.get("error", "Unknown error")
            result["top_agents_query_failed"] = True

        # Get transformation stats
        transform_query = """
            SELECT
                COUNT(*) as total,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate,
                AVG(transformation_duration_ms) as avg_duration_ms
            FROM agent_transformation_events
            WHERE started_at > NOW() - %s::interval
        """
        transform_result = execute_query(transform_query, (interval,))

        if transform_result["success"] and transform_result["rows"]:
            row = transform_result["rows"][0]
            result["transformations"] = {
                "total": row["total"] or 0,
                "success_rate": round(float(row["success_rate"] or 0), 2),
                "avg_duration_ms": round(float(row["avg_duration_ms"] or 0), 1),
            }
        else:
            result["transformations_error"] = transform_result.get(
                "error", "Unknown error"
            )
            result["transformations_query_failed"] = True

        # Add success and timestamp to response
        result["success"] = True
        result["timestamp"] = datetime.now(timezone.utc).isoformat()

        print(format_json(result))

        # Evaluate health status based on metrics
        # Critical: Can't fetch core metrics
        if not routing_result.get("success") or not top_result.get("success"):
            return 2

        # Degraded: Performance issues detected
        if result.get("routing", {}).get("threshold_violations", 0) > 0:
            return 1

        # Healthy: All systems nominal
        return 0

    except Exception as e:
        print(
            format_json(
                {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())

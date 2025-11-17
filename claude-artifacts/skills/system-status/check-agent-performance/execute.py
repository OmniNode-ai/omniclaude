#!/usr/bin/env python3
"""
Check Agent Performance - Agent routing and execution metrics

Usage:
    python3 execute.py [--timeframe 1h] [--top-agents 10]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from db_helper import execute_query
    from status_formatter import format_json
    from timeframe_helper import parse_timeframe
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check agent performance")
    parser.add_argument(
        "--timeframe", default="1h", help="Time period (5m, 15m, 1h, 24h, 7d)"
    )
    parser.add_argument(
        "--top-agents", type=int, default=10, help="Number of top agents (1-100)"
    )
    args = parser.parse_args()

    # Validate --top-agents parameter
    if args.top_agents <= 0:
        print(
            format_json(
                {
                    "success": False,
                    "error": f"top_agents must be positive (got {args.top_agents})",
                }
            )
        )
        return 1

    if args.top_agents > 100:
        print(
            format_json(
                {
                    "success": False,
                    "error": f"top_agents must be <= 100 (got {args.top_agents})",
                }
            )
        )
        return 1

    # Validate and parse timeframe
    try:
        interval = parse_timeframe(args.timeframe)
    except ValueError as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1

    try:
        result = {"timeframe": args.timeframe}

        # Get routing statistics
        routing_query = f"""
            SELECT
                COUNT(*) as total_decisions,
                AVG(routing_time_ms) as avg_routing_time_ms,
                AVG(confidence_score) as avg_confidence,
                COUNT(CASE WHEN routing_time_ms > 100 THEN 1 END) as threshold_violations
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        routing_result = execute_query(routing_query)

        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            result["routing"] = {
                "total_decisions": row["total_decisions"] or 0,
                "avg_routing_time_ms": round(float(row["avg_routing_time_ms"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2),
                "threshold_violations": row["threshold_violations"] or 0,
            }

        # Get top agents
        top_agents_query = f"""
            SELECT
                selected_agent as agent,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '{interval}'
            GROUP BY selected_agent
            ORDER BY count DESC
            LIMIT {args.top_agents}
        """
        top_result = execute_query(top_agents_query)

        if top_result["success"]:
            result["top_agents"] = [
                {
                    "agent": row["agent"],
                    "count": row["count"],
                    "avg_confidence": round(float(row["avg_confidence"]), 2),
                }
                for row in top_result["rows"]
            ]

        # Get transformation stats
        transform_query = f"""
            SELECT
                COUNT(*) as total,
                AVG(CASE WHEN success THEN 1.0 ELSE 0.0 END) as success_rate,
                AVG(transformation_duration_ms) as avg_duration_ms
            FROM agent_transformation_events
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        transform_result = execute_query(transform_query)

        if transform_result["success"] and transform_result["rows"]:
            row = transform_result["rows"][0]
            result["transformations"] = {
                "total": row["total"] or 0,
                "success_rate": round(float(row["success_rate"] or 0), 2),
                "avg_duration_ms": round(float(row["avg_duration_ms"] or 0), 1),
            }

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

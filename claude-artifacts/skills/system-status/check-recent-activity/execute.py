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
    from db_helper import execute_query
    from status_formatter import format_json
    from timeframe_helper import parse_timeframe
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Check recent activity")
    parser.add_argument("--limit", type=int, default=20, help="Number of records")
    parser.add_argument("--since", default="5m", help="Time period")
    parser.add_argument("--include-errors", action="store_true", help="Include errors")
    args = parser.parse_args()

    interval = parse_timeframe(args.since, default="5 minutes")
    result = {"timeframe": args.since}

    try:
        # Manifest injections
        manifest_query = f"""
            SELECT
                COUNT(*) as count,
                AVG(total_query_time_ms) as avg_query_time_ms,
                AVG(patterns_count) as avg_patterns_count,
                SUM(CASE WHEN is_fallback THEN 1 ELSE 0 END) as fallbacks
            FROM agent_manifest_injections
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        manifest_result = execute_query(manifest_query)
        if manifest_result["success"] and manifest_result["rows"]:
            row = manifest_result["rows"][0]
            result["manifest_injections"] = {
                "count": row["count"] or 0,
                "avg_query_time_ms": round(float(row["avg_query_time_ms"] or 0), 1),
                "avg_patterns_count": round(float(row["avg_patterns_count"] or 0), 1),
                "fallbacks": row["fallbacks"] or 0,
            }

        # Routing decisions
        routing_query = f"""
            SELECT
                COUNT(*) as count,
                AVG(routing_time_ms) as avg_routing_time_ms,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        routing_result = execute_query(routing_query)
        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            result["routing_decisions"] = {
                "count": row["count"] or 0,
                "avg_routing_time_ms": round(float(row["avg_routing_time_ms"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2),
            }

        # Agent actions
        actions_query = f"""
            SELECT
                action_type,
                COUNT(*) as count
            FROM agent_actions
            WHERE created_at > NOW() - INTERVAL '{interval}'
            GROUP BY action_type
        """
        actions_result = execute_query(actions_query)
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
            errors_query = f"""
                SELECT
                    agent_name,
                    action_details->>'error' as error,
                    created_at
                FROM agent_actions
                WHERE action_type = 'error'
                AND created_at > NOW() - INTERVAL '{interval}'
                ORDER BY created_at DESC
                LIMIT {args.limit}
            """
            errors_result = execute_query(errors_query)
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

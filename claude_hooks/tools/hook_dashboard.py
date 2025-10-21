#!/usr/bin/env python3
"""
Hook Intelligence Dashboard
Real-time view of Claude Code hook system activity
"""

import json
import os
from typing import Any, Dict, List

import psycopg2


class HookDashboard:
    """Simple dashboard for hook intelligence data"""

    def __init__(self, db_password: str | None = None):
        # Read from environment variable, fallback to dev default
        password = db_password or os.getenv(
            "DB_PASSWORD", "omninode-bridge-postgres-dev-2024"
        )
        self.conn_string = (
            f"host=localhost port=5436 dbname=omninode_bridge "
            f"user=postgres password={password}"
        )

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(self.conn_string)

    def recent_agent_detections(
        self, hours: int = 24, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent agent detections"""
        query = """
        SELECT
            created_at,
            payload->>'agent_detected' as agent,
            payload->>'agent_domain' as domain,
            payload->>'prompt_preview' as prompt,
            payload->>'detection_method' as method,
            payload->>'confidence' as confidence
        FROM hook_events
        WHERE source = 'UserPromptSubmit'
          AND created_at > NOW() - INTERVAL '%s hours'
        ORDER BY created_at DESC
        LIMIT %s
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (hours, limit))
                rows = cur.fetchall()
                return [
                    {
                        "time": row[0],
                        "agent": row[1],
                        "domain": row[2],
                        "prompt": row[3][:80] + "..." if row[3] else None,
                        "method": row[4],
                        "confidence": row[5],
                    }
                    for row in rows
                ]

    def tool_usage_by_agent(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Get tool usage patterns by agent"""
        query = """
        SELECT
            u.payload->>'agent_detected' as agent,
            post.resource_id as tool,
            COUNT(*) as usage_count,
            AVG(EXTRACT(EPOCH FROM (post.created_at - pre.created_at)) * 1000) as avg_duration_ms
        FROM hook_events u
        LEFT JOIN hook_events pre
            ON u.metadata->>'correlation_id' = pre.metadata->>'correlation_id'
            AND pre.source = 'PreToolUse'
        LEFT JOIN hook_events post
            ON u.metadata->>'correlation_id' = post.metadata->>'correlation_id'
            AND post.source = 'PostToolUse'
        WHERE u.source = 'UserPromptSubmit'
          AND u.created_at > NOW() - INTERVAL '%s hours'
          AND post.resource_id IS NOT NULL
        GROUP BY agent, tool
        ORDER BY usage_count DESC
        LIMIT 20
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (hours,))
                rows = cur.fetchall()
                return [
                    {
                        "agent": row[0] or "no_agent",
                        "tool": row[1],
                        "count": row[2],
                        "avg_ms": round(float(row[3]), 2) if row[3] else 0,
                    }
                    for row in rows
                ]

    def hook_performance_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Get hook performance statistics"""
        query = """
        SELECT
            source,
            COUNT(*) as events,
            MIN(created_at) as first_event,
            MAX(created_at) as last_event
        FROM hook_events
        WHERE created_at > NOW() - INTERVAL '%s hours'
        GROUP BY source
        ORDER BY events DESC
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (hours,))
                rows = cur.fetchall()
                return {
                    row[0]: {"events": row[1], "first": row[2], "last": row[3]}
                    for row in rows
                }

    def correlation_trace(self, correlation_id: str) -> Dict[str, Any]:
        """Get full correlation trace for a request"""
        query = """
        SELECT
            source,
            action,
            resource_id,
            payload,
            metadata,
            created_at
        FROM hook_events
        WHERE metadata->>'correlation_id' = %s
        ORDER BY created_at ASC
        """

        with self.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (correlation_id,))
                rows = cur.fetchall()
                return {
                    "correlation_id": correlation_id,
                    "events": [
                        {
                            "source": row[0],
                            "action": row[1],
                            "resource_id": row[2],
                            "payload": row[3],
                            "metadata": row[4],
                            "time": row[5],
                        }
                        for row in rows
                    ],
                }

    def print_dashboard(self):
        """Print formatted dashboard"""
        print("\n" + "=" * 80)
        print("Claude Code Hook Intelligence Dashboard")
        print("=" * 80)

        # Performance stats
        print("\n📊 Hook Performance (Last 24 Hours)")
        print("-" * 80)
        stats = self.hook_performance_stats()
        if stats:
            for source, data in stats.items():
                print(
                    f"{source:20} {data['events']:5} events  "
                    f"(First: {data['first'].strftime('%H:%M:%S')}  "
                    f"Last: {data['last'].strftime('%H:%M:%S')})"
                )
        else:
            print("No events found")

        # Agent detections
        print("\n🤖 Recent Agent Detections (Last 10)")
        print("-" * 80)
        detections = self.recent_agent_detections()
        if detections:
            for d in detections:
                time_str = d["time"].strftime("%H:%M:%S")
                agent = d["agent"] or "no_agent"
                method = d["method"] or "unknown"
                conf = d["confidence"] or "N/A"
                print(f"{time_str}  {agent:30}  {method:12}  conf:{conf}")
                if d["prompt"]:
                    print(f"         Prompt: {d['prompt']}")
        else:
            print("No agent detections found")

        # Tool usage
        print("\n🔧 Tool Usage by Agent (Top 10)")
        print("-" * 80)
        usage = self.tool_usage_by_agent()
        if usage:
            print(f"{'Agent':<30} {'Tool':<15} {'Count':<8} {'Avg ms':<10}")
            print("-" * 80)
            for u in usage[:10]:
                print(
                    f"{u['agent']:<30} {u['tool']:<15} {u['count']:<8} {u['avg_ms']:<10}"
                )
        else:
            print("No tool usage found")

        print("\n" + "=" * 80)


if __name__ == "__main__":
    import sys

    dashboard = HookDashboard()

    if len(sys.argv) > 1 and sys.argv[1] == "trace":
        # Show correlation trace
        if len(sys.argv) < 3:
            print("Usage: hook_dashboard.py trace <correlation_id>")
            sys.exit(1)

        trace = dashboard.correlation_trace(sys.argv[2])
        print(json.dumps(trace, indent=2, default=str))
    else:
        # Show dashboard
        dashboard.print_dashboard()

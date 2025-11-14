#!/usr/bin/env python3
"""
Generate Status Report - Comprehensive system status report

Usage:
    python3 execute.py [--format json|markdown|text] [--output file] [--include-trends]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from docker_helper import list_containers, get_container_status
    from kafka_helper import check_kafka_connection, list_topics
    from qdrant_helper import get_all_collections_stats
    from db_helper import execute_query
    from status_formatter import (
        format_json, format_markdown_table, format_status_indicator,
        format_timestamp, generate_markdown_report
    )
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def parse_timeframe(timeframe: str) -> str:
    """Convert timeframe to PostgreSQL interval."""
    mapping = {
        "1h": "1 hour",
        "24h": "24 hours",
        "7d": "7 days"
    }
    return mapping.get(timeframe, "24 hours")


def collect_report_data(timeframe: str, include_trends: bool):
    """Collect all data for the report."""
    interval = parse_timeframe(timeframe)
    data = {
        "generated": format_timestamp(),
        "timeframe": timeframe
    }

    # Service status
    containers = list_containers()
    if containers["success"]:
        services_data = []
        for container in containers["containers"][:20]:  # Limit to 20 for report
            status = get_container_status(container["name"])
            services_data.append({
                "name": container["name"],
                "status": status.get("status", "unknown"),
                "health": status.get("health", "unknown"),
                "restart_count": status.get("restart_count", 0)
            })
        data["services"] = services_data

    # Infrastructure
    kafka = check_kafka_connection()
    topics = list_topics()
    postgres_test = execute_query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'")
    qdrant_stats = get_all_collections_stats()

    data["infrastructure"] = {
        "kafka": {
            "status": kafka.get("status"),
            "topics": topics.get("count", 0) if topics["success"] else 0
        },
        "postgres": {
            "status": "connected" if postgres_test["success"] else "failed",
            "tables": postgres_test["rows"][0]["count"] if postgres_test["success"] else 0
        },
        "qdrant": {
            "status": "connected" if qdrant_stats["success"] else "failed",
            "total_vectors": qdrant_stats.get("total_vectors", 0)
        }
    }

    # Performance metrics
    try:
        routing_query = f"""
            SELECT
                COUNT(*) as total,
                AVG(routing_time_ms) as avg_time,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        routing_result = execute_query(routing_query)

        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            data["performance"] = {
                "routing_decisions": row["total"] or 0,
                "avg_routing_time_ms": round(float(row["avg_time"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2)
            }
    except Exception:
        data["performance"] = {}

    # Recent activity
    try:
        manifest_query = f"""
            SELECT COUNT(*) as count
            FROM agent_manifest_injections
            WHERE created_at > NOW() - INTERVAL '{interval}'
        """
        manifest_result = execute_query(manifest_query)

        data["recent_activity"] = {
            "agent_executions": manifest_result["rows"][0]["count"] if manifest_result["success"] else 0
        }
    except Exception:
        data["recent_activity"] = {}

    # Top agents
    try:
        top_agents_query = f"""
            SELECT
                selected_agent,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '{interval}'
            GROUP BY selected_agent
            ORDER BY count DESC
            LIMIT 10
        """
        top_result = execute_query(top_agents_query)

        if top_result["success"]:
            data["top_agents"] = [
                {
                    "agent": row["selected_agent"],
                    "count": row["count"],
                    "avg_confidence": round(float(row["avg_confidence"]), 2)
                }
                for row in top_result["rows"]
            ]
    except Exception:
        data["top_agents"] = []

    return data


def generate_markdown_output(data: dict) -> str:
    """Generate Markdown format report."""
    sections = []

    # Executive summary
    services_running = sum(1 for s in data.get("services", []) if s["status"] == "running")
    services_total = len(data.get("services", []))
    perf = data.get("performance", {})

    summary = f"""**Generated**: {data['generated']}
**Timeframe**: {data['timeframe']}

## Executive Summary

- **Services Running**: {services_running}/{services_total}
- **Agent Executions**: {data.get('recent_activity', {}).get('agent_executions', 0)}
- **Routing Decisions**: {perf.get('routing_decisions', 0)}
- **Average Confidence**: {int(perf.get('avg_confidence', 0) * 100)}%
"""
    sections.append({"title": "Overview", "content": summary})

    # Services table
    if data.get("services"):
        services_rows = []
        for service in data["services"]:
            indicator = format_status_indicator(service["status"])
            services_rows.append([
                service["name"],
                f"{indicator} {service['status']}",
                service.get("health", "unknown"),
                service.get("restart_count", 0)
            ])

        sections.append({
            "title": "Service Health",
            "table": {
                "headers": ["Service", "Status", "Health", "Restarts"],
                "rows": services_rows
            }
        })

    # Infrastructure
    if data.get("infrastructure"):
        infra = data["infrastructure"]
        infra_rows = [
            ["Kafka", format_status_indicator(infra["kafka"]["status"]), f"{infra['kafka']['topics']} topics"],
            ["PostgreSQL", format_status_indicator(infra["postgres"]["status"]), f"{infra['postgres']['tables']} tables"],
            ["Qdrant", format_status_indicator(infra["qdrant"]["status"]), f"{infra['qdrant']['total_vectors']} vectors"]
        ]

        sections.append({
            "title": "Infrastructure",
            "table": {
                "headers": ["Component", "Status", "Details"],
                "rows": infra_rows
            }
        })

    # Top agents
    if data.get("top_agents"):
        agents_rows = []
        for agent in data["top_agents"]:
            agents_rows.append([
                agent["agent"],
                agent["count"],
                f"{int(agent['avg_confidence'] * 100)}%"
            ])

        sections.append({
            "title": "Top Agents",
            "table": {
                "headers": ["Agent", "Count", "Avg Confidence"],
                "rows": agents_rows
            }
        })

    return generate_markdown_report("System Status Report", sections)


def main():
    parser = argparse.ArgumentParser(description="Generate system status report")
    parser.add_argument("--format", choices=["json", "markdown", "text"], default="json",
                      help="Output format")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--include-trends", action="store_true", help="Include trend analysis")
    parser.add_argument("--timeframe", default="24h", help="Data timeframe (1h, 24h, 7d)")
    args = parser.parse_args()

    try:
        # Collect data
        data = collect_report_data(args.timeframe, args.include_trends)

        # Format output
        if args.format == "markdown":
            output = generate_markdown_output(data)
        elif args.format == "text":
            output = generate_markdown_output(data)  # Use markdown as base for text
        else:
            output = format_json(data)

        # Write to file or stdout
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Report written to: {args.output}")
        else:
            print(output)

        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

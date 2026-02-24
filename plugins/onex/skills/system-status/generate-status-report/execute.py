#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

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
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from constants import (
        DEFAULT_TOP_AGENTS,
        MAX_CONTAINERS_DISPLAY,
        MIN_DIVISOR,
        PERCENT_MULTIPLIER,
    )
    from db_helper import execute_query
    from docker_helper import get_container_status, list_containers
    from kafka_helper import check_kafka_connection, list_topics
    from qdrant_helper import get_all_collections_stats
    from status_formatter import (
        format_json,
        format_status_indicator,
        format_timestamp,
        generate_markdown_report,
    )
    from timeframe_helper import parse_timeframe
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def collect_report_data(timeframe: str, include_trends: bool) -> dict[str, Any]:
    """Collect all data for the report.

    Args:
        timeframe: Time period for the report (e.g., '24h', '7d')
        include_trends: Whether to include trend analysis

    Returns:
        Dictionary containing all report data
    """
    interval = parse_timeframe(timeframe)
    data = {
        "generated": format_timestamp(),
        "timeframe": timeframe,
        "trends_enabled": include_trends,
    }

    # Service status
    containers = list_containers()
    if containers["success"]:
        services_data = []
        for container in containers["containers"][:MAX_CONTAINERS_DISPLAY]:
            status = get_container_status(container["name"])
            services_data.append(
                {
                    "name": container["name"],
                    "status": status.get("status", "unknown"),
                    "health": status.get("health", "unknown"),
                    "restart_count": status.get("restart_count", 0),
                }
            )
        data["services"] = services_data

    # Infrastructure
    kafka = check_kafka_connection()
    topics = list_topics()
    postgres_test = execute_query(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
    )
    qdrant_stats = get_all_collections_stats()

    data["infrastructure"] = {
        "kafka": {
            "status": kafka.get("status"),
            "topics": topics.get("count", 0) if topics["success"] else 0,
        },
        "postgres": {
            "status": "connected" if postgres_test["success"] else "failed",
            "tables": (
                postgres_test["rows"][0]["count"] if postgres_test["success"] else 0
            ),
        },
        "qdrant": {
            "status": "connected" if qdrant_stats["success"] else "failed",
            "total_vectors": qdrant_stats.get("total_vectors", 0),
        },
    }

    # Performance metrics
    try:
        routing_query = """
            SELECT
                COUNT(*) as total,
                AVG(routing_time_ms) as avg_time,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - %s::INTERVAL
        """
        routing_result = execute_query(routing_query, params=(interval,))

        if routing_result["success"] and routing_result["rows"]:
            row = routing_result["rows"][0]
            data["performance"] = {
                "routing_decisions": row["total"] or 0,
                "avg_routing_time_ms": round(float(row["avg_time"] or 0), 1),
                "avg_confidence": round(float(row["avg_confidence"] or 0), 2),
            }
    except Exception:
        data["performance"] = {}

    # Recent activity
    try:
        manifest_query = """
            SELECT COUNT(*) as count
            FROM agent_manifest_injections
            WHERE created_at > NOW() - %s::INTERVAL
        """
        manifest_result = execute_query(manifest_query, params=(interval,))

        data["recent_activity"] = {
            "agent_executions": (
                manifest_result["rows"][0]["count"] if manifest_result["success"] else 0
            )
        }
    except Exception:
        data["recent_activity"] = {}

    # Top agents
    try:
        top_agents_query = """
            SELECT
                selected_agent,
                COUNT(*) as count,
                AVG(confidence_score) as avg_confidence
            FROM agent_routing_decisions
            WHERE created_at > NOW() - %s::INTERVAL
            GROUP BY selected_agent
            ORDER BY count DESC
            LIMIT %s
        """
        top_result = execute_query(
            top_agents_query, params=(interval, DEFAULT_TOP_AGENTS)
        )

        if top_result["success"]:
            data["top_agents"] = [
                {
                    "agent": row["selected_agent"],
                    "count": row["count"],
                    "avg_confidence": round(float(row["avg_confidence"]), 2),
                }
                for row in top_result["rows"]
            ]
    except Exception:
        data["top_agents"] = []

    # Trend analysis (if enabled)
    if include_trends:
        try:
            # Compare current period with previous period
            trend_query = """
                WITH current_period AS (
                    SELECT
                        COUNT(*) as decisions,
                        AVG(routing_time_ms) as avg_time,
                        AVG(confidence_score) as avg_confidence
                    FROM agent_routing_decisions
                    WHERE created_at > NOW() - %s::INTERVAL
                ),
                previous_period AS (
                    SELECT
                        COUNT(*) as decisions,
                        AVG(routing_time_ms) as avg_time,
                        AVG(confidence_score) as avg_confidence
                    FROM agent_routing_decisions
                    WHERE created_at BETWEEN NOW() - %s::INTERVAL * 2
                        AND NOW() - %s::INTERVAL
                )
                SELECT
                    c.decisions as current_decisions,
                    p.decisions as previous_decisions,
                    c.avg_time as current_avg_time,
                    p.avg_time as previous_avg_time,
                    c.avg_confidence as current_avg_confidence,
                    p.avg_confidence as previous_avg_confidence
                FROM current_period c, previous_period p
            """
            trend_result = execute_query(
                trend_query, params=(interval, interval, interval)
            )

            if trend_result["success"] and trend_result["rows"]:
                row = trend_result["rows"][0]
                curr_dec = row["current_decisions"] or 0
                prev_dec = (
                    row["previous_decisions"] or MIN_DIVISOR
                )  # Avoid division by zero
                curr_time = float(row["current_avg_time"] or 0)
                prev_time = float(row["previous_avg_time"] or MIN_DIVISOR)
                curr_conf = float(row["current_avg_confidence"] or 0)
                prev_conf = float(row["previous_avg_confidence"] or MIN_DIVISOR)

                data["trends"] = {
                    "decisions_change_pct": round(
                        ((curr_dec - prev_dec) / prev_dec) * PERCENT_MULTIPLIER, 1
                    ),
                    "routing_time_change_pct": round(
                        ((curr_time - prev_time) / prev_time) * PERCENT_MULTIPLIER, 1
                    ),
                    "confidence_change_pct": round(
                        ((curr_conf - prev_conf) / prev_conf) * PERCENT_MULTIPLIER, 1
                    ),
                }
        except Exception as e:
            data["trends"] = {"error": str(e)}

    return data


def generate_markdown_output(data: dict) -> str:
    """Generate Markdown format report."""
    sections = []

    # Executive summary (timestamp added by generate_markdown_report)
    services_running = sum(
        1 for s in data.get("services", []) if s["status"] == "running"
    )
    services_total = len(data.get("services", []))
    perf = data.get("performance", {})

    summary = f"""**Timeframe**: {data["timeframe"]}

- **Services Running**: {services_running}/{services_total}
- **Agent Executions**: {data.get("recent_activity", {}).get("agent_executions", 0)}
- **Routing Decisions**: {perf.get("routing_decisions", 0)}
- **Average Confidence**: {int(perf.get("avg_confidence", 0) * PERCENT_MULTIPLIER)}%
"""
    sections.append({"title": "Executive Summary", "content": summary})

    # Services table
    if data.get("services"):
        services_rows = []
        for service in data["services"]:
            indicator = format_status_indicator(service["status"])
            services_rows.append(
                [
                    service["name"],
                    f"{indicator} {service['status']}",
                    service.get("health", "unknown"),
                    service.get("restart_count", 0),
                ]
            )

        sections.append(
            {
                "title": "Service Health",
                "table": {
                    "headers": ["Service", "Status", "Health", "Restarts"],
                    "rows": services_rows,
                },
            }
        )

    # Infrastructure
    if data.get("infrastructure"):
        infra = data["infrastructure"]
        infra_rows = [
            [
                "Kafka",
                format_status_indicator(infra["kafka"]["status"]),
                f"{infra['kafka']['topics']} topics",
            ],
            [
                "PostgreSQL",
                format_status_indicator(infra["postgres"]["status"]),
                f"{infra['postgres']['tables']} tables",
            ],
            [
                "Qdrant",
                format_status_indicator(infra["qdrant"]["status"]),
                f"{infra['qdrant']['total_vectors']} vectors",
            ],
        ]

        sections.append(
            {
                "title": "Infrastructure",
                "table": {
                    "headers": ["Component", "Status", "Details"],
                    "rows": infra_rows,
                },
            }
        )

    # Top agents
    if data.get("top_agents"):
        agents_rows = []
        for agent in data["top_agents"]:
            agents_rows.append(
                [
                    agent["agent"],
                    agent["count"],
                    f"{int(agent['avg_confidence'] * PERCENT_MULTIPLIER)}%",
                ]
            )

        sections.append(
            {
                "title": "Top Agents",
                "table": {
                    "headers": ["Agent", "Count", "Avg Confidence"],
                    "rows": agents_rows,
                },
            }
        )

    # Trends (if enabled)
    if data.get("trends") and "error" not in data["trends"]:
        trends = data["trends"]
        trends_content = f"""**Comparison with Previous Period**:

- **Routing Decisions**: {trends["decisions_change_pct"]:+.1f}% change
- **Average Routing Time**: {trends["routing_time_change_pct"]:+.1f}% change
- **Average Confidence**: {trends["confidence_change_pct"]:+.1f}% change

*Positive values indicate increase, negative values indicate decrease*
"""
        sections.append({"title": "Trends Analysis", "content": trends_content})

    return generate_markdown_report("System Status Report", sections)


def main() -> int:
    """Generate comprehensive system status report.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(description="Generate system status report")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "text"],
        default="json",
        help="Output format",
    )
    parser.add_argument("--output", help="Output file path")
    parser.add_argument(
        "--include-trends", action="store_true", help="Include trend analysis"
    )
    parser.add_argument(
        "--timeframe", default="24h", help="Data timeframe (1h, 24h, 7d)"
    )
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

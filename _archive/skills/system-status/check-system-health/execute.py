#!/usr/bin/env python3
"""
Skill: check-system-health
Purpose: Fast overall system health snapshot

Description:
    Performs a comprehensive system health check including Docker services,
    infrastructure connectivity (Kafka, PostgreSQL, Qdrant), and recent
    activity metrics. Designed to complete in under 5 seconds for quick
    health assessment. Provides multiple output formats and determines
    overall system status.

Usage:
    python3 execute.py [--format FORMAT] [--verbose]

    Options:
        --format FORMAT         Output format: json, text, or summary
                               Default: json
        --verbose              Include detailed information for all components

Output:
    JSON object with the following structure:
    {
        "status": "healthy|degraded|critical",
        "timestamp": "2025-11-12T14:30:00Z",
        "check_duration_ms": 3542,
        "services": {
            "success": true,
            "total": 12,
            "running": 12,
            "stopped": 0,
            "unhealthy": 0,
            "healthy": 12
        },
        "infrastructure": {
            "kafka": {
                "status": "connected",
                "broker": "192.168.86.200:29092",
                "reachable": true,
                "topics": 15
            },
            "postgres": {
                "status": "connected",
                "host": "192.168.86.200:5436",
                "database": "omninode_bridge",
                "tables": 34
            },
            "qdrant": {
                "status": "connected",
                "url": "http://localhost:6333",
                "reachable": true,
                "collections": 4,
                "total_vectors": 15689
            }
        },
        "recent_activity": {
            "timeframe": "5m",
            "agent_executions": 12,
            "routing_decisions": 15,
            "agent_actions": 47
        },
        "issues": [],
        "recommendations": []
    }

Exit Codes:
    0: Success - all systems healthy
    1: Warning - system degraded with warnings
    2: Critical - system critical with errors
    3: Error - health check execution failed

Examples:
    # Quick health check (JSON output)
    python3 execute.py

    # Summary format for quick view
    python3 execute.py --format summary

    # Detailed text report
    python3 execute.py --format text --verbose

Created: 2025-11-12
"""

import argparse
import json
import sys
import time
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from db_helper import execute_query
    from docker_helper import get_service_summary
    from kafka_helper import check_kafka_connection, list_topics
    from qdrant_helper import check_qdrant_connection, get_all_collections_stats
    from status_formatter import format_json, format_status_indicator, format_timestamp
except ImportError as e:
    print(
        json.dumps(
            {
                "success": False,
                "error": f"Failed to import helpers: {e}",
                "hint": "Ensure _shared helpers are installed",
            }
        )
    )
    sys.exit(3)


def _calculate_service_summary(containers: list) -> dict:
    """
    Calculate service summary from container list.

    Args:
        containers: List of container dictionaries

    Returns:
        Dictionary with summary statistics
    """
    running = 0
    stopped = 0
    unhealthy = 0

    for container in containers:
        state = container.get("state", "").lower()
        status = container.get("status", "").lower()

        if state == "running":
            running += 1
            if "unhealthy" in status:
                unhealthy += 1
        else:
            stopped += 1

    return {
        "success": True,
        "total": len(containers),
        "running": running,
        "stopped": stopped,
        "unhealthy": unhealthy,
        "healthy": running - unhealthy,
        "error": None,
    }


def check_docker_services(verbose: bool = False) -> dict:
    """Check Docker services status."""
    try:
        # Call docker ps once and filter in memory
        from docker_helper import list_containers

        all_containers_result = list_containers()

        if not all_containers_result["success"]:
            return {
                "success": False,
                "error": all_containers_result.get(
                    "error", "Failed to list containers"
                ),
            }

        all_containers = all_containers_result["containers"]

        # Filter containers by name prefix in memory
        archon_containers = [
            c for c in all_containers if c["name"].startswith("archon-")
        ]
        omninode_containers = [
            c for c in all_containers if c["name"].startswith("omninode-")
        ]
        app_containers = [c for c in all_containers if "app" in c["name"]]

        # Calculate summaries
        all_services = _calculate_service_summary(all_containers)
        archon_services = _calculate_service_summary(archon_containers)
        omninode_services = _calculate_service_summary(omninode_containers)
        app_services = _calculate_service_summary(app_containers)

        return {
            "success": True,
            "total": all_services.get("total", 0),
            "running": all_services.get("running", 0),
            "stopped": all_services.get("stopped", 0),
            "unhealthy": all_services.get("unhealthy", 0),
            "healthy": all_services.get("healthy", 0),
            "details": {
                "archon": archon_services if verbose else None,
                "omninode": omninode_services if verbose else None,
                "app": app_services if verbose else None,
            },
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def check_infrastructure(verbose: bool = False) -> dict:
    """Check infrastructure components."""
    infrastructure = {}

    # Check Kafka
    try:
        kafka_conn = check_kafka_connection()
        kafka_topics = list_topics() if verbose else {"count": 0}

        infrastructure["kafka"] = {
            "status": kafka_conn.get("status", "unknown"),
            "broker": kafka_conn.get("broker", "unknown"),
            "reachable": kafka_conn.get("reachable", False),
            "topics": kafka_topics.get("count", 0) if verbose else None,
            "error": kafka_conn.get("error"),
        }
    except Exception as e:
        infrastructure["kafka"] = {"status": "error", "error": str(e)}

    # Check PostgreSQL
    try:
        postgres_result = execute_query(
            "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = 'public'"
        )
        if postgres_result["success"] and postgres_result["rows"]:
            table_count = postgres_result["rows"][0]["count"]
            infrastructure["postgres"] = {
                "status": "connected",
                "host": f"{postgres_result.get('host', 'unknown')}:{postgres_result.get('port', 'unknown')}",
                "database": postgres_result.get("database", "unknown"),
                "tables": table_count,
                "error": None,
            }
        else:
            infrastructure["postgres"] = {
                "status": "error",
                "error": postgres_result.get("error", "Unknown error"),
            }
    except Exception as e:
        infrastructure["postgres"] = {"status": "error", "error": str(e)}

    # Check Qdrant
    try:
        qdrant_conn = check_qdrant_connection()
        qdrant_stats = (
            get_all_collections_stats()
            if verbose
            else {"collection_count": 0, "total_vectors": 0}
        )

        infrastructure["qdrant"] = {
            "status": qdrant_conn.get("status", "unknown"),
            "url": qdrant_conn.get("url", "unknown"),
            "reachable": qdrant_conn.get("reachable", False),
            "collections": qdrant_stats.get("collection_count", 0) if verbose else None,
            "total_vectors": qdrant_stats.get("total_vectors", 0) if verbose else None,
            "error": qdrant_conn.get("error"),
        }
    except Exception as e:
        infrastructure["qdrant"] = {"status": "error", "error": str(e)}

    return infrastructure


def check_recent_activity() -> dict:
    """Check recent activity (last 5 minutes)."""
    activity = {
        "timeframe": "5m",
        "agent_executions": 0,
        "routing_decisions": 0,
        "agent_actions": 0,
    }

    try:
        # Check manifest injections
        manifest_result = execute_query(
            "SELECT COUNT(*) as count FROM agent_manifest_injections WHERE created_at > NOW() - %s::interval",
            ("5 minutes",),
        )
        if manifest_result["success"] and manifest_result["rows"]:
            activity["agent_executions"] = manifest_result["rows"][0]["count"]

        # Check routing decisions
        routing_result = execute_query(
            "SELECT COUNT(*) as count FROM agent_routing_decisions WHERE created_at > NOW() - %s::interval",
            ("5 minutes",),
        )
        if routing_result["success"] and routing_result["rows"]:
            activity["routing_decisions"] = routing_result["rows"][0]["count"]

        # Check agent actions
        actions_result = execute_query(
            "SELECT COUNT(*) as count FROM agent_actions WHERE created_at > NOW() - %s::interval",
            ("5 minutes",),
        )
        if actions_result["success"] and actions_result["rows"]:
            activity["agent_actions"] = actions_result["rows"][0]["count"]
    except Exception:
        # Silently fail - activity is optional
        pass

    return activity


def determine_overall_status(services: dict, infrastructure: dict) -> tuple:
    """
    Determine overall system status.

    Returns:
        Tuple of (status_string, issues_list, recommendations_list)
    """
    issues = []
    recommendations = []

    # Check services
    if not services.get("success"):
        issues.append(
            {
                "severity": "critical",
                "component": "docker",
                "issue": "Failed to check Docker services",
                "details": services.get("error", "Unknown error"),
            }
        )
    elif services.get("stopped", 0) > 0:
        issues.append(
            {
                "severity": "critical",
                "component": "docker",
                "issue": f"{services['stopped']} service(s) stopped",
                "details": f"{services['stopped']} containers are not running",
            }
        )
        recommendations.append(
            "Start stopped services with: docker start <container-name>"
        )
    elif services.get("unhealthy", 0) > 0:
        issues.append(
            {
                "severity": "warning",
                "component": "docker",
                "issue": f"{services['unhealthy']} service(s) unhealthy",
                "details": f"{services['unhealthy']} containers are running but unhealthy",
            }
        )
        recommendations.append("Check service logs with: docker logs <container-name>")

    # Check infrastructure
    for component, status in infrastructure.items():
        if status.get("status") in ["error", "unreachable", "timeout"]:
            issues.append(
                {
                    "severity": "critical",
                    "component": component,
                    "issue": f"{component.capitalize()} unreachable",
                    "details": status.get("error", "Connection failed"),
                }
            )
            if component == "kafka":
                recommendations.append(
                    "Check Kafka broker at: docker logs omninode-bridge-redpanda"
                )
            elif component == "postgres":
                recommendations.append("Verify PostgreSQL credentials in .env file")
            elif component == "qdrant":
                recommendations.append(
                    "Check Qdrant service: docker logs archon-qdrant"
                )

    # Determine status
    critical_count = sum(1 for issue in issues if issue["severity"] == "critical")
    warning_count = sum(1 for issue in issues if issue["severity"] == "warning")

    if critical_count > 0:
        return ("critical", issues, recommendations)
    elif warning_count > 0:
        return ("degraded", issues, recommendations)
    else:
        return ("healthy", issues, recommendations)


def format_output(data: dict, format_type: str) -> str:
    """Format output based on requested format."""
    if format_type == "json":
        return format_json(data, pretty=True)
    elif format_type == "summary":
        # Brief summary format
        status = data.get("status", "unknown")
        indicator = format_status_indicator(status)
        services = data.get("services", {})
        issues = data.get("issues", [])

        lines = [
            f"{indicator} System Status: {status.upper()}",
            f"  Services: {services.get('running', 0)}/{services.get('total', 0)} running",
            f"  Issues: {len(issues)}",
            f"  Duration: {data.get('check_duration_ms', 0)}ms",
        ]
        return "\n".join(lines)
    else:  # text format
        lines = [
            "=" * 60,
            "SYSTEM HEALTH CHECK",
            "=" * 60,
            f"Status: {data.get('status', 'unknown').upper()}",
            f"Timestamp: {data.get('timestamp', 'unknown')}",
            f"Duration: {data.get('check_duration_ms', 0)}ms",
            "",
            "Services:",
            f"  Running: {data.get('services', {}).get('running', 0)}/{data.get('services', {}).get('total', 0)}",
            f"  Unhealthy: {data.get('services', {}).get('unhealthy', 0)}",
            "",
            "Infrastructure:",
        ]

        for component, status in data.get("infrastructure", {}).items():
            indicator = format_status_indicator(status.get("status", "unknown"))
            lines.append(
                f"  {indicator} {component.capitalize()}: {status.get('status', 'unknown')}"
            )

        if data.get("issues"):
            lines.append("")
            lines.append("Issues:")
            for issue in data["issues"]:
                severity_indicator = "✗" if issue["severity"] == "critical" else "⚠"
                lines.append(
                    f"  {severity_indicator} {issue['component']}: {issue['issue']}"
                )

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check system health")
    parser.add_argument(
        "--format",
        choices=["json", "text", "summary"],
        default="json",
        help="Output format",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Include detailed information"
    )
    args = parser.parse_args()

    start_time = time.time()

    try:
        # Perform checks
        services = check_docker_services(verbose=args.verbose)
        infrastructure = check_infrastructure(verbose=args.verbose)
        activity = check_recent_activity()

        # Determine overall status
        status, issues, recommendations = determine_overall_status(
            services, infrastructure
        )

        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)

        # Build result
        result = {
            "success": True,
            "status": status,
            "timestamp": format_timestamp(),
            "check_duration_ms": duration_ms,
            "services": services,
            "infrastructure": infrastructure,
            "recent_activity": activity,
            "issues": issues,
            "recommendations": recommendations,
        }

        # Output result
        print(format_output(result, args.format))

        # Exit with appropriate code
        if status == "critical":
            return 2
        elif status == "degraded":
            return 1
        else:
            return 0

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "timestamp": format_timestamp(),
        }
        print(format_json(error_result))
        return 3


if __name__ == "__main__":
    sys.exit(main())

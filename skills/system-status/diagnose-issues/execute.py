#!/usr/bin/env python3
"""
Skill: diagnose-issues
Purpose: Identify and diagnose common system problems

Description:
    Performs comprehensive system diagnostics including Docker service health,
    infrastructure connectivity, and performance metrics. Categorizes issues
    by severity (critical, warning, info) and provides actionable
    recommendations for resolution.

Usage:
    python3 execute.py [--severity SEVERITIES] [--format FORMAT]

    Options:
        --severity SEVERITIES    Filter by severity levels (critical,warning,info)
                                Comma-separated list. Default: all
        --format FORMAT          Output format: json or text
                                Default: json

Output:
    JSON object with the following structure:
    {
        "system_health": "healthy|degraded|critical",
        "issues_found": 3,
        "critical": 1,
        "warnings": 2,
        "issues": [
            {
                "severity": "critical",
                "component": "kafka",
                "issue": "Kafka broker unreachable",
                "details": "Connection timeout after 5s",
                "recommendation": "Check Kafka broker: docker logs omninode-bridge-redpanda",
                "auto_fix_available": false
            }
        ],
        "recommendations": [
            "Check Kafka broker: docker logs omninode-bridge-redpanda",
            "Verify PostgreSQL credentials in .env file"
        ]
    }

Exit Codes:
    0: Success - no issues found, system healthy
    1: Warning - non-critical issues found, system degraded
    2: Critical - critical issues found, system unhealthy
    3: Error - diagnostic execution failed

Examples:
    # Run full diagnostics
    python3 execute.py

    # Check only critical issues in text format
    python3 execute.py --severity critical --format text

    # Check critical and warning issues
    python3 execute.py --severity critical,warning

Created: 2025-11-12
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from db_helper import execute_query
    from docker_helper import get_container_status, list_containers
    from kafka_helper import check_kafka_connection
    from qdrant_helper import check_qdrant_connection
    from status_formatter import format_json, format_status_indicator
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(3)


def check_service_issues():
    """Check for Docker service issues (filtered to relevant OmniNode containers)."""
    issues = []

    # Define monitored container prefixes (OmniNode services only)
    monitored_prefixes = ["archon-", "omninode-", "omniclaude-"]

    try:
        containers = list_containers()
        if not containers["success"]:
            issues.append(
                {
                    "severity": "critical",
                    "component": "docker",
                    "issue": "Failed to list containers",
                    "details": containers.get("error"),
                    "recommendation": "Verify Docker daemon is running",
                    "auto_fix_available": False,
                }
            )
            return issues

        # Filter to monitored containers only
        monitored_containers = [
            c
            for c in containers["containers"]
            if any(c["name"].startswith(prefix) for prefix in monitored_prefixes)
        ]

        for container in monitored_containers:
            name = container["name"]
            state = container["state"].lower()
            status = container["status"].lower()

            # Check if stopped
            if state != "running":
                issues.append(
                    {
                        "severity": "critical",
                        "component": name,
                        "issue": "Container not running",
                        "details": f"Current state: {state}",
                        "recommendation": f"Start container: docker start {name}",
                        "auto_fix_available": False,
                    }
                )

            # Check if unhealthy
            elif "unhealthy" in status:
                issues.append(
                    {
                        "severity": "warning",
                        "component": name,
                        "issue": "Container unhealthy",
                        "details": "Health check failing",
                        "recommendation": f"Check logs: docker logs {name}",
                        "auto_fix_available": False,
                    }
                )

            # Check restart count
            container_status = get_container_status(name)
            if (
                container_status.get("success")
                and container_status.get("restart_count", 0) > 5
            ):
                issues.append(
                    {
                        "severity": "warning",
                        "component": name,
                        "issue": "High restart count",
                        "details": f"Restarted {container_status['restart_count']} times",
                        "recommendation": f"Investigate crashes: docker logs {name}",
                        "auto_fix_available": False,
                    }
                )

    except Exception as e:
        issues.append(
            {
                "severity": "critical",
                "component": "docker",
                "issue": "Service check failed",
                "details": str(e),
                "recommendation": "Verify Docker is accessible",
                "auto_fix_available": False,
            }
        )

    return issues


def check_infrastructure_issues():
    """Check for infrastructure connectivity issues."""
    issues = []

    # Check Kafka
    try:
        kafka = check_kafka_connection()
        if not kafka.get("reachable"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "kafka",
                    "issue": "Kafka broker unreachable",
                    "details": kafka.get("error", "Connection failed"),
                    "recommendation": "Check Kafka broker: docker logs omninode-bridge-redpanda",
                    "auto_fix_available": False,
                }
            )
    except Exception as e:
        issues.append(
            {
                "severity": "critical",
                "component": "kafka",
                "issue": "Kafka check failed",
                "details": str(e),
                "recommendation": "Verify Kafka configuration in .env",
                "auto_fix_available": False,
            }
        )

    # Check PostgreSQL
    try:
        result = execute_query("SELECT 1")
        if not result.get("success"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "postgres",
                    "issue": "PostgreSQL unreachable",
                    "details": result.get("error", "Connection failed"),
                    "recommendation": "Verify PostgreSQL credentials in .env file",
                    "auto_fix_available": False,
                }
            )
        else:
            # Check connection pool usage
            # First, query the actual max_connections setting
            max_conn_result = execute_query("SHOW max_connections")
            max_connections = None
            if max_conn_result.get("success") and max_conn_result.get("rows"):
                try:
                    max_connections = int(
                        max_conn_result["rows"][0].get("max_connections", 100)
                    )
                except (ValueError, TypeError):
                    max_connections = None

            # Query active connections
            conn_result = execute_query(
                """
                SELECT count(*) as active
                FROM pg_stat_activity
                WHERE state = 'active'
            """
            )
            if conn_result.get("success") and conn_result.get("rows"):
                active = conn_result["rows"][0]["active"]

                # Calculate usage percentage based on actual max_connections
                if max_connections:
                    usage_pct = (active / max_connections) * 100
                    details = f"Active connections: {active}/{max_connections} ({usage_pct:.1f}%)"

                    # Determine severity based on percentage thresholds
                    if usage_pct > 80:
                        severity = "critical"
                        issue_text = "Connection pool critically high"
                    elif usage_pct > 60:
                        severity = "warning"
                        issue_text = "Connection pool near capacity"
                    else:
                        severity = None  # No issue if under 60%

                    if severity:
                        issues.append(
                            {
                                "severity": severity,
                                "component": "postgres",
                                "issue": issue_text,
                                "details": details,
                                "recommendation": "Consider increasing max_connections or optimizing queries",
                                "auto_fix_available": False,
                            }
                        )
                else:
                    # Fallback: max_connections unknown, use absolute threshold
                    if active > 80:
                        issues.append(
                            {
                                "severity": "warning",
                                "component": "postgres",
                                "issue": "High active connection count",
                                "details": f"Active connections: {active} (max_connections unknown)",
                                "recommendation": "Consider increasing max_connections or optimizing queries",
                                "auto_fix_available": False,
                            }
                        )
    except Exception as e:
        issues.append(
            {
                "severity": "critical",
                "component": "postgres",
                "issue": "PostgreSQL check failed",
                "details": str(e),
                "recommendation": "Verify database is running and accessible",
                "auto_fix_available": False,
            }
        )

    # Check Qdrant
    try:
        qdrant = check_qdrant_connection()
        if not qdrant.get("reachable"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "qdrant",
                    "issue": "Qdrant unreachable",
                    "details": qdrant.get("error", "Connection failed"),
                    "recommendation": "Check Qdrant service: docker logs archon-qdrant",
                    "auto_fix_available": False,
                }
            )
    except Exception as e:
        issues.append(
            {
                "severity": "critical",
                "component": "qdrant",
                "issue": "Qdrant check failed",
                "details": str(e),
                "recommendation": "Verify Qdrant configuration",
                "auto_fix_available": False,
            }
        )

    return issues


def check_performance_issues():
    """Check for performance degradation."""
    issues = []

    # Check manifest injection performance (separate try/except)
    try:
        manifest_query = """
            SELECT AVG(total_query_time_ms) as avg_time
            FROM agent_manifest_injections
            WHERE created_at > NOW() - %s::interval
        """
        result = execute_query(manifest_query, ("1 hour",))

        if result.get("success") and result.get("rows"):
            avg_time = result["rows"][0].get("avg_time")
            if avg_time and float(avg_time) > 5000:
                issues.append(
                    {
                        "severity": "warning",
                        "component": "manifest-injection",
                        "issue": "High manifest injection latency",
                        "details": f"Avg query time: {int(avg_time)}ms (target: <2000ms)",
                        "recommendation": "Check Qdrant performance and collection sizes",
                        "auto_fix_available": False,
                    }
                )
        elif not result.get("success"):
            issues.append(
                {
                    "severity": "info",
                    "component": "manifest-injection",
                    "issue": "Manifest performance check returned error",
                    "details": result.get("error", "Query failed"),
                    "recommendation": "Verify agent_manifest_injections table exists",
                    "auto_fix_available": False,
                }
            )
    except Exception as e:
        issues.append(
            {
                "severity": "info",
                "component": "manifest-injection",
                "issue": "Manifest performance check failed",
                "details": str(e),
                "recommendation": "Check database schema and permissions",
                "auto_fix_available": False,
            }
        )

    # Check routing performance (separate try/except)
    try:
        routing_query = """
            SELECT AVG(routing_time_ms) as avg_time
            FROM agent_routing_decisions
            WHERE created_at > NOW() - %s::interval
        """
        result = execute_query(routing_query, ("1 hour",))

        if result.get("success") and result.get("rows"):
            avg_time = result["rows"][0].get("avg_time")
            if avg_time and float(avg_time) > 100:
                issues.append(
                    {
                        "severity": "warning",
                        "component": "routing",
                        "issue": "High routing latency",
                        "details": f"Avg routing time: {int(avg_time)}ms (target: <100ms)",
                        "recommendation": "Review routing algorithm efficiency",
                        "auto_fix_available": False,
                    }
                )
        elif not result.get("success"):
            issues.append(
                {
                    "severity": "info",
                    "component": "routing",
                    "issue": "Routing performance check returned error",
                    "details": result.get("error", "Query failed"),
                    "recommendation": "Verify agent_routing_decisions table exists",
                    "auto_fix_available": False,
                }
            )
    except Exception as e:
        issues.append(
            {
                "severity": "info",
                "component": "routing",
                "issue": "Routing performance check failed",
                "details": str(e),
                "recommendation": "Check database schema and permissions",
                "auto_fix_available": False,
            }
        )

    return issues


def format_text_output(data: dict) -> str:
    """Format output as text."""
    lines = [
        "=" * 70,
        "SYSTEM DIAGNOSTICS",
        "=" * 70,
        f"System Health: {data['system_health'].upper()}",
        f"Issues Found: {data['issues_found']} (Critical: {data['critical']}, Warnings: {data['warnings']})",
        "",
    ]

    if data.get("issues"):
        lines.append("ISSUES:")
        for issue in data["issues"]:
            severity_symbol = "✗" if issue["severity"] == "critical" else "⚠"
            lines.append(
                f"\n{severity_symbol} {issue['component'].upper()} - {issue['issue']}"
            )
            lines.append(f"  Details: {issue['details']}")
            lines.append(f"  Recommendation: {issue['recommendation']}")

    if data.get("recommendations"):
        lines.append("\nRECOMMENDATIONS:")
        for i, rec in enumerate(data["recommendations"], 1):
            lines.append(f"  {i}. {rec}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Diagnose system issues")
    parser.add_argument("--severity", help="Filter by severity (critical,warning,info)")
    parser.add_argument(
        "--format", choices=["json", "text"], default="json", help="Output format"
    )
    args = parser.parse_args()

    try:
        # Collect issues from all checks
        all_issues = []
        all_issues.extend(check_service_issues())
        all_issues.extend(check_infrastructure_issues())
        all_issues.extend(check_performance_issues())

        # Filter by severity if requested
        if args.severity:
            severities = [s.strip() for s in args.severity.split(",")]
            all_issues = [i for i in all_issues if i["severity"] in severities]

        # Count issues by severity
        critical_count = sum(1 for i in all_issues if i["severity"] == "critical")
        warning_count = sum(1 for i in all_issues if i["severity"] == "warning")

        # Determine system health
        if critical_count > 0:
            system_health = "critical"
            exit_code = 2
        elif warning_count > 0:
            system_health = "degraded"
            exit_code = 1
        else:
            system_health = "healthy"
            exit_code = 0

        # Build result
        result = {
            "success": True,
            "system_health": system_health,
            "issues_found": len(all_issues),
            "critical": critical_count,
            "warnings": warning_count,
            "issues": all_issues,
            "recommendations": list(set(i["recommendation"] for i in all_issues)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Output result
        if args.format == "text":
            print(format_text_output(result))
        else:
            print(format_json(result))

        return exit_code

    except Exception as e:
        error_result = {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print(format_json(error_result))
        return 3


if __name__ == "__main__":
    sys.exit(main())

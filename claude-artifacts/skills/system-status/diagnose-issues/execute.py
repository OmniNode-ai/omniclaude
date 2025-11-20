#!/usr/bin/env python3
"""
Diagnose Issues - Identify and diagnose common system problems

Usage:
    python3 execute.py [--severity critical,warning] [--format json|text]

Exit Codes:
    0 - No issues found
    1 - Warnings found
    2 - Critical issues found
    3 - Execution error

Created: 2025-11-12
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

try:
    from constants import (
        MAX_CONNECTIONS_THRESHOLD,
        MAX_RESTART_COUNT_THRESHOLD,
        QUERY_TIMEOUT_THRESHOLD_MS,
        ROUTING_TIMEOUT_THRESHOLD_MS,
    )
    from db_helper import execute_query
    from docker_helper import get_container_status, list_containers
    from kafka_helper import check_kafka_connection
    from qdrant_helper import check_qdrant_connection
    from status_formatter import format_json, format_status_indicator
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(3)


def check_service_issues() -> List[Dict[str, Any]]:
    """Check for Docker service issues.

    Returns:
        List of issue dictionaries containing severity, component, issue description, and recommendations
    """
    issues: List[Dict[str, Any]] = []

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

        for container in containers["containers"]:
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
                and container_status.get("restart_count", 0)
                > MAX_RESTART_COUNT_THRESHOLD
            ):
                issues.append(
                    {
                        "severity": "warning",
                        "component": name,
                        "issue": "High restart count",
                        "details": f"Restarted {container_status['restart_count']} times (threshold: {MAX_RESTART_COUNT_THRESHOLD})",
                        "recommendation": f"Investigate crashes: docker logs {name}",
                        "auto_fix_available": False,
                    }
                )

    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Docker connectivity check failed: {e}", exc_info=True)
        issues.append(
            {
                "severity": "critical",
                "component": "docker",
                "issue": "Docker connection failed",
                "details": str(e),
                "recommendation": "Verify Docker daemon is running and accessible",
                "auto_fix_available": False,
            }
        )
    except Exception as e:
        logger.exception(f"Unexpected error in Docker service check: {e}")
        issues.append(
            {
                "severity": "critical",
                "component": "docker",
                "issue": "Service check failed",
                "details": f"Unexpected error: {e}",
                "recommendation": "Check Docker installation and permissions",
                "auto_fix_available": False,
            }
        )

    return issues


def check_infrastructure_issues() -> List[Dict[str, Any]]:
    """Check for infrastructure connectivity issues.

    Returns:
        List of issue dictionaries containing severity, component, issue description, and recommendations
    """
    issues: List[Dict[str, Any]] = []

    # Check Kafka (independent check - failures don't affect other checks)
    kafka_result = None
    try:
        kafka_result = check_kafka_connection()
        if not kafka_result.get("reachable"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "kafka",
                    "issue": "Kafka broker unreachable",
                    "details": kafka_result.get("error", "Connection failed"),
                    "recommendation": "Check Kafka broker: docker logs omninode-bridge-redpanda",
                    "auto_fix_available": False,
                }
            )
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Kafka connectivity check failed: {e}", exc_info=True)
        issues.append(
            {
                "severity": "critical",
                "component": "kafka",
                "issue": "Kafka connection failed",
                "details": str(e),
                "recommendation": "Verify Kafka broker is running and KAFKA_BOOTSTRAP_SERVERS in .env is correct",
                "auto_fix_available": False,
            }
        )
    except Exception as e:
        logger.exception(f"Unexpected error in Kafka check: {e}")
        issues.append(
            {
                "severity": "critical",
                "component": "kafka",
                "issue": "Kafka check failed",
                "details": f"Unexpected error: {e}",
                "recommendation": "Verify Kafka configuration in .env and check kafka_helper.py",
                "auto_fix_available": False,
            }
        )

    # Check PostgreSQL (independent check - failures don't affect other checks)
    postgres_result = None
    try:
        postgres_result = execute_query("SELECT 1")
        if not postgres_result.get("success"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "postgres",
                    "issue": "PostgreSQL unreachable",
                    "details": postgres_result.get("error", "Connection failed"),
                    "recommendation": "Verify PostgreSQL credentials in .env file and source .env before running",
                    "auto_fix_available": False,
                }
            )
        else:
            # Check connection pool
            try:
                conn_result = execute_query(
                    """
                    SELECT count(*) as active
                    FROM pg_stat_activity
                    WHERE state = 'active'
                """
                )
                if conn_result.get("success") and conn_result.get("rows"):
                    active = conn_result["rows"][0]["active"]
                    if active > MAX_CONNECTIONS_THRESHOLD:
                        issues.append(
                            {
                                "severity": "warning",
                                "component": "postgres",
                                "issue": "Connection pool near capacity",
                                "details": f"Active connections: {active}/{MAX_CONNECTIONS_THRESHOLD + 20}",
                                "recommendation": "Consider increasing max_connections or optimizing queries",
                                "auto_fix_available": False,
                            }
                        )
            except Exception as e:
                logger.warning(f"Could not check PostgreSQL connection pool: {e}")
                # Don't add to issues - pool check is optional
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"PostgreSQL connectivity check failed: {e}", exc_info=True)
        issues.append(
            {
                "severity": "critical",
                "component": "postgres",
                "issue": "PostgreSQL connection failed",
                "details": str(e),
                "recommendation": "Verify PostgreSQL is running: docker ps | grep postgres",
                "auto_fix_available": False,
            }
        )
    except Exception as e:
        logger.exception(f"Unexpected error in PostgreSQL check: {e}")
        issues.append(
            {
                "severity": "critical",
                "component": "postgres",
                "issue": "PostgreSQL check failed",
                "details": f"Unexpected error: {e}",
                "recommendation": "Verify database is running and POSTGRES_* variables in .env are correct",
                "auto_fix_available": False,
            }
        )

    # Check Qdrant (independent check - failures don't affect other checks)
    qdrant_result = None
    try:
        qdrant_result = check_qdrant_connection()
        if not qdrant_result.get("reachable"):
            issues.append(
                {
                    "severity": "critical",
                    "component": "qdrant",
                    "issue": "Qdrant unreachable",
                    "details": qdrant_result.get("error", "Connection failed"),
                    "recommendation": "Check Qdrant service: docker logs archon-qdrant",
                    "auto_fix_available": False,
                }
            )
    except (ConnectionError, TimeoutError) as e:
        logger.error(f"Qdrant connectivity check failed: {e}", exc_info=True)
        issues.append(
            {
                "severity": "critical",
                "component": "qdrant",
                "issue": "Qdrant connection failed",
                "details": str(e),
                "recommendation": "Verify Qdrant is running and QDRANT_URL in .env is correct",
                "auto_fix_available": False,
            }
        )
    except Exception as e:
        logger.exception(f"Unexpected error in Qdrant check: {e}")
        issues.append(
            {
                "severity": "critical",
                "component": "qdrant",
                "issue": "Qdrant check failed",
                "details": f"Unexpected error: {e}",
                "recommendation": "Verify Qdrant configuration in .env and check qdrant_helper.py",
                "auto_fix_available": False,
            }
        )

    return issues


def check_performance_issues() -> List[Dict[str, Any]]:
    """Check for performance degradation.

    Returns:
        List of issue dictionaries containing severity, component, issue description, and recommendations
    """
    issues: List[Dict[str, Any]] = []

    try:
        # Check manifest injection performance
        manifest_query = """
            SELECT AVG(total_query_time_ms) as avg_time
            FROM agent_manifest_injections
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """
        result = execute_query(manifest_query)

        if result.get("success") and result.get("rows"):
            avg_time = result["rows"][0].get("avg_time")
            if avg_time and float(avg_time) > QUERY_TIMEOUT_THRESHOLD_MS:
                issues.append(
                    {
                        "severity": "warning",
                        "component": "manifest-injection",
                        "issue": "High manifest injection latency",
                        "details": f"Avg query time: {int(avg_time)}ms (target: <{QUERY_TIMEOUT_THRESHOLD_MS}ms)",
                        "recommendation": "Check Qdrant performance and collection sizes",
                        "auto_fix_available": False,
                    }
                )

        # Check routing performance
        routing_query = """
            SELECT AVG(routing_time_ms) as avg_time
            FROM agent_routing_decisions
            WHERE created_at > NOW() - INTERVAL '1 hour'
        """
        result = execute_query(routing_query)

        if result.get("success") and result.get("rows"):
            avg_time = result["rows"][0].get("avg_time")
            if avg_time and float(avg_time) > ROUTING_TIMEOUT_THRESHOLD_MS:
                issues.append(
                    {
                        "severity": "warning",
                        "component": "routing",
                        "issue": "High routing latency",
                        "details": f"Avg routing time: {int(avg_time)}ms (target: <{ROUTING_TIMEOUT_THRESHOLD_MS}ms)",
                        "recommendation": "Review routing algorithm efficiency",
                        "auto_fix_available": False,
                    }
                )
    except Exception as e:
        # Performance checks are optional - log but don't fail if tables don't exist
        logger.info(f"Performance checks skipped (tables may not exist yet): {e}")
        # Not adding to issues - performance monitoring is optional during initial setup

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


def main() -> int:
    """Diagnose system issues.

    Returns:
        Exit code (0=healthy, 1=warnings, 2=critical, 3=error)
    """
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
            "system_health": system_health,
            "issues_found": len(all_issues),
            "critical": critical_count,
            "warnings": warning_count,
            "issues": all_issues,
            "recommendations": list(set(i["recommendation"] for i in all_issues)),
        }

        # Output result
        if args.format == "text":
            print(format_text_output(result))
        else:
            print(format_json(result))

        return exit_code

    except Exception as e:
        error_result = {"success": False, "error": str(e)}
        print(format_json(error_result))
        return 3


if __name__ == "__main__":
    sys.exit(main())

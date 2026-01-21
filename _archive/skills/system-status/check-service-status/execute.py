#!/usr/bin/env python3
"""
Skill: check-service-status
Purpose: Check detailed status for specific Docker services

Description:
    Retrieves detailed status information for a specific Docker service
    including runtime status, health status, resource usage, and recent
    logs. Useful for deep-diving into individual service health and
    troubleshooting issues.

Usage:
    python3 execute.py --service SERVICE [--include-logs] [--include-stats] [--log-lines N]

    Options:
        --service SERVICE        Name of the Docker service to check (required)
        --include-logs          Include recent log entries in output
        --include-stats         Include resource usage statistics (CPU, memory)
        --log-lines N           Number of log lines to retrieve (1-1000)
                               Default: 50

Output:
    JSON object with the following structure:
    {
        "service": "archon-intelligence",
        "status": "running",
        "health": "healthy",
        "running": true,
        "started_at": "2025-11-12T10:00:00Z",
        "restart_count": 0,
        "image": "archon-intelligence:latest",
        "resources": {
            "cpu_percent": 5.2,
            "memory_usage": "256 MB",
            "memory_percent": 12.5
        },
        "logs": {
            "total_lines": 1234,
            "error_count": 2,
            "recent_errors": [
                "2025-11-12 14:30:00 ERROR: Connection timeout"
            ]
        }
    }

Exit Codes:
    0: Success - service status retrieved successfully
    1: Error - service not found or Docker communication failed

Examples:
    # Check basic service status
    python3 execute.py --service archon-intelligence

    # Check service with resource stats
    python3 execute.py --service archon-intelligence --include-stats

    # Check service with logs and stats
    python3 execute.py --service archon-intelligence --include-logs --include-stats

    # Check service with last 100 log lines
    python3 execute.py --service archon-intelligence --include-logs --log-lines 100

Created: 2025-11-12
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from docker_helper import (
        get_container_logs,
        get_container_stats,
        get_container_status,
    )
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def validate_log_lines(value):
    """Validate log-lines value to prevent errors and DoS attacks.

    Args:
        value: String value from argparse

    Returns:
        int: Validated integer value (1-1000)

    Raises:
        argparse.ArgumentTypeError: If value is outside valid range or non-integer
    """
    try:
        ivalue = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid integer: {value}")

    if not (1 <= ivalue <= 1000):
        raise argparse.ArgumentTypeError(
            f"Value must be between 1 and 1000 (got {ivalue})"
        )

    return ivalue


def main():
    parser = argparse.ArgumentParser(description="Check service status")
    parser.add_argument("--service", required=True, help="Service name")
    parser.add_argument(
        "--include-logs", action="store_true", help="Include recent logs"
    )
    parser.add_argument(
        "--include-stats", action="store_true", help="Include resource stats"
    )
    parser.add_argument(
        "--log-lines",
        type=validate_log_lines,
        default=50,
        help="Number of log lines (1-1000, default: 50)",
    )
    args = parser.parse_args()

    try:
        # Get container status
        status = get_container_status(args.service)

        if not status["success"]:
            print(format_json(status))
            return 1

        result = {
            "service": args.service,
            "status": status.get("status"),
            "health": status.get("health"),
            "running": status.get("running"),
            "started_at": status.get("started_at"),
            "restart_count": status.get("restart_count"),
            "image": status.get("image"),
        }

        # Add resource stats if requested
        if args.include_stats:
            stats = get_container_stats(args.service)
            if stats["success"]:
                result["resources"] = {
                    "cpu_percent": stats.get("cpu_percent"),
                    "memory_usage": stats.get("memory_usage"),
                    "memory_percent": stats.get("memory_percent"),
                }

        # Add logs if requested
        if args.include_logs:
            logs = get_container_logs(args.service, tail=args.log_lines)
            if logs["success"]:
                result["logs"] = {
                    "total_lines": logs.get("log_count"),
                    "error_count": logs.get("error_count"),
                    "recent_errors": logs.get("errors", [])[:5],  # Top 5 errors
                }

        # Add success and timestamp to response
        result["success"] = True
        result["timestamp"] = datetime.now(UTC).isoformat()

        print(format_json(result))
        return 0

    except Exception as e:
        print(
            format_json(
                {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())

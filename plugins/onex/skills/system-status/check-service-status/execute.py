#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Check Service Status - Detailed status for specific Docker services

Usage:
    python3 execute.py --service <service-name> [--include-logs] [--include-stats]

Created: 2025-11-12
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))

try:
    from constants import (
        DEFAULT_LOG_LINES,
        MAX_LOG_LINES,
        MAX_RECENT_ERRORS_DISPLAY,
        MIN_LOG_LINES,
    )
    from docker_helper import (
        get_container_logs,
        get_container_stats,
        get_container_status,
    )
    from status_formatter import format_json
except ImportError as e:
    print(json.dumps({"success": False, "error": f"Import failed: {e}"}))
    sys.exit(1)


def validate_log_lines(value: str) -> int:
    """Validate --log-lines parameter is within acceptable range.

    Args:
        value: String value from argparse

    Returns:
        Validated integer value

    Raises:
        argparse.ArgumentTypeError: If value is out of bounds
    """
    ivalue: int = int(value)
    if not (MIN_LOG_LINES <= ivalue <= MAX_LOG_LINES):
        raise argparse.ArgumentTypeError(
            f"log-lines must be between {MIN_LOG_LINES} and {MAX_LOG_LINES}"
        )
    return ivalue


def main() -> int:
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
        default=DEFAULT_LOG_LINES,
        help=f"Number of log lines ({MIN_LOG_LINES}-{MAX_LOG_LINES})",
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
                    "recent_errors": logs.get("errors", [])[:MAX_RECENT_ERRORS_DISPLAY],
                }

        print(format_json(result))
        return 0

    except Exception as e:
        print(format_json({"success": False, "error": str(e)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())

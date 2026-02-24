#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Log Agent Action Skill - Track every agent action in debug mode

Logs every action an agent takes (tool calls, decisions, errors) when
DEBUG mode is enabled, providing complete execution traces for analysis.

Usage:
  /log-agent-action --agent AGENT_NAME --action-type TYPE --action-name NAME --details JSON

Options:
  --agent: Agent name performing the action (required)
  --action-type: Type of action (tool_call|decision|error|success) (required)
  --action-name: Specific action name (required)
  --details: JSON object with action-specific details (optional)
  --correlation-id: Correlation ID for tracking (optional, auto-generated)
  --debug-mode: Force debug logging regardless of DEBUG env var (optional)
  --duration-ms: How long the action took in milliseconds (optional)
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
)


def should_log_debug() -> bool:
    """
    Check if debug logging is enabled.

    Returns:
        True if DEBUG env var is set to true/1/yes, False otherwise
    """
    debug_env = os.environ.get("DEBUG", "").lower()
    return debug_env in ("true", "1", "yes", "on")


def log_agent_action(args):
    """Log an agent action to the database."""

    # Check if we should log (debug mode)
    force_debug = getattr(args, "debug_mode", False)
    if not force_debug and not should_log_debug():
        # Silent skip in non-debug mode
        output = {
            "success": True,
            "skipped": True,
            "reason": "debug_mode_disabled",
            "message": "Action logging skipped (DEBUG mode not enabled)",
        }
        print(json.dumps(output, indent=2))
        return 0

    # Get or generate correlation ID
    correlation_id = (
        args.correlation_id if args.correlation_id else get_correlation_id()
    )

    # Parse JSON details
    details = {}
    if hasattr(args, "details") and args.details:
        details = parse_json_param(args.details)
        if details is None:
            details = {}

    # Prepare SQL
    sql = """
    INSERT INTO agent_actions (
        correlation_id,
        agent_name,
        action_type,
        action_name,
        action_details,
        debug_mode,
        duration_ms
    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    RETURNING id, created_at
    """

    params = (
        correlation_id,
        args.agent,
        args.action_type,
        args.action_name,
        json.dumps(details),
        True,  # debug_mode (always true if we got here)
        (
            int(args.duration_ms)
            if hasattr(args, "duration_ms") and args.duration_ms
            else None
        ),
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            output = {
                "success": True,
                "action_id": str(row["id"]),
                "correlation_id": correlation_id,
                "agent_name": args.agent,
                "action_type": args.action_type,
                "action_name": args.action_name,
                "debug_mode": True,
                "created_at": row["created_at"].isoformat(),
            }
            print(json.dumps(output, indent=2))
            return 0
        else:
            error = {"success": False, "error": "No result returned from database"}
            print(json.dumps(error), file=sys.stderr)
            return 1

    except Exception as e:
        error_info = handle_db_error(e, "log_agent_action")
        print(json.dumps(error_info), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent action to PostgreSQL (debug mode)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Required arguments
    parser.add_argument("--agent", required=True, help="Agent name performing action")
    parser.add_argument(
        "--action-type",
        required=True,
        choices=["tool_call", "decision", "error", "success"],
        help="Type of action",
    )
    parser.add_argument("--action-name", required=True, help="Specific action name")

    # Optional arguments
    parser.add_argument("--details", help="JSON object with action details")
    parser.add_argument("--correlation-id", help="Correlation ID for tracking")
    parser.add_argument(
        "--debug-mode",
        action="store_true",
        help="Force debug logging (override DEBUG env var)",
    )
    parser.add_argument(
        "--duration-ms", type=int, help="Action duration in milliseconds"
    )

    args = parser.parse_args()

    return log_agent_action(args)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Log Agent Action Skill

Logs agent actions (tool calls, decisions, errors, successes) to the database.
Called by hooks during agent execution for observability.

Usage:
    python3 execute_unified.py \
        --agent polymorphic-agent \
        --action-type decision \
        --action-name agent_selected \
        --details '{"selection_method": "event_routing", "confidence": "0.85"}' \
        --correlation-id uuid-here \
        --project-path /path/to/project \
        --project-name myproject \
        --working-directory /current/dir
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Add project root to path for config imports
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

# Add skills root to path for shared imports
_SKILLS_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _SKILLS_ROOT)

# Import directly from db_helper module
from _shared.db_helper import execute_query, get_correlation_id, parse_json_param

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_agent_action(
    agent: str,
    action_type: str,
    action_name: str,
    details: Optional[Dict[str, Any]],
    correlation_id: str,
    project_path: str,
    project_name: str,
    working_directory: str,
    session_id: Optional[str] = None,
    duration_ms: Optional[int] = None,
    success: Optional[bool] = None,
    error_message: Optional[str] = None,
) -> Optional[str]:
    """
    Log an agent action to the database.

    Args:
        agent: Name of the agent performing the action
        action_type: Type of action (tool_call, decision, error, success, milestone)
        action_name: Name of the specific action
        details: JSON-serializable details about the action
        correlation_id: Correlation ID for tracing
        project_path: Path to the project
        project_name: Name of the project
        working_directory: Current working directory
        session_id: Optional session ID
        duration_ms: Optional duration in milliseconds
        success: Optional success indicator
        error_message: Optional error message if action failed

    Returns:
        Event ID if logged successfully, None otherwise
    """
    sql = """
        INSERT INTO agent_actions (
            correlation_id,
            session_id,
            agent_name,
            action_type,
            action_name,
            details,
            project_name,
            project_path,
            working_directory,
            duration_ms,
            success,
            error_message,
            created_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
    """

    # Serialize details to JSON string for storage
    details_json = json.dumps(details) if details else "{}"

    params = (
        correlation_id,
        session_id,
        agent,
        action_type,
        action_name,
        details_json,
        project_name,
        project_path,
        working_directory,
        duration_ms,
        success,
        error_message[:1000] if error_message else None,  # Truncate error message
        datetime.now(timezone.utc),
    )

    result = execute_query(sql, params, fetch=True)

    if result["success"] and result["rows"]:
        event_id = str(result["rows"][0]["id"])
        logger.info(f"Agent action logged: {event_id} ({action_type}/{action_name})")
        return event_id
    else:
        logger.error(f"Failed to log agent action: {result.get('error')}")
        return None


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Log agent action")
    parser.add_argument("--agent", required=True, help="Agent name")
    parser.add_argument(
        "--action-type",
        required=True,
        choices=["tool_call", "decision", "error", "success", "milestone"],
        help="Type of action",
    )
    parser.add_argument("--action-name", required=True, help="Name of the action")
    parser.add_argument("--details", default="{}", help="JSON details about the action")
    parser.add_argument(
        "--correlation-id", default="", help="Correlation ID for tracing"
    )
    parser.add_argument("--project-path", default="", help="Project path")
    parser.add_argument("--project-name", default="", help="Project name")
    parser.add_argument("--working-directory", default="", help="Working directory")
    parser.add_argument("--session-id", default=None, help="Session ID")
    parser.add_argument(
        "--duration-ms", type=int, default=None, help="Action duration in milliseconds"
    )
    parser.add_argument(
        "--success", type=bool, default=None, help="Whether action succeeded"
    )
    parser.add_argument("--error-message", default=None, help="Error message if failed")

    args = parser.parse_args()

    # Parse details JSON
    details = parse_json_param(args.details)

    # Use provided correlation ID or generate one
    correlation_id = args.correlation_id or get_correlation_id()

    event_id = log_agent_action(
        agent=args.agent,
        action_type=args.action_type,
        action_name=args.action_name,
        details=details,
        correlation_id=correlation_id,
        project_path=args.project_path,
        project_name=args.project_name,
        working_directory=args.working_directory or os.getcwd(),
        session_id=args.session_id,
        duration_ms=args.duration_ms,
        success=args.success,
        error_message=args.error_message,
    )

    if event_id:
        print(f"Agent action logged: {event_id}")
        sys.exit(0)
    else:
        print("Failed to log agent action", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

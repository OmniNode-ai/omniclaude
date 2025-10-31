#!/usr/bin/env python3
"""
Log Execution Skill - Track agent execution in PostgreSQL

Usage:
  /log-execution start --agent AGENT_NAME --description "Task description"
  /log-execution progress --execution-id UUID --stage STAGE --percent 50
  /log-execution complete --execution-id UUID --status success

Options:
  start:
    --agent: Agent name (required)
    --description: Task description (optional)
    --session-id: Session ID (optional, auto-generated)
    --metadata: JSON metadata (optional)

  progress:
    --execution-id: Execution ID from start (required)
    --stage: Current stage name (required)
    --percent: Progress percentage 0-100 (optional)
    --metadata: Additional JSON metadata (optional)

  complete:
    --execution-id: Execution ID from start (required)
    --status: success|error|cancelled (default: success)
    --error-message: Error description if status=error (optional)
    --quality-score: Quality score 0.0-1.0 (optional)
    --metadata: Final JSON metadata (optional)
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add _shared to path
sys.path.insert(0, str(Path(__file__).parent.parent / "_shared"))
from db_helper import (
    execute_query,
    get_correlation_id,
    handle_db_error,
    parse_json_param,
)


def log_start(args):
    """Log execution start - creates new execution record."""
    correlation_id = get_correlation_id()

    # Parse metadata
    metadata = (
        parse_json_param(args.metadata)
        if hasattr(args, "metadata") and args.metadata
        else {}
    )

    # Generate session_id if not provided
    session_id = (
        args.session_id
        if hasattr(args, "session_id") and args.session_id
        else str(uuid.uuid4())
    )

    sql = """
    INSERT INTO agent_execution_logs (
        correlation_id,
        session_id,
        agent_name,
        user_prompt,
        status,
        metadata,
        project_path,
        project_name,
        terminal_id
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING execution_id, started_at
    """

    params = (
        correlation_id,
        session_id,
        args.agent,
        args.description if hasattr(args, "description") else None,
        "in_progress",
        json.dumps(metadata),
        (
            args.project_path
            if hasattr(args, "project_path") and args.project_path
            else None
        ),
        (
            args.project_name
            if hasattr(args, "project_name") and args.project_name
            else None
        ),
        args.terminal_id if hasattr(args, "terminal_id") and args.terminal_id else None,
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            print(
                json.dumps(
                    {
                        "success": True,
                        "execution_id": str(row["execution_id"]),
                        "started_at": row["started_at"].isoformat(),
                        "correlation_id": correlation_id,
                        "session_id": session_id,
                    },
                    indent=2,
                )
            )
            return 0
        else:
            print(
                json.dumps({"success": False, "error": "No result returned"}),
                file=sys.stderr,
            )
            return 1

    except Exception as e:
        print(json.dumps(handle_db_error(e, "log_start")), file=sys.stderr)
        return 1


def log_progress(args):
    """Log execution progress - updates existing record with progress info."""
    # Parse or create metadata
    metadata = (
        parse_json_param(args.metadata)
        if hasattr(args, "metadata") and args.metadata
        else {}
    )

    # Add progress information
    metadata.update(
        {
            "stage": args.stage,
            "percent": (
                args.percent if hasattr(args, "percent") and args.percent else None
            ),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    sql = """
    UPDATE agent_execution_logs
    SET metadata = metadata || %s::jsonb
    WHERE execution_id = %s
    RETURNING execution_id, agent_name, started_at
    """

    params = (json.dumps(metadata), args.execution_id)

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            print(
                json.dumps(
                    {
                        "success": True,
                        "execution_id": str(row["execution_id"]),
                        "agent_name": row["agent_name"],
                        "stage": args.stage,
                        "progress": metadata,
                    },
                    indent=2,
                )
            )
            return 0
        else:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Execution ID {args.execution_id} not found",
                    }
                ),
                file=sys.stderr,
            )
            return 1

    except Exception as e:
        print(json.dumps(handle_db_error(e, "log_progress")), file=sys.stderr)
        return 1


def log_complete(args):
    """Log execution completion - updates record with final status."""
    # Parse or create metadata
    metadata = (
        parse_json_param(args.metadata)
        if hasattr(args, "metadata") and args.metadata
        else {}
    )
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Determine status
    status = args.status if hasattr(args, "status") and args.status else "success"
    if status not in ["success", "error", "cancelled"]:
        status = "success"

    sql = """
    UPDATE agent_execution_logs
    SET
        completed_at = NOW(),
        status = %s,
        error_message = %s,
        quality_score = %s,
        metadata = metadata || %s::jsonb
    WHERE execution_id = %s
    RETURNING execution_id, agent_name, started_at, completed_at, duration_ms
    """

    params = (
        status,
        (
            args.error_message
            if hasattr(args, "error_message") and args.error_message
            else None
        ),
        (
            args.quality_score
            if hasattr(args, "quality_score") and args.quality_score
            else None
        ),
        json.dumps(metadata),
        args.execution_id,
    )

    try:
        result = execute_query(sql, params, fetch=True)
        if result and len(result) > 0:
            row = result[0]
            print(
                json.dumps(
                    {
                        "success": True,
                        "execution_id": str(row["execution_id"]),
                        "agent_name": row["agent_name"],
                        "status": status,
                        "duration_ms": row["duration_ms"],
                        "started_at": row["started_at"].isoformat(),
                        "completed_at": row["completed_at"].isoformat(),
                    },
                    indent=2,
                )
            )
            return 0
        else:
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": f"Execution ID {args.execution_id} not found",
                    }
                ),
                file=sys.stderr,
            )
            return 1

    except Exception as e:
        print(json.dumps(handle_db_error(e, "log_complete")), file=sys.stderr)
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Log agent execution to PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start execution logging")
    start_parser.add_argument("--agent", required=True, help="Agent name")
    start_parser.add_argument("--description", help="Task description")
    start_parser.add_argument("--session-id", help="Session ID (optional)")
    start_parser.add_argument("--metadata", help="JSON metadata (optional)")
    # Project context arguments
    start_parser.add_argument(
        "--project-path", help="Absolute path to project directory"
    )
    start_parser.add_argument("--project-name", help="Project name")
    start_parser.add_argument("--terminal-id", help="Terminal ID")

    # Progress command
    progress_parser = subparsers.add_parser("progress", help="Log execution progress")
    progress_parser.add_argument(
        "--execution-id", required=True, help="Execution ID from start"
    )
    progress_parser.add_argument("--stage", required=True, help="Current stage name")
    progress_parser.add_argument(
        "--percent", type=int, help="Progress percentage (0-100)"
    )
    progress_parser.add_argument("--metadata", help="Additional JSON metadata")

    # Complete command
    complete_parser = subparsers.add_parser(
        "complete", help="Complete execution logging"
    )
    complete_parser.add_argument(
        "--execution-id", required=True, help="Execution ID from start"
    )
    complete_parser.add_argument(
        "--status", choices=["success", "error", "cancelled"], default="success"
    )
    complete_parser.add_argument(
        "--error-message", help="Error description (if status=error)"
    )
    complete_parser.add_argument(
        "--quality-score", type=float, help="Quality score (0.0-1.0)"
    )
    complete_parser.add_argument("--metadata", help="Final JSON metadata")
    # Project context arguments
    complete_parser.add_argument(
        "--project-path", help="Absolute path to project directory"
    )
    complete_parser.add_argument("--project-name", help="Project name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    if args.command == "start":
        return log_start(args)
    elif args.command == "progress":
        return log_progress(args)
    elif args.command == "complete":
        return log_complete(args)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

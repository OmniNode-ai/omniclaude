#!/usr/bin/env python3
"""
Session Intelligence - Session Start/End Event Logging

Logs session lifecycle events (start/end) to the database for analytics.
Called by session-start.sh and session-end.sh hooks.

Usage:
    python3 session_intelligence.py --mode start --session-id UUID --project-path /path --cwd /path
    python3 session_intelligence.py --mode end --session-id UUID --metadata '{"duration_ms": 1000}'
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_session_start(
    session_id: str,
    project_path: Optional[str] = None,
    cwd: Optional[str] = None,
) -> Optional[str]:
    """
    Log session start event.

    Args:
        session_id: Unique session identifier
        project_path: Project directory path
        cwd: Current working directory

    Returns:
        Event ID if logged successfully, None otherwise
    """
    try:
        # Import here to avoid circular imports and allow graceful degradation
        from hook_event_logger import HookEventLogger

        logger_instance = HookEventLogger()
        event_id = logger_instance.log_event(
            source="SessionStart",
            action="session_initialized",
            resource="session",
            resource_id=session_id,
            payload={
                "session_id": session_id,
                "project_path": project_path,
                "cwd": cwd,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            metadata={
                "hook_type": "SessionStart",
                "session_id": session_id,
            },
        )
        logger.info(f"Session start logged: {event_id}")
        return event_id
    except ImportError as e:
        logger.warning(f"HookEventLogger not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to log session start: {e}")
        return None


def log_session_end(
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Log session end event with aggregated statistics.

    Args:
        session_id: Unique session identifier
        metadata: Additional session metadata (duration, etc.)

    Returns:
        Event ID if logged successfully, None otherwise
    """
    try:
        # Import here to avoid circular imports and allow graceful degradation
        from hook_event_logger import HookEventLogger

        logger_instance = HookEventLogger()
        event_id = logger_instance.log_event(
            source="SessionEnd",
            action="session_completed",
            resource="session",
            resource_id=session_id,
            payload={
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **(metadata or {}),
            },
            metadata={
                "hook_type": "SessionEnd",
                "session_id": session_id,
            },
        )
        logger.info(f"Session end logged: {event_id}")
        return event_id
    except ImportError as e:
        logger.warning(f"HookEventLogger not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to log session end: {e}")
        return None


def main():
    """CLI entry point for session intelligence."""
    parser = argparse.ArgumentParser(description="Log session lifecycle events")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["start", "end"],
        help="Session event mode (start or end)",
    )
    parser.add_argument("--session-id", required=True, help="Session identifier")
    parser.add_argument("--project-path", help="Project directory path")
    parser.add_argument("--cwd", help="Current working directory")
    parser.add_argument("--metadata", help="JSON metadata object")

    args = parser.parse_args()

    # Parse metadata if provided
    metadata = None
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid metadata JSON: {e}")

    # Execute based on mode
    if args.mode == "start":
        event_id = log_session_start(
            session_id=args.session_id,
            project_path=args.project_path,
            cwd=args.cwd,
        )
    else:  # mode == "end"
        event_id = log_session_end(
            session_id=args.session_id,
            metadata=metadata,
        )

    # Exit with appropriate code
    sys.exit(0 if event_id else 1)


if __name__ == "__main__":
    main()

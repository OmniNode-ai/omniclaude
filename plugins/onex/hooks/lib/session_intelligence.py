#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Session Intelligence - Session Start/End Event Logging

Stub module retained for CLI compatibility.  The PostgreSQL HookEventLogger
that previously powered log_session_start / log_session_end was removed in
OMN-5139 (Kafka is the canonical observability path).  The functions now
return None immediately and the CLI exits 0 as before.

Usage:
    python3 session_intelligence.py --mode start --session-id UUID --project-path /path --cwd /path
    python3 session_intelligence.py --mode end --session-id UUID --metadata '{"duration_ms": 1000}'
"""

import argparse
import json
import logging
import sys
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_session_start(
    session_id: str,
    project_path: str | None = None,
    cwd: str | None = None,
) -> str | None:
    """Log session start event.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for CLI compat.
    """
    logger.info("Session start event skipped (PostgreSQL logger removed in OMN-5139)")
    return None


def log_session_end(
    session_id: str,
    metadata: dict[str, Any]  # ONEX_EXCLUDE: dict_str_any - generic metadata container
    | None = None,
) -> str | None:
    """Log session end event.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for CLI compat.
    """
    logger.info("Session end event skipped (PostgreSQL logger removed in OMN-5139)")
    return None


def main():
    """CLI entry point for session intelligence.

    Graceful Degradation:
        - Always exits with 0 to not block hooks
        - Logs warnings when database is unavailable
        - Continues even if logging fails
    """
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
    event_id = None
    try:
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
    except Exception as e:
        # Catch any unexpected error and log it, but don't crash
        print(
            f"Warning: session_intelligence failed to log {args.mode} event: {e}",
            file=sys.stderr,
        )
        event_id = None

    # Always exit with 0 - don't block hook execution
    # Log if we failed to record the event
    if event_id is None:
        logger.info(
            f"Session {args.mode} event not logged (database may be unavailable)"
        )
    sys.exit(0)


if __name__ == "__main__":
    main()

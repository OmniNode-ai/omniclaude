#!/usr/bin/env python3
"""
Log Routing Decision Skill

Logs agent routing decisions to the database for analytics and debugging.
Called by user-prompt-submit.sh hook after agent selection.

Usage:
    python3 execute_unified.py \
        --agent polymorphic-agent \
        --confidence 0.85 \
        --strategy event_routing \
        --latency-ms 45 \
        --user-request "Fix the bug in..." \
        --project-path /path/to/project \
        --project-name myproject \
        --session-id uuid-here \
        --correlation-id uuid-here \
        --reasoning "Selected based on workflow complexity"
"""

import argparse
import logging
import os
import sys
from datetime import UTC, datetime


# Add project root to path for config imports
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _PROJECT_ROOT)

# Add skills root to path for shared imports
_SKILLS_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _SKILLS_ROOT)

# Import directly from db_helper module to avoid __init__.py import chain issues
from _shared.db_helper import execute_query, get_correlation_id


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_routing_decision(
    agent: str,
    confidence: float,
    strategy: str,
    latency_ms: int,
    user_request: str,
    project_path: str,
    project_name: str,
    session_id: str,
    correlation_id: str,
    reasoning: str,
) -> str | None:
    """
    Log a routing decision to the database.

    Args:
        agent: Name of the selected agent
        confidence: Confidence score (0.0 - 1.0)
        strategy: Selection strategy used (event_routing, fuzzy_match, fallback)
        latency_ms: Routing latency in milliseconds
        user_request: Truncated user request
        project_path: Path to the project
        project_name: Name of the project
        session_id: Claude Code session ID
        correlation_id: Correlation ID for tracing
        reasoning: Reasoning for agent selection

    Returns:
        Event ID if logged successfully, None otherwise
    """
    sql = """
        INSERT INTO agent_routing_decisions (
            correlation_id,
            session_id,
            project_name,
            project_path,
            user_request,
            selected_agent,
            confidence_score,
            selection_strategy,
            latency_ms,
            reasoning,
            created_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
    """

    params = (
        correlation_id,
        session_id,
        project_name,
        project_path,
        user_request[:500] if user_request else "",  # Truncate to 500 chars
        agent,
        confidence,
        strategy,
        latency_ms,
        reasoning[:1000] if reasoning else "",  # Truncate to 1000 chars
        datetime.now(UTC),
    )

    result = execute_query(sql, params, fetch=True)

    if result["success"] and result["rows"]:
        event_id = str(result["rows"][0]["id"])
        logger.info(f"Routing decision logged: {event_id}")
        return event_id
    else:
        logger.error(f"Failed to log routing decision: {result.get('error')}")
        return None


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Log agent routing decision")
    parser.add_argument("--agent", required=True, help="Selected agent name")
    parser.add_argument(
        "--confidence", type=float, default=0.5, help="Confidence score (0.0-1.0)"
    )
    parser.add_argument("--strategy", default="unknown", help="Selection strategy used")
    parser.add_argument(
        "--latency-ms", type=int, default=0, help="Routing latency in milliseconds"
    )
    parser.add_argument("--user-request", default="", help="User request (truncated)")
    parser.add_argument("--project-path", default="", help="Project path")
    parser.add_argument("--project-name", default="", help="Project name")
    parser.add_argument("--session-id", default="", help="Session ID")
    parser.add_argument(
        "--correlation-id", default="", help="Correlation ID for tracing"
    )
    parser.add_argument("--reasoning", default="", help="Selection reasoning")

    args = parser.parse_args()

    # Use provided correlation ID or generate one
    correlation_id = args.correlation_id or get_correlation_id()

    event_id = log_routing_decision(
        agent=args.agent,
        confidence=args.confidence,
        strategy=args.strategy,
        latency_ms=args.latency_ms,
        user_request=args.user_request,
        project_path=args.project_path,
        project_name=args.project_name,
        session_id=args.session_id,
        correlation_id=correlation_id,
        reasoning=args.reasoning,
    )

    if event_id:
        print(f"Routing decision logged: {event_id}")
        sys.exit(0)
    else:
        print("Failed to log routing decision", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

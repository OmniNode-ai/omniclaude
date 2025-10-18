#!/usr/bin/env python3
"""
Session Intelligence Logger - Capture session lifecycle and aggregate statistics

Logs session start/end events to database with rich context:
- Session ID and project path
- Git branch and uncommitted changes
- Timestamp and environment metadata
- Session statistics (duration, prompts, tools, agents)
- Workflow pattern classification
- Performance tracking

Target: <50ms execution time for session metadata capture
"""

import sys
import os
import json
import argparse
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from pathlib import Path
import time

# Add hooks lib to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from hook_event_logger import HookEventLogger

# PostgreSQL connection (lazy import to avoid dependency issues)
try:
    import psycopg2

    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False


def get_git_metadata(cwd: str) -> Dict[str, Any]:
    """Extract git repository metadata.

    Args:
        cwd: Working directory to check for git repo

    Returns:
        Dict with git_branch, git_dirty, git_commit, git_remote
    """
    metadata = {"git_branch": None, "git_dirty": False, "git_commit": None, "git_remote": None, "is_git_repo": False}

    try:
        # Check if this is a git repository
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"], cwd=cwd, capture_output=True, text=True, timeout=1
        )

        if result.returncode != 0:
            return metadata

        metadata["is_git_repo"] = True

        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            metadata["git_branch"] = result.stdout.strip()

        # Check for uncommitted changes
        result = subprocess.run(["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, timeout=1)
        if result.returncode == 0:
            metadata["git_dirty"] = bool(result.stdout.strip())

        # Get current commit hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            metadata["git_commit"] = result.stdout.strip()

        # Get remote URL
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=cwd, capture_output=True, text=True, timeout=1
        )
        if result.returncode == 0:
            metadata["git_remote"] = result.stdout.strip()

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        # Gracefully handle git command failures
        print(f"⚠️  Git metadata extraction warning: {e}", file=sys.stderr)

    return metadata


def get_environment_metadata() -> Dict[str, Any]:
    """Extract environment metadata.

    Returns:
        Dict with user, hostname, platform, python_version
    """
    import platform

    metadata = {
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
        "hostname": platform.node(),
        "platform": platform.system(),
        "python_version": platform.python_version(),
        "shell": os.environ.get("SHELL"),
    }

    return metadata


def log_session_start(
    session_id: str, project_path: str, cwd: str, additional_metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Log session start event to database.

    Args:
        session_id: Unique session identifier
        project_path: Project root path
        cwd: Current working directory
        additional_metadata: Optional additional metadata

    Returns:
        Event ID if successful, None if failed
    """
    # Performance tracking
    start_time = time.time()

    try:
        # Initialize logger
        logger = HookEventLogger()

        # Get git metadata (fast - typically <20ms)
        git_metadata = get_git_metadata(cwd)

        # Get environment metadata (fast - <5ms)
        env_metadata = get_environment_metadata()

        # Build payload
        payload = {
            "session_id": session_id,
            "project_path": project_path,
            "cwd": cwd,
            "git_branch": git_metadata["git_branch"],
            "git_dirty": git_metadata["git_dirty"],
            "git_commit": git_metadata["git_commit"],
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

        # Build metadata
        metadata = {"hook_type": "SessionStart", "git_metadata": git_metadata, "environment": env_metadata}

        # Merge additional metadata if provided
        if additional_metadata:
            metadata.update(additional_metadata)

        # Log to database
        event_id = logger.log_event(
            source="SessionStart",
            action="session_initialized",
            resource="session",
            resource_id=session_id or "unknown",
            payload=payload,
            metadata=metadata,
        )

        # Performance check
        elapsed_ms = (time.time() - start_time) * 1000

        if event_id:
            print(f"✅ Session start logged: {event_id} ({elapsed_ms:.1f}ms)")

            # Warn if exceeded performance target
            if elapsed_ms > 50:
                print(f"⚠️  WARNING: Session logging exceeded 50ms target: {elapsed_ms:.1f}ms", file=sys.stderr)
        else:
            print(f"❌ Failed to log session start", file=sys.stderr)

        return event_id

    except Exception as e:
        # Graceful error handling - don't break user workflow
        elapsed_ms = (time.time() - start_time) * 1000
        print(f"❌ Session intelligence error ({elapsed_ms:.1f}ms): {e}", file=sys.stderr)
        return None


def get_session_start_time() -> Optional[datetime]:
    """Get session start time from correlation state file.

    Returns:
        Session start time or None if not found
    """
    try:
        state_file = Path.home() / ".claude" / "hooks" / ".state" / "correlation_id.json"
        if state_file.exists():
            with open(state_file, "r") as f:
                state = json.load(f)
                created_at = state.get("created_at")
                if created_at:
                    return datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except Exception as e:
        print(f"⚠️  Failed to get session start time: {e}", file=sys.stderr)

    return None


def query_session_statistics() -> Dict[str, Any]:
    """Query hook_events for session statistics.

    Returns:
        Dict with aggregated session statistics
    """
    if not PSYCOPG2_AVAILABLE:
        print(f"⚠️  psycopg2 not available, returning empty statistics", file=sys.stderr)
        return {
            "duration_seconds": 0,
            "total_prompts": 0,
            "total_tools": 0,
            "agents_invoked": [],
            "agent_usage": {},
            "tool_breakdown": {},
        }

    try:
        # Note: Set DB_PASSWORD environment variable for database access
        import os

        db_password = os.getenv("DB_PASSWORD", "")

        # Connect to database
        connection_string = (
            "host=localhost port=5436 " "dbname=omninode_bridge " "user=postgres " f"password={db_password}"
        )
        conn = psycopg2.connect(connection_string)

        # Get session start time from state file
        session_start = get_session_start_time()

        # If no session start time, use earliest event in last hour
        if session_start is None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MIN(created_at)
                    FROM hook_events
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                )
                result = cur.fetchone()
                session_start = result[0] if result and result[0] else datetime.now(timezone.utc)

        # Query statistics for current session
        with conn.cursor() as cur:
            # Count prompts
            cur.execute(
                """
                SELECT COUNT(*) as prompt_count
                FROM hook_events
                WHERE source = 'UserPromptSubmit'
                  AND created_at >= %s
            """,
                (session_start,),
            )
            prompt_count = cur.fetchone()[0]

            # Count tools
            cur.execute(
                """
                SELECT COUNT(*) as tool_count
                FROM hook_events
                WHERE source = 'PostToolUse'
                  AND created_at >= %s
            """,
                (session_start,),
            )
            tool_count = cur.fetchone()[0]

            # Get unique agents invoked
            cur.execute(
                """
                SELECT DISTINCT resource_id, COUNT(*) as usage_count
                FROM hook_events
                WHERE source = 'UserPromptSubmit'
                  AND created_at >= %s
                  AND resource_id != 'no_agent'
                GROUP BY resource_id
                ORDER BY usage_count DESC
            """,
                (session_start,),
            )
            agents_data = cur.fetchall()

            # Get tool usage breakdown
            cur.execute(
                """
                SELECT resource_id, COUNT(*) as count
                FROM hook_events
                WHERE source = 'PostToolUse'
                  AND created_at >= %s
                GROUP BY resource_id
                ORDER BY count DESC
                LIMIT 10
            """,
                (session_start,),
            )
            tool_breakdown = cur.fetchall()

        conn.close()

        # Calculate session duration
        session_end = datetime.now(timezone.utc)
        duration_seconds = (session_end - session_start).total_seconds()

        # Extract agent information
        agents_invoked = [agent[0] for agent in agents_data]
        agent_usage = {agent[0]: agent[1] for agent in agents_data}

        # Build statistics
        statistics = {
            "session_start": session_start.isoformat(),
            "session_end": session_end.isoformat(),
            "duration_seconds": int(duration_seconds),
            "total_prompts": prompt_count,
            "total_tools": tool_count,
            "agents_invoked": agents_invoked,
            "agent_usage": agent_usage,
            "tool_breakdown": {tool[0]: tool[1] for tool in tool_breakdown},
        }

        return statistics

    except Exception as e:
        print(f"⚠️  Failed to query session events: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return {
            "error": str(e),
            "duration_seconds": 0,
            "total_prompts": 0,
            "total_tools": 0,
            "agents_invoked": [],
            "agent_usage": {},
            "tool_breakdown": {},
        }


def classify_workflow_pattern(statistics: Dict[str, Any]) -> str:
    """Classify workflow pattern based on agent usage and tool patterns.

    Args:
        statistics: Session statistics dict

    Returns:
        Workflow pattern classification
    """
    agents_invoked = statistics.get("agents_invoked", [])
    agent_usage = statistics.get("agent_usage", {})
    tool_breakdown = statistics.get("tool_breakdown", {})

    # No agents detected
    if not agents_invoked:
        # Check tool usage
        if tool_breakdown.get("Read", 0) > tool_breakdown.get("Write", 0):
            return "exploration"
        return "direct_interaction"

    # Single agent invoked
    if len(agents_invoked) == 1:
        agent = agents_invoked[0]

        # Debug/testing patterns
        if any(keyword in agent.lower() for keyword in ["debug", "test", "diagnostic"]):
            return "debugging"

        # Code generation patterns
        if any(keyword in agent.lower() for keyword in ["code", "generator", "implement"]):
            return "feature_development"

        # Refactoring patterns
        if any(keyword in agent.lower() for keyword in ["refactor", "optimize", "architect"]):
            return "refactoring"

        return "specialized_task"

    # Multiple agents invoked
    # Check for specific patterns
    agent_names_lower = [a.lower() for a in agents_invoked]

    # Debugging workflow (debug + testing + code)
    if any("debug" in a for a in agent_names_lower) and any("test" in a for a in agent_names_lower):
        return "debugging"

    # Feature development workflow
    if any("code" in a or "generator" in a or "implement" in a for a in agent_names_lower):
        return "feature_development"

    # Architecture/refactoring workflow
    if any("architect" in a or "refactor" in a or "optimize" in a for a in agent_names_lower):
        return "refactoring"

    # Multi-agent exploration
    return "exploratory"


def log_session_end(
    session_id: Optional[str] = None, additional_metadata: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Log session end event and aggregate statistics.

    Args:
        session_id: Optional session ID (uses correlation_id if None)
        additional_metadata: Additional metadata to include

    Returns:
        Event ID if successful, None if failed
    """
    # Performance tracking
    start_time = time.time()

    try:
        import uuid
        from correlation_manager import get_correlation_id

        # Query session statistics
        statistics = query_session_statistics()

        # Classify workflow pattern
        workflow_pattern = classify_workflow_pattern(statistics)

        # Calculate session quality score (basic heuristic)
        # Higher prompts with fewer tools = more efficient
        # Multiple agents = more complex workflow
        quality_score = 0.5  # baseline

        if statistics["total_prompts"] > 0:
            tools_per_prompt = statistics["total_tools"] / statistics["total_prompts"]
            if tools_per_prompt < 3:
                quality_score += 0.2
            elif tools_per_prompt < 5:
                quality_score += 0.1

        if len(statistics.get("agents_invoked", [])) > 1:
            quality_score += 0.2  # Multi-agent coordination bonus

        quality_score = min(1.0, quality_score)

        # Use correlation_id as session_id if not provided
        if session_id is None:
            session_id = get_correlation_id() or str(uuid.uuid4())

        # Build event payload
        payload = {
            "duration_seconds": statistics.get("duration_seconds", 0),
            "total_prompts": statistics.get("total_prompts", 0),
            "total_tools": statistics.get("total_tools", 0),
            "agents_invoked": statistics.get("agents_invoked", []),
            "workflow_pattern": workflow_pattern,
            "agent_usage": statistics.get("agent_usage", {}),
            "tool_breakdown": statistics.get("tool_breakdown", {}),
            "session_start": statistics.get("session_start"),
            "session_end": statistics.get("session_end"),
        }

        # Build event metadata
        metadata = {
            "hook_type": "SessionEnd",
            "session_quality_score": quality_score,
            "workflow_pattern": workflow_pattern,
        }

        if additional_metadata:
            metadata.update(additional_metadata)

        # Log event to database
        logger = HookEventLogger()
        event_id = logger.log_event(
            source="SessionEnd",
            action="session_completed",
            resource="session",
            resource_id=session_id,
            payload=payload,
            metadata=metadata,
        )

        # Performance check
        elapsed_ms = (time.time() - start_time) * 1000

        if event_id:
            print(f"✅ Session end logged: {event_id} ({elapsed_ms:.1f}ms)")
            print(f"   Duration: {statistics.get('duration_seconds', 0)}s")
            print(f"   Prompts: {statistics.get('total_prompts', 0)}")
            print(f"   Tools: {statistics.get('total_tools', 0)}")
            print(f"   Pattern: {workflow_pattern}")
            print(f"   Quality: {quality_score:.2f}")

            # Warn if exceeded performance target
            if elapsed_ms > 50:
                print(f"⚠️  WARNING: Session end logging exceeded 50ms target: {elapsed_ms:.1f}ms", file=sys.stderr)
        else:
            print(f"❌ Failed to log session end", file=sys.stderr)

        return event_id

    except Exception as e:
        # Graceful error handling - don't break user workflow
        elapsed_ms = (time.time() - start_time) * 1000
        print(f"❌ Session end error ({elapsed_ms:.1f}ms): {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)
        return None


def main():
    """Command-line interface for session intelligence logging."""
    parser = argparse.ArgumentParser(description="Log session start/end intelligence to database")
    parser.add_argument("--mode", choices=["start", "end"], required=True, help="Session lifecycle mode (start or end)")
    parser.add_argument("--session-id", default=None, help="Session identifier (optional for end mode)")
    parser.add_argument("--project-path", default="", help="Project root path (for start mode)")
    parser.add_argument("--cwd", default="", help="Current working directory (for start mode)")
    parser.add_argument("--metadata", type=json.loads, default=None, help="Additional metadata as JSON")

    args = parser.parse_args()

    # Handle start mode
    if args.mode == "start":
        if not args.session_id:
            print("❌ --session-id required for start mode", file=sys.stderr)
            sys.exit(1)

        # Use current directory if cwd not provided
        cwd = args.cwd or os.getcwd()

        # Log session start
        event_id = log_session_start(
            session_id=args.session_id, project_path=args.project_path, cwd=cwd, additional_metadata=args.metadata
        )

    # Handle end mode
    elif args.mode == "end":
        # Log session end (session_id is optional, will use correlation_id if not provided)
        event_id = log_session_end(session_id=args.session_id, additional_metadata=args.metadata)

    # Exit with success even if logging failed (graceful degradation)
    sys.exit(0)


if __name__ == "__main__":
    main()

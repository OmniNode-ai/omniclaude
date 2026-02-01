#!/usr/bin/env python3
"""Session marker utilities for injection coordination.

Prevents duplicate pattern injection between SessionStart and UserPromptSubmit
by using marker files to track injection state per session.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Default marker directory (intentional temp usage for session-scoped markers)
DEFAULT_MARKER_DIR = "/tmp/omniclaude-sessions"  # noqa: S108  # nosec B108


def get_marker_path(session_id: str, marker_dir: str = DEFAULT_MARKER_DIR) -> Path:
    """Get the marker file path for a session.

    Args:
        session_id: The session ID (can be any string, will be sanitized)
        marker_dir: Directory for marker files

    Returns:
        Path to the marker file
    """
    # Sanitize session_id to be filesystem-safe
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return Path(marker_dir) / f"injected-{safe_id}"


def mark_session_injected(
    session_id: str,
    injection_id: str | None = None,
    marker_dir: str = DEFAULT_MARKER_DIR,
) -> bool:
    """Mark a session as having received pattern injection.

    Args:
        session_id: The session ID
        injection_id: Optional injection ID to store in marker
        marker_dir: Directory for marker files

    Returns:
        True if marker was created successfully
    """
    try:
        marker_path = get_marker_path(session_id, marker_dir)
        marker_path.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON with injection_id and timestamp for TTL support
        content = json.dumps(
            {
                "injection_id": injection_id or "",
                "timestamp": time.time(),
            }
        )
        marker_path.write_text(content)
        return True
    except OSError as e:
        logger.debug(
            "Failed to create session marker for %s: %s",
            session_id,
            e,
        )
        return False


def is_session_injected(
    session_id: str,
    marker_dir: str = DEFAULT_MARKER_DIR,
    max_age_hours: int = 24,
) -> bool:
    """Check if a session has already received pattern injection.

    Uses file modification time for staleness detection. Markers older than
    max_age_hours are considered stale and will return False, preventing
    stale markers from blocking injection on new sessions (e.g., after
    Claude Code crashes or is force-quit).

    Args:
        session_id: The session ID
        marker_dir: Directory for marker files
        max_age_hours: Maximum age in hours before marker is considered stale

    Returns:
        True if session was already injected and marker is not stale
    """
    marker_path = get_marker_path(session_id, marker_dir)
    if marker_path.exists():
        try:
            age_hours = (time.time() - marker_path.stat().st_mtime) / 3600
            return age_hours < max_age_hours
        except OSError as e:
            logger.debug(
                "Failed to check marker age for %s: %s",
                session_id,
                e,
            )
            # If we can't check the age, assume marker is valid
            return True
    return False


def get_session_injection_id(
    session_id: str,
    marker_dir: str = DEFAULT_MARKER_DIR,
) -> str | None:
    """Get the injection_id for a previously injected session.

    Handles both JSON format (new) and plain text format (backward compatibility).

    Args:
        session_id: The session ID
        marker_dir: Directory for marker files

    Returns:
        The injection_id if found, None otherwise
    """
    marker_path = get_marker_path(session_id, marker_dir)
    if marker_path.exists():
        content = marker_path.read_text().strip()
        if not content:
            return None

        # Try JSON format first (new format with timestamp)
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                injection_id = data.get("injection_id", "")
                return injection_id if injection_id else None
        except json.JSONDecodeError:
            pass

        # Fall back to plain text format (backward compatibility)
        return content if content else None
    return None


def clear_session_marker(
    session_id: str,
    marker_dir: str = DEFAULT_MARKER_DIR,
) -> bool:
    """Clear the injection marker for a session.

    Called during SessionEnd to clean up.

    Args:
        session_id: The session ID
        marker_dir: Directory for marker files

    Returns:
        True if marker was removed (or didn't exist)
    """
    try:
        marker_path = get_marker_path(session_id, marker_dir)
        marker_path.unlink(missing_ok=True)
        return True
    except OSError as e:
        logger.debug(
            "Failed to clear session marker for %s: %s",
            session_id,
            e,
        )
        return False


# CLI interface for shell scripts
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Session marker utilities")
    parser.add_argument("command", choices=["mark", "check", "clear", "get-id"])
    parser.add_argument("--session-id", required=True, help="Session ID")
    parser.add_argument("--injection-id", help="Injection ID (for mark command)")
    parser.add_argument("--marker-dir", default=DEFAULT_MARKER_DIR)
    parser.add_argument(
        "--max-age-hours",
        type=int,
        default=24,
        help="Max age in hours before marker is stale (for check command)",
    )

    args = parser.parse_args()

    if args.command == "mark":
        success = mark_session_injected(
            args.session_id, args.injection_id, args.marker_dir
        )
        sys.exit(0 if success else 1)
    elif args.command == "check":
        injected = is_session_injected(
            args.session_id, args.marker_dir, args.max_age_hours
        )
        print("true" if injected else "false")
        sys.exit(0 if injected else 1)
    elif args.command == "clear":
        success = clear_session_marker(args.session_id, args.marker_dir)
        sys.exit(0 if success else 1)
    elif args.command == "get-id":
        injection_id = get_session_injection_id(args.session_id, args.marker_dir)
        if injection_id:
            print(injection_id)
            sys.exit(0)
        sys.exit(1)

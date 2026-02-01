#!/usr/bin/env python3
"""Session marker utilities for injection coordination.

Prevents duplicate pattern injection between SessionStart and UserPromptSubmit
by using marker files to track injection state per session.
"""

from __future__ import annotations

import logging
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

        # Write injection_id if provided, otherwise empty file
        content = injection_id or ""
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
) -> bool:
    """Check if a session has already received pattern injection.

    Args:
        session_id: The session ID
        marker_dir: Directory for marker files

    Returns:
        True if session was already injected
    """
    marker_path = get_marker_path(session_id, marker_dir)
    return marker_path.exists()


def get_session_injection_id(
    session_id: str,
    marker_dir: str = DEFAULT_MARKER_DIR,
) -> str | None:
    """Get the injection_id for a previously injected session.

    Args:
        session_id: The session ID
        marker_dir: Directory for marker files

    Returns:
        The injection_id if found, None otherwise
    """
    marker_path = get_marker_path(session_id, marker_dir)
    if marker_path.exists():
        content = marker_path.read_text().strip()
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

    args = parser.parse_args()

    if args.command == "mark":
        success = mark_session_injected(
            args.session_id, args.injection_id, args.marker_dir
        )
        sys.exit(0 if success else 1)
    elif args.command == "check":
        injected = is_session_injected(args.session_id, args.marker_dir)
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

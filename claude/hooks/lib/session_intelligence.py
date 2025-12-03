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
from pathlib import Path
from typing import Any, Dict, Optional


# Ensure project root is in path for imports
# This file is at: claude/hooks/lib/session_intelligence.py
# Project root is 3 levels up: lib -> hooks -> claude -> project_root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ONEX error handling - import for structured error logging
# Use Any type for optional imports to satisfy mypy while allowing runtime flexibility
from typing import Any as _AnyType


_OnexError: _AnyType = None
_EnumCoreErrorCode: _AnyType = None

try:
    from claude.lib.core import EnumCoreErrorCode, OnexError

    _OnexError = OnexError
    _EnumCoreErrorCode = EnumCoreErrorCode
except ImportError:
    try:
        from agents.lib.errors import EnumCoreErrorCode, OnexError

        _OnexError = OnexError
        _EnumCoreErrorCode = EnumCoreErrorCode
    except ImportError:
        # Minimal fallback if neither import works
        pass


# Reserved payload fields that metadata cannot overwrite
# These fields are protected to ensure event integrity and traceability
_RESERVED_PAYLOAD_FIELDS = frozenset(
    {
        "session_id",  # Core session identifier
        "timestamp",  # Event timing (set by system)
        "project_path",  # Session context
        "cwd",  # Session context
        "event_type",  # Event classification (reserved for internal use)
        "correlation_id",  # Event correlation chain
        "source",  # Event source identifier
        "action",  # Event action type
    }
)


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
        event_id: str | None = logger_instance.log_event(
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
    except (OSError, IOError) as e:
        # I/O errors during logging - use OnexError for structured logging
        error_code = _EnumCoreErrorCode.IO_ERROR if _EnumCoreErrorCode else "IO_ERROR"
        logger.error(
            f"[{error_code}] Failed to log session start (I/O error): {e}",
            extra={"error_code": str(error_code), "session_id": session_id},
        )
        return None
    except Exception as e:
        # Unexpected error - wrap in OnexError for structured error handling
        if _OnexError is not None and _EnumCoreErrorCode is not None:
            onex_error = _OnexError(
                code=_EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to log session start: {e}",
                details={
                    "session_id": session_id,
                    "exception_type": type(e).__name__,
                    "original_error": str(e),
                },
            )
            logger.error(
                str(onex_error),
                extra={
                    "error_code": str(onex_error.code),
                    "session_id": session_id,
                    "details": onex_error.details,
                },
            )
        else:
            # Fallback if OnexError not available
            logger.error(
                f"[OPERATION_FAILED] Failed to log session start: {type(e).__name__}: {e}",
                extra={"error_code": "OPERATION_FAILED", "session_id": session_id},
            )
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

        # Filter metadata to prevent overwriting reserved fields
        # Warn if metadata contains reserved fields (helps debug accidental overwrites)
        raw_metadata = metadata or {}
        conflicting_keys = set(raw_metadata.keys()) & _RESERVED_PAYLOAD_FIELDS
        if conflicting_keys:
            logger.warning(
                f"Metadata contains reserved payload fields that will be ignored: "
                f"{conflicting_keys}. These fields are protected: {_RESERVED_PAYLOAD_FIELDS}"
            )

        safe_metadata = {
            k: v for k, v in raw_metadata.items() if k not in _RESERVED_PAYLOAD_FIELDS
        }

        event_id: str | None = logger_instance.log_event(
            source="SessionEnd",
            action="session_completed",
            resource="session",
            resource_id=session_id,
            # Double-defense: spread metadata FIRST, then set core fields AFTER
            # This ensures core fields always win even if filtering misses something
            payload={
                **safe_metadata,
                "session_id": session_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
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
    except (OSError, IOError) as e:
        # I/O errors during logging - use OnexError for structured logging
        error_code = _EnumCoreErrorCode.IO_ERROR if _EnumCoreErrorCode else "IO_ERROR"
        logger.error(
            f"[{error_code}] Failed to log session end (I/O error): {e}",
            extra={"error_code": str(error_code), "session_id": session_id},
        )
        return None
    except Exception as e:
        # Unexpected error - wrap in OnexError for structured error handling
        if _OnexError is not None and _EnumCoreErrorCode is not None:
            onex_error = _OnexError(
                code=_EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to log session end: {e}",
                details={
                    "session_id": session_id,
                    "exception_type": type(e).__name__,
                    "original_error": str(e),
                },
            )
            logger.error(
                str(onex_error),
                extra={
                    "error_code": str(onex_error.code),
                    "session_id": session_id,
                    "details": onex_error.details,
                },
            )
        else:
            # Fallback if OnexError not available
            logger.error(
                f"[OPERATION_FAILED] Failed to log session end: {type(e).__name__}: {e}",
                extra={"error_code": "OPERATION_FAILED", "session_id": session_id},
            )
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

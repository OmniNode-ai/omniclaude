#!/usr/bin/env python3
"""
Response Intelligence - Response Completion Event Logging

Logs response completion events including tools executed and completion status.
Called by stop.sh hook.
"""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type


# Add script directory to path for sibling imports
# This enables imports like 'from hook_event_logger import ...' to work
# regardless of the current working directory
_SCRIPT_DIR = Path(__file__).parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# Import HookEventLogger with graceful fallback
_HookEventLoggerClass: Optional[Type[Any]] = None
try:
    from hook_event_logger import HookEventLogger

    _HookEventLoggerClass = HookEventLogger
except ImportError:
    _HookEventLoggerClass = None


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_response_completion(
    session_id: str,
    tools_executed: Optional[List[str]] = None,
    completion_status: str = "complete",
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Log response completion event with execution summary.

    Args:
        session_id: Session identifier
        tools_executed: List of tool names executed during response
        completion_status: Completion status (complete, interrupted, error)
        metadata: Additional metadata

    Returns:
        Event ID if logged successfully, None otherwise
    """
    try:
        # Use pre-imported class for graceful degradation
        if _HookEventLoggerClass is None:
            logger.warning("HookEventLogger not available (import failed)")
            return None

        logger_instance = _HookEventLoggerClass()

        # Build payload
        payload = {
            "session_id": session_id,
            "completion_status": completion_status,
            "tools_executed": tools_executed or [],
            "tool_count": len(tools_executed) if tools_executed else 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Merge additional metadata
        event_metadata = {
            "hook_type": "Stop",
            "session_id": session_id,
            "completion_status": completion_status,
        }
        if metadata:
            event_metadata.update(metadata)

        event_id = logger_instance.log_event(
            source="Stop",
            action="response_completed",
            resource="response",
            resource_id=session_id,
            payload=payload,
            metadata=event_metadata,
        )

        logger.info(
            f"Response completion logged: {event_id} "
            f"(status={completion_status}, tools={len(tools_executed or [])})"
        )
        return event_id

    except Exception as e:
        logger.error(f"Failed to log response completion: {e}")
        return None

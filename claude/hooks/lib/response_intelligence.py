#!/usr/bin/env python3
"""
Response Intelligence - Response Completion Event Logging

Logs response completion events including tools executed and completion status.
Called by stop.sh hook.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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
        # Import here to avoid circular imports and allow graceful degradation
        from hook_event_logger import HookEventLogger

        logger_instance = HookEventLogger()

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

    except ImportError as e:
        logger.warning(f"HookEventLogger not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to log response completion: {e}")
        return None

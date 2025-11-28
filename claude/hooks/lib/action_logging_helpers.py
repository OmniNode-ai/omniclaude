#!/usr/bin/env python3
"""
Action Logging Helpers - Convenience functions for logging agent actions

Provides helper functions for common logging patterns used across hooks.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def log_error(
    error_type: str,
    error_message: str,
    error_context: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """
    Log an error event to the database.

    Args:
        error_type: Type/category of error (e.g., "ToolExecutionError")
        error_message: Human-readable error description
        error_context: Additional context (tool info, stack trace, etc.)
        correlation_id: Correlation ID for tracing

    Returns:
        Event ID if logged successfully, None otherwise
    """
    try:
        # Import here to avoid circular imports
        from hook_event_logger import HookEventLogger

        logger_instance = HookEventLogger()

        payload = {
            "error_type": error_type,
            "error_message": error_message,
            "error_context": error_context or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        metadata = {
            "hook_type": "ErrorHandler",
            "error_type": error_type,
        }
        if correlation_id:
            metadata["correlation_id"] = correlation_id

        event_id = logger_instance.log_event(
            source="ErrorHandler",
            action="error_logged",
            resource="error",
            resource_id=error_type,
            payload=payload,
            metadata=metadata,
        )

        logger.info(f"Error logged: {error_type} - {error_message[:100]}")
        return event_id

    except ImportError as e:
        logger.warning(f"HookEventLogger not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to log error: {e}")
        return None


def log_success(
    action_name: str,
    action_result: Optional[Dict[str, Any]] = None,
    correlation_id: Optional[str] = None,
) -> Optional[str]:
    """
    Log a successful action completion.

    Args:
        action_name: Name of the completed action
        action_result: Result/output of the action
        correlation_id: Correlation ID for tracing

    Returns:
        Event ID if logged successfully, None otherwise
    """
    try:
        from hook_event_logger import HookEventLogger

        logger_instance = HookEventLogger()

        payload = {
            "action_name": action_name,
            "action_result": action_result or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        metadata = {
            "hook_type": "SuccessHandler",
            "action_name": action_name,
        }
        if correlation_id:
            metadata["correlation_id"] = correlation_id

        event_id = logger_instance.log_event(
            source="SuccessHandler",
            action="success_logged",
            resource="action",
            resource_id=action_name,
            payload=payload,
            metadata=metadata,
        )

        logger.info(f"Success logged: {action_name}")
        return event_id

    except ImportError as e:
        logger.warning(f"HookEventLogger not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to log success: {e}")
        return None

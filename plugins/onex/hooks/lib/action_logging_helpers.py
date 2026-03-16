#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Action Logging Helpers - Convenience functions for logging agent actions

Stub module retained for compatibility.  The PostgreSQL HookEventLogger
that previously powered log_error / log_success was removed in OMN-5139
(Kafka is the canonical observability path).  The functions now return
None immediately.
"""

import logging
from typing import Any

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
    error_context: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> str | None:
    """Log an error event.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for compat.
    """
    logger.info("Error logging skipped (PostgreSQL logger removed in OMN-5139)")
    return None


def log_success(
    action_name: str,
    action_result: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> str | None:
    """Log a successful action completion.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for compat.
    """
    logger.info("Success logging skipped (PostgreSQL logger removed in OMN-5139)")
    return None

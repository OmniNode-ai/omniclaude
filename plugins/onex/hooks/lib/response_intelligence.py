#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Response Intelligence - Response Completion Event Logging

Stub module retained for stop.sh CLI compatibility.  The PostgreSQL
HookEventLogger that previously powered log_response_completion was removed
in OMN-5139 (Kafka is the canonical observability path).  The function now
returns None immediately.
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


def log_response_completion(
    session_id: str,
    tools_executed: list[str] | None = None,
    completion_status: str = "complete",
    metadata: dict[str, Any]  # ONEX_EXCLUDE: dict_str_any - generic metadata container
    | None = None,
) -> str | None:
    """Log response completion event.

    No-op after OMN-5139 (PostgreSQL logger removed). Retained for CLI compat.
    """
    logger.info(
        "Response completion event skipped (PostgreSQL logger removed in OMN-5139)"
    )
    return None

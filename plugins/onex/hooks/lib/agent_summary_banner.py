#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Agent Summary Banner - Display execution summary at response completion

Displays a summary banner showing tools executed and completion status.
Called by stop.sh hook.
"""

import logging
import sys
from datetime import UTC, datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def display_summary_banner(
    tools_executed: list[str] | None = None,
    completion_status: str = "complete",
) -> None:
    """
    Display execution summary banner to stderr.

    Args:
        tools_executed: List of tool names executed during response
        completion_status: Completion status (complete, interrupted, error)
    """
    tools = tools_executed or []
    tool_count = len(tools)

    # Status emoji mapping
    status_emoji = {
        "complete": "[OK]",
        "interrupted": "[!]",
        "error": "[X]",
        "cancelled": "[!]",
    }.get(completion_status, "[?]")

    # Build summary banner
    banner_lines = [
        "",
        "=" * 60,
        f"  {status_emoji} Response {completion_status.upper()}",
        "=" * 60,
        f"  Tools Executed: {tool_count}",
    ]

    # Add tool list if any tools were executed
    if tools:
        unique_tools = sorted(set(tools))
        banner_lines.append(f"  Tool Types: {', '.join(unique_tools)}")

    banner_lines.extend(
        [
            f"  Timestamp: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "=" * 60,
            "",
        ]
    )

    # Print to stderr (visible to user but doesn't affect stdout)
    for line in banner_lines:
        print(line, file=sys.stderr)

    logger.debug(f"Summary banner displayed: {completion_status}, {tool_count} tools")

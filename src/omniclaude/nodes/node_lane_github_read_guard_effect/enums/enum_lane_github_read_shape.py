# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Which GitHub read path a tool call takes around the gh shim (OMN-20916)."""

from enum import StrEnum


class EnumLaneGithubReadShape(StrEnum):
    """The three bypass paths the guard judges, and none."""

    NONE = "NONE"
    """The call reaches GitHub by none of the three paths."""

    MCP_TOOL = "MCP_TOOL"
    """A GitHub MCP server tool (AC1)."""

    RAW_API = "RAW_API"
    """curl, wget, a script interpreter or similar reaching api.github.com directly (AC2)."""

    REAL_GH = "REAL_GH"
    """The real gh binary run by its path instead of the shim on PATH (AC3)."""

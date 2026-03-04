# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Shared normalization helpers for hook event emission.

Centralized normalization utilities used by all
hook emitters to produce consistent, human-readable action descriptions.

See OMN-3297 for the specification of action_description normalization.
"""

from __future__ import annotations

__all__ = ["normalize_action_description"]

ACTION_DESCRIPTION_MAX_LENGTH: int = 160


def normalize_action_description(s: str) -> str:
    """Truncate to 160 chars and strip newlines. Never raises.

    Args:
        s: Raw action description string.

    Returns:
        Normalized string with newlines replaced by spaces and length
        capped at ACTION_DESCRIPTION_MAX_LENGTH (160 chars).

    Examples:
        >>> normalize_action_description("")
        ''
        >>> normalize_action_description("Read: topics.py")
        'Read: topics.py'
        >>> normalize_action_description("line1\\nline2")
        'line1 line2'
        >>> normalize_action_description("x" * 200)
        'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
    """
    return s.replace("\n", " ").replace("\r", " ")[:ACTION_DESCRIPTION_MAX_LENGTH]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Enum for chat message severity levels.

Severity determines visual rendering priority in the /chat reader
and controls filtering thresholds for noisy channels.
"""

from __future__ import annotations

from enum import StrEnum


class EnumChatSeverity(StrEnum):
    """Severity levels for agent chat messages.

    Attributes:
        INFO: Informational — routine status updates, progress notes.
        WARN: Warning — non-blocking issues that deserve attention.
        ERROR: Error — failures that may require human intervention.
        CRITICAL: Critical — pipeline-stopping events requiring immediate action.
    """

    INFO = "INFO"
    WARN = "WARN"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


__all__ = ["EnumChatSeverity"]

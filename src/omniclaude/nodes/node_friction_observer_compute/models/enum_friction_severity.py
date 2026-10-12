# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Severity levels a friction classification rule may assign."""

from __future__ import annotations

from enum import StrEnum


class EnumFrictionSeverity(StrEnum):
    """Severity of an observed friction event."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


__all__ = ["EnumFrictionSeverity"]

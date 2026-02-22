# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Enum for sandbox constraint levels in ticket policy envelopes."""

from __future__ import annotations

from enum import Enum


class EnumSandboxLevel(str, Enum):
    """Sandbox constraint levels for ticket execution.

    Controls what resources and permissions are available when executing
    the ticket's work.
    """

    NONE = "NONE"
    STANDARD = "STANDARD"
    ENFORCED = "ENFORCED"
    ISOLATED = "ISOLATED"


__all__ = ["EnumSandboxLevel"]

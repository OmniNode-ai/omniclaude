# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Per-AC verdict recorded in an evidence bundle."""

from __future__ import annotations

from enum import Enum


class EnumAcVerdict(str, Enum):
    """Result of evaluating a single acceptance criterion.

    PASS    — criterion was verified and met.
    FAIL    — criterion was verified and not met.
    SKIPPED — criterion was not evaluated (e.g. execution halted early).
    ERROR   — verification raised an unexpected exception.
    """

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


__all__ = ["EnumAcVerdict"]

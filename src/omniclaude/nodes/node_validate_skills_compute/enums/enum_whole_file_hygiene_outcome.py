# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The three outcomes of the whole-file hygiene leg (OMN-22273)."""

from __future__ import annotations

from enum import StrEnum


class EnumWholeFileHygieneOutcome(StrEnum):
    """CLEAN exits 0, DETECTED exits 1, CONFIG_ERROR exits 2.

    CONFIG_ERROR means the leg did not run to a verdict (a missing vocabulary,
    an unreadable scrub map, an empty scope). It is never a detection and never
    a pass.
    """

    CLEAN = "clean"
    DETECTED = "detected"
    CONFIG_ERROR = "config-error"

    @property
    def exit_code(self) -> int:
        return _EXIT_CODES[self]


_EXIT_CODES: dict[EnumWholeFileHygieneOutcome, int] = {
    EnumWholeFileHygieneOutcome.CLEAN: 0,
    EnumWholeFileHygieneOutcome.DETECTED: 1,
    EnumWholeFileHygieneOutcome.CONFIG_ERROR: 2,
}

__all__ = ["EnumWholeFileHygieneOutcome"]

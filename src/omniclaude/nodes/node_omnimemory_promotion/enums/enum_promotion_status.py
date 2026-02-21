# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Status of a pattern promotion attempt."""

from __future__ import annotations

from enum import Enum


class EnumPromotionStatus(str, Enum):
    """Outcome of an OmniMemory pattern promotion attempt.

    PROMOTED        — pattern was newly promoted and written to OmniMemory.
    VERSION_BUMPED  — pattern already existed; evidence count incremented.
    SKIPPED         — pattern does not meet promotion criteria yet.
    ALREADY_CURRENT — pattern is already promoted at the same version; no-op.
    """

    PROMOTED = "PROMOTED"
    VERSION_BUMPED = "VERSION_BUMPED"
    SKIPPED = "SKIPPED"
    ALREADY_CURRENT = "ALREADY_CURRENT"


__all__ = ["EnumPromotionStatus"]

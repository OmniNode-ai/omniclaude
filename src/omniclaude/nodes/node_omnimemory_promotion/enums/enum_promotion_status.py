# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Status of a pattern promotion attempt."""

from __future__ import annotations

from enum import StrEnum


class EnumPromotionStatus(StrEnum):
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

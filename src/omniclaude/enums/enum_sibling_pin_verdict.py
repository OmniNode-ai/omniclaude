# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The internal-sibling-pins check's verdict on one pin (OMN-21282)."""

from __future__ import annotations

from enum import StrEnum


class EnumSiblingPinVerdict(StrEnum):
    """STANDING is a release pin the change under review does not move."""

    ALLOWED = "allowed"
    STANDING = "standing"
    REFUSED = "refused"


__all__ = ["EnumSiblingPinVerdict"]

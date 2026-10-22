# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""How a lock file pins an internal OmniNode sibling (OMN-21282)."""

from __future__ import annotations

from enum import StrEnum


class EnumSiblingPinKind(StrEnum):
    """RELEASE and RELEASE_TAG are the release-version pins the check judges."""

    DEV_TAG = "dev_tag"
    RELEASE = "release"
    RELEASE_TAG = "release_tag"
    REV = "rev"


__all__ = ["EnumSiblingPinKind"]

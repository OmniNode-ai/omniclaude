# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What the claims directory says about one target (OMN-20685)."""

from enum import StrEnum


class EnumPrClaimStatus(StrEnum):
    """A claim read, with an unreadable file kept distinct from an absent one."""

    ABSENT = "absent"
    ACTIVE = "active"
    EXPIRED = "expired"
    UNREADABLE = "unreadable"

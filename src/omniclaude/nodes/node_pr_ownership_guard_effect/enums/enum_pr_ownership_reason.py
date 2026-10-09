# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Why the ownership gate allowed or refused one mutation (OMN-20685)."""

from enum import StrEnum


class EnumPrOwnershipReason(StrEnum):
    """The verdict codes the refusal log and the shell wrapper read."""

    OWNED_BY_SELF = "OWNED_BY_SELF"
    FIRST_WRITER = "FIRST_WRITER"
    CROSS_LANE = "CROSS_LANE"
    CROSS_RUN = "CROSS_RUN"
    UNCLAIMED = "UNCLAIMED"
    INDETERMINATE_LANE = "INDETERMINATE_LANE"
    INDETERMINATE_TARGET = "INDETERMINATE_TARGET"
    INDETERMINATE_CLAIM = "INDETERMINATE_CLAIM"

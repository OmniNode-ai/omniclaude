# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The two kinds of guarded GitHub mutation (OMN-16485, OMN-20685)."""

from enum import StrEnum


class EnumPrMutationClass(StrEnum):
    """What a mutation puts at risk, which decides how an absent claim reads."""

    OWNERSHIP = "ownership"
    """Destroys a peer's work (close, reopen): an absent claim refuses."""

    EXCLUSIVITY = "exclusivity"
    """Duplicates a peer's action (dispatch, cancel): the first writer wins."""

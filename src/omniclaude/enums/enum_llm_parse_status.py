# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""How one LLM call's reply was read (OMN-26353)."""

from __future__ import annotations

from enum import StrEnum


class EnumLlmParseStatus(StrEnum):
    """PARSED: the reply held a usable answer.

    UNPARSABLE: the endpoint replied, but the reply holds no usable answer.
    UNAVAILABLE: no reply was read (timeout, connection or HTTP failure).
    """

    PARSED = "parsed"
    UNPARSABLE = "unparsable"
    UNAVAILABLE = "unavailable"


__all__ = ["EnumLlmParseStatus"]

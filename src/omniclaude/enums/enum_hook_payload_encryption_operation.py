# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What a payload encryption request asks for (OMN-19513)."""

from __future__ import annotations

from enum import StrEnum


class EnumHookPayloadEncryptionOperation(StrEnum):
    """CHECK resolves the key and seals nothing; SEAL and OPEN transform a payload."""

    CHECK = "check"
    SEAL = "seal"
    OPEN = "open"


__all__ = ["EnumHookPayloadEncryptionOperation"]

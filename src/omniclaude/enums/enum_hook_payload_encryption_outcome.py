# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""How a payload encryption request ended (OMN-19513)."""

from __future__ import annotations

from enum import StrEnum


class EnumHookPayloadEncryptionOutcome(StrEnum):
    """REFUSED carries a reason that names a cause, never a key or content."""

    READY = "ready"
    SEALED = "sealed"
    OPENED = "opened"
    REFUSED = "refused"


__all__ = ["EnumHookPayloadEncryptionOutcome"]

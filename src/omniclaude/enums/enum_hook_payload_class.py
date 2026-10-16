# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The capture classes whose payload can be sealed (OMN-19513)."""

from __future__ import annotations

from enum import StrEnum


class EnumHookPayloadClass(StrEnum):
    """The journal event type of the payload; its readable fields differ per class."""

    HOOK_EVENT = "hook.event"
    CONTENT_CAPTURED = "content.captured"


__all__ = ["EnumHookPayloadClass"]

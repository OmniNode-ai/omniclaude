# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What a private value becomes in the scrub map (OMN-22273)."""

from __future__ import annotations

from enum import StrEnum


class EnumScrubMapKeyKind(StrEnum):
    """The destination kind of one scrub-map row."""

    OVERLAY_KEY = "overlay-key"
    ENV_VAR = "env-var"
    RELATIVE_PATH = "relative-path"
    NOT_REWRITTEN = "not-rewritten"


__all__ = ["EnumScrubMapKeyKind"]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

from enum import StrEnum


class EnumCliRecipient(StrEnum):
    CLAUDE = "claude"
    OPENCODE = "opencode"
    CODEX = "codex"


__all__ = ["EnumCliRecipient"]

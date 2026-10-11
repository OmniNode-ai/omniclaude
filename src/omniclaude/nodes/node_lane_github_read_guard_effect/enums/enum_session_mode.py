# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The session's omniclaude_mode, as plugins/onex/lib/mode.sh reports it (OMN-20916)."""

from enum import StrEnum


class EnumSessionMode(StrEnum):
    """FULL inside the OmniNode workspace; LITE for a non-OmniNode install, which has no lanes."""

    FULL = "full"
    LITE = "lite"

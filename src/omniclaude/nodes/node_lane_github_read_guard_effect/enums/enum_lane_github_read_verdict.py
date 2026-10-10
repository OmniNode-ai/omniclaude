# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The guard's verdict for one tool call (OMN-20916)."""

from enum import StrEnum


class EnumLaneGithubReadVerdict(StrEnum):
    """ALLOW lets the tool call run; REFUSE blocks it with the local reader named."""

    ALLOW = "ALLOW"
    REFUSE = "REFUSE"

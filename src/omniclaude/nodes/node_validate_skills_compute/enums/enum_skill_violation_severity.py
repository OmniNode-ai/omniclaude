# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Severity levels for skill validation violations."""

from enum import StrEnum


class EnumSkillViolationSeverity(StrEnum):
    """Severity of a skill validation violation."""

    ERROR = "ERROR"
    WARNING = "WARNING"

# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Shared skill node models — request and result."""

from .model_skill_request import ModelSkillRequest
from .model_skill_result import ModelSkillResult, SkillResultStatus

__all__ = [
    "ModelSkillRequest",
    "ModelSkillResult",
    "SkillResultStatus",
]

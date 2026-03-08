# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Shared skill node infrastructure — handler, request model, result model.

All skill-dispatch nodes import from this package. It provides the canonical
request/result models and the single shared handler that dispatches any skill
to the polymorphic agent (Polly).

Exported Components:
    Models:
        ModelSkillRequest - Input to any skill dispatch node
        ModelSkillResult  - Output from any skill dispatch node
        SkillResult       - Alias for ModelSkillResult (omnibase_core naming)
        SkillResultStatus - Enum of possible skill result statuses

    Handler:
        handle_skill_requested - Async handler; dispatches skill to Polly
"""

from .handler_skill_requested import handle_skill_requested
from .models import ModelSkillRequest, ModelSkillResult, SkillResult, SkillResultStatus

__all__ = [
    # Models
    "ModelSkillRequest",
    "ModelSkillResult",
    "SkillResult",
    "SkillResultStatus",
    # Handler
    "handle_skill_requested",
]

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A comment reply and the route that actually produced it."""

from omniclaude.nodes.node_skill_comment_sweep_orchestrator.models.model_render_delegation import (
    ModelRenderDelegation,
)
from omniclaude.shared.models.model_skill_result import ModelSkillResult


class ModelCommentSweepResult(ModelSkillResult):
    """Rendering never loses the work-side fallback record."""

    render_delegation: ModelRenderDelegation | None = None

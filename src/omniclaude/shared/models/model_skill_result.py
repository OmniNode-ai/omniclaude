# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Skill dispatch result model (omniclaude-owned, OMN-13894).

``ModelSkillResult`` is the lightweight result envelope every omniclaude skill
dispatch node (``handle_skill_requested``, the claude-code-session backends, the
local-llm-inference backends) returns: a skill name, a canonical status, and a
free-form ``extra`` string map carrying the skill ``output`` and/or ``error``.

Why this is a LOCAL model (OMN-13894)
-------------------------------------
Historically this module re-exported ``ModelSkillResult`` from omnibase_core
(``omnibase_core.models.skill.model_skill_result``, OMN-3867). That path was
removed in omnibase_core 0.45.0+: ``models.skill`` now only ships
``ModelSkillResultFile``, and a *different* ``ModelSkillResult`` was introduced
at ``omnibase_core.models.dispatch.model_skill_result``. The dispatch model is a
**receipt-mode CLI dispatch envelope** (per its own docstring: "the single typed
JSON object a receipt-mode dispatch prints to stdout") — it requires
``node_name``, ``run_id``, ``exit_code``, ``duration_ms``, ``result`` and a fully
qualified ``result_model`` FQN. That surface is unrelated to omniclaude's
internal effect-node result; adopting it would force every backend call site to
fabricate meaningless receipt fields (``exit_code=0``, ``run_id=uuid4()``,
``result_model="builtins.str"``).

The correct migration decouples omniclaude's internal result type from core's
receipt envelope. Only the shared status *vocabulary*
(``EnumSkillResultStatus``) stays sourced from core — that enum is stable and
still exported in 0.46.x. This keeps the exact ``{skill_name, status, extra}``
shape every existing call site and consumer already uses, so the omnibase_core
bump to 0.46.4 (needed for ``omnibase_core.validation.no_faked_boundary``) lands
without churning dispatch code. See OMN-13894 / OMN-13501 / OMN-13502.
"""

from __future__ import annotations

from omnibase_core.enums.enum_skill_result_status import (
    EnumSkillResultStatus as SkillResultStatus,
)
from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModelSkillResult", "SkillResult", "SkillResultStatus"]


class ModelSkillResult(BaseModel):
    """Result of a single omniclaude skill invocation.

    Attributes:
        skill_name: Human-readable skill identifier matching the request.
        status: Final status of the skill invocation.
        extra: Free-form string map. Conventionally carries ``"output"``
            (raw skill output) and/or ``"error"`` (error detail). Consumers
            read ``result.extra.get("output")`` / ``result.extra.get("error")``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", from_attributes=True)

    skill_name: str = Field(
        ...,
        min_length=1,
        description="Human-readable skill identifier matching the request",
    )
    status: SkillResultStatus = Field(
        ...,
        description="Final status of the skill invocation",
    )
    extra: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Free-form string map carrying the skill output and/or error "
            "detail (conventional keys: 'output', 'error')"
        ),
    )


#: Alias retained for callers that imported ``SkillResult`` from this module.
SkillResult = ModelSkillResult

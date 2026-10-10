# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The verdict for one guarded mutation (OMN-20685).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_pr_ownership_guard_effect.enums import EnumPrOwnershipReason


class ModelPrOwnershipDecision(BaseModel):
    """Allowed or refused, and the sentence that tells the lane what to do next."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason_code: EnumPrOwnershipReason
    message: str
    verb: str
    target_key: str | None
    record_claim: bool = Field(
        default=False,
        description="The caller should record a claim before the command runs.",
    )

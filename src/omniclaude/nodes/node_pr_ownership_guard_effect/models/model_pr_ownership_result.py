# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The ownership verdict for a whole Bash command (OMN-20685).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_pr_ownership_guard_effect.models.model_pr_ownership_decision import (
    ModelPrOwnershipDecision,
)


class ModelPrOwnershipResult(BaseModel):
    """One decision per guarded mutation; empty when the command holds none."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    blocked: bool
    decisions: list[ModelPrOwnershipDecision]
    reason: str = Field(description="The refusal messages of every refused mutation.")
    recorded_claims: list[str] = Field(
        default_factory=list,
        description="Claim keys this call recorded for allowed first-writer mutations.",
    )

    def verdict_payload(self) -> dict[str, object]:
        """The JSON the shell wrapper reads: its keys are the wire contract."""
        return {
            "blocked": self.blocked,
            "decisions": [
                {
                    "allowed": decision.allowed,
                    "reason_code": decision.reason_code.value,
                    "verb": decision.verb,
                    "target_key": decision.target_key,
                    "message": decision.message,
                }
                for decision in self.decisions
            ],
            "reason": self.reason,
        }

# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The lane GitHub read guard's verdict for one tool call (OMN-20916).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import (
    EnumLaneGithubReadShape,
    EnumLaneGithubReadVerdict,
)


class ModelLaneGithubReadDecision(BaseModel):
    """ALLOW or REFUSE, the bypass path judged, and the refusal naming the local reader."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: EnumLaneGithubReadVerdict
    shape: EnumLaneGithubReadShape
    is_read: bool = Field(
        description="The call reads GitHub (a write is never refused)."
    )
    lane_reason: str = Field(
        default="", description="Why the caller is a lane; empty for the operator."
    )
    target: str = Field(default="", description="The tool, program or gh path judged.")
    reason: str = Field(default="", description="The refusal text; empty on ALLOW.")

    def hook_payload(self) -> dict[str, object]:
        """The JSON the hook prints on a refusal: its keys are the wire contract."""
        return {
            "decision": "block",
            "reason": self.reason,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": self.reason,
            },
        }

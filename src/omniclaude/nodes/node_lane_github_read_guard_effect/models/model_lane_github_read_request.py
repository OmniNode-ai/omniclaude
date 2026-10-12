# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One PreToolUse call, as the lane GitHub read guard judges it (OMN-20916).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_lane_github_read_guard_effect.enums import EnumSessionMode


class ModelLaneGithubReadRequest(BaseModel):
    """The tool call and the facts that say whether its caller is a lane.

    No environment VALUE is carried: lane_markers holds only the names of the
    lane marker variables that are set, so no token or secret can reach the model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(description="The PreToolUse tool_name.")
    command: str = Field(default="", description="tool_input.command of a Bash call.")
    cwd: str = Field(default="", description="The caller's working directory.")
    home: str = Field(default="", description="HOME, for expanding a ~ or $HOME path.")
    agent_id: str = Field(
        default="",
        description="The payload's agent_id: set only when a subagent made the call.",
    )
    entrypoint: str = Field(
        default="",
        description="CLAUDE_CODE_ENTRYPOINT of the session (cli, sdk-cli, ...).",
    )
    mode: EnumSessionMode = Field(
        default=EnumSessionMode.FULL,
        description="omniclaude_mode of the session: lite (a non-OmniNode install) has no lanes.",
    )
    lane_markers: tuple[str, ...] = Field(
        default=(),
        description="Names of the lane marker environment variables that are set.",
    )

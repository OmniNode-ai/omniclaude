# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The typed verdict of one adapter call (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientVerdictAction,
)


class ModelClientVerdict(BaseModel):
    """client_verdict: the action, its text, and the hash the server echoed for that text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: EnumClientVerdictAction
    text: str = Field(default="")
    package_sha256: str = Field(
        default="",
        description="Echoed sha256 of text, when the action carries a package.",
    )

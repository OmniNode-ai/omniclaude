# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The adapter contract's client_bindings.claude_code section (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models.model_client_binding import (
    ModelClientBinding,
)


class ModelClientSection(BaseModel):
    """Per-host maximum modes and the binding rows; the inventory of binding hooks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_max_mode: EnumClientMaxMode = Field(default=EnumClientMaxMode.OBSERVE)
    host_max_modes: dict[str, EnumClientMaxMode] = Field(default_factory=dict)
    bindings: tuple[ModelClientBinding, ...] = Field(default=())

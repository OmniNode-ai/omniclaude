# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Bindings and the installing host's maximum mode (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientBinding,
)


class ModelBindingRenderRequest(BaseModel):
    """What a render needs: the rows and the host's client-section maximum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bindings: tuple[ModelClientBinding, ...]
    max_mode: EnumClientMaxMode

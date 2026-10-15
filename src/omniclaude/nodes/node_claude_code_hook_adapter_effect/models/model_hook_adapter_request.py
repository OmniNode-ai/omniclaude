# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The hook input and the binding it arrived under (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue

from omniclaude.nodes.node_claude_code_hook_adapter_effect.models.model_client_binding import (
    ModelClientBinding,
)


class ModelHookAdapterRequest(BaseModel):
    """What the adapter is given: the binding row and the hook JSON from stdin, nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding: ModelClientBinding
    hook_input: dict[str, JsonValue]

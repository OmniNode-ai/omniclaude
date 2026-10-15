# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""What to install, where, and which probe rows the capability report marks supported (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientBinding,
)


class ModelBindingInstallRequest(BaseModel):
    """Install request; mods_dir and settings_path are host paths the caller resolves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bindings: tuple[ModelClientBinding, ...]
    max_mode: EnumClientMaxMode
    mods_dir: str = Field(
        description="Claude Code mods folder; never inside a repository."
    )
    settings_path: str = Field(
        description="The user's settings.json (never a project's)."
    )
    supported_probe_rows: tuple[str, ...] = Field(
        description="Capability-report rows marked supported; a row needing any other is not installed."
    )
    plugin_name: str = Field(default="onex-claude-code-bindings")

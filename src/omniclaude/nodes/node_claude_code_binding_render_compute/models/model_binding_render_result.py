# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The rendered module text, its hash and the additive registrations (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_claude_code_binding_render_compute.models.model_binding_registration import (
    ModelBindingRegistration,
)


class ModelBindingRenderResult(BaseModel):
    """module_text is never committed anywhere; its sha256 is what install records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    module_text: str
    module_sha256: str
    registrations: tuple[ModelBindingRegistration, ...] = ()

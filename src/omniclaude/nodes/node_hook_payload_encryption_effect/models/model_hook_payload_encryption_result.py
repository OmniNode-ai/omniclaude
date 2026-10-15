# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The outcome of a payload encryption request (OMN-19513).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from omniclaude.nodes.node_hook_payload_encryption_effect.enums import (
    EnumHookPayloadEncryptionOutcome,
)


class ModelHookPayloadEncryptionResult(BaseModel):
    """The payload for SEALED and OPENED; a reason, never a key, for REFUSED."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: EnumHookPayloadEncryptionOutcome
    payload: dict[str, JsonValue] | None = None
    reason: str | None = Field(
        default=None,
        description="Names a cause or an exception type. Never a key or content.",
    )

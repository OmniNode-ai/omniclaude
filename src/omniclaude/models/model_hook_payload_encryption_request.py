# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One payload to seal or open, or a key check (OMN-19513).

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from omniclaude.enums.enum_hook_payload_class import EnumHookPayloadClass
from omniclaude.enums.enum_hook_payload_encryption_operation import (
    EnumHookPayloadEncryptionOperation,
)


class ModelHookPayloadEncryptionRequest(BaseModel):
    """The operation, the capture class, and the payload it applies to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: EnumHookPayloadEncryptionOperation
    payload_class: EnumHookPayloadClass
    payload: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="The plaintext payload to seal, or the sealed payload to open.",
    )
    key: SecretStr | None = Field(
        default=None,
        description=(
            "Base64 key text for OPEN by a reader that holds it. None reads the "
            "key from the secret store by the handler's key reference."
        ),
    )

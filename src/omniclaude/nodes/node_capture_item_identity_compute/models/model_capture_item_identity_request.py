# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One request to node_capture_item_identity_compute."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_capture_item_identity_compute.models.enum_capture_item_operation import (
    EnumCaptureItemOperation,
)


class ModelCaptureItemIdentityRequest(BaseModel):
    """The fields each operation reads; the others stay unset.

    - content_record_id: event_id and field.
    - claim_event_id: item_dir, session_id, agent_id, hook_event_name,
      discriminator, stream and minted_event_id.
    - next_producer_seq, high_water: item_dir, session_id and stream.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    operation: EnumCaptureItemOperation
    item_dir: str | None = None
    session_id: str | None = None
    stream: str | None = None
    agent_id: str | None = None
    hook_event_name: str | None = None
    discriminator: str | None = None
    minted_event_id: UUID | None = None
    event_id: UUID | None = None
    field: str | None = None


__all__ = ["ModelCaptureItemIdentityRequest"]

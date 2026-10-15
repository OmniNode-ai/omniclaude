# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One result from node_capture_item_identity_compute."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ModelCaptureItemIdentityResult(BaseModel):
    """The id or the number the requested operation produced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID | None = None
    content_record_id: UUID | None = None
    sequence: int | None = None


__all__ = ["ModelCaptureItemIdentityResult"]

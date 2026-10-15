# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One event the receipt-mode client returned for the published command (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue


class ModelReceiptEvent(BaseModel):
    """A correlated terminal or chunk event: its topic and payload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    topic: str
    payload: dict[str, JsonValue]

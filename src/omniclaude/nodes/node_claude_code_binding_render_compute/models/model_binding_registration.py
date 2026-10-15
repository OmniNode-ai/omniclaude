# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""One user-settings command-hook registration rendered from an additive row (OMN-18531)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ModelBindingRegistration(BaseModel):
    """event + optional matcher + the exact adapter command."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: str
    matcher: str | None = None
    command: str

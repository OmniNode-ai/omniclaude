# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Email adapter configuration model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelEmailConfig(BaseModel):
    """Configuration for the Email channel adapter.

    Credentials are resolved from environment at runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    imap_host: str = Field(..., min_length=1, description="IMAP server hostname")
    imap_user: str = Field(..., min_length=1, description="IMAP login username")
    imap_password: str = Field(  # secret-ok: config model, resolved from env at runtime
        ..., min_length=1, description="IMAP login password"
    )
    smtp_host: str = Field(..., min_length=1, description="SMTP server hostname")
    smtp_port: int = Field(default=587, description="SMTP server port")
    smtp_from: str = Field(..., min_length=1, description="From address for outbound")
    poll_interval_seconds: int = Field(
        default=30, ge=5, description="IMAP polling interval in seconds"
    )

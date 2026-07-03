# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Manifest fetch request model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ModelManifestFetchRequest(BaseModel):
    """Input model for manifest fetch requests.

    Attributes:
        runtime_url: Base URL of the ONEX runtime (e.g. ``http://192.168.86.201:18085``).  # onex-allow-internal-ip
            The handler appends ``/v1/introspection/manifest``.
        timeout_ms: Request timeout in milliseconds. Defaults to 5000.
        correlation_id: Optional correlation ID for tracing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_url: str = Field(
        ...,
        min_length=1,
        description="Base URL of the ONEX runtime (e.g. http://host:port)",
    )
    timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Request timeout in milliseconds",
    )
    correlation_id: UUID | None = Field(
        default=None,
        description="Correlation ID for tracing",
    )


__all__ = ["ModelManifestFetchRequest"]

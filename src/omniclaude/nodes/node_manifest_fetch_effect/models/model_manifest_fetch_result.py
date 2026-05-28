# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Manifest fetch result model.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class EnumManifestFetchStatus(StrEnum):
    """Status of a manifest fetch operation."""

    SUCCESS = "success"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class ModelManifestFetchResult(BaseModel):
    """Output model for manifest fetch operations.

    Attributes:
        status: Outcome of the fetch operation.
        manifest: Raw manifest payload from /v1/introspection/manifest.
            Empty dict when status is not SUCCESS.
        runtime_url: The runtime URL that was queried.
        duration_ms: Time taken for the HTTP request in milliseconds.
        error: Error message when status is not SUCCESS, None otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: EnumManifestFetchStatus = Field(
        ...,
        description="Outcome of the fetch operation",
    )
    manifest: dict[str, object] = Field(
        default_factory=dict,
        description="Raw manifest payload from /v1/introspection/manifest",
    )
    runtime_url: str = Field(
        ...,
        description="The runtime URL that was queried",
    )
    duration_ms: float = Field(
        default=0.0,
        ge=0.0,
        description="Time taken for the HTTP request in milliseconds",
    )
    error: str | None = Field(
        default=None,
        description="Error message when status is not SUCCESS",
    )


__all__ = ["EnumManifestFetchStatus", "ModelManifestFetchResult"]

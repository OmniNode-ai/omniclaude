# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Models for the NodeManifestFetchEffect node.

This package contains Pydantic models for manifest fetch operations:

- ModelManifestFetchRequest: Input model for fetch requests
- ModelManifestFetchResult: Output model for fetch results
- EnumManifestFetchStatus: Status enum for fetch outcomes

Model Ownership:
    These models are PRIVATE to omniclaude.
"""

from .model_manifest_fetch_request import ModelManifestFetchRequest
from .model_manifest_fetch_result import (
    EnumManifestFetchStatus,
    ModelManifestFetchResult,
)

__all__ = [
    "EnumManifestFetchStatus",
    "ModelManifestFetchRequest",
    "ModelManifestFetchResult",
]

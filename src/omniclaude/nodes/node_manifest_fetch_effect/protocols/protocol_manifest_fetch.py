# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Protocol for manifest fetch backends.

Model ownership: PRIVATE to omniclaude.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_manifest_fetch_effect.models import (
    ModelManifestFetchRequest,
    ModelManifestFetchResult,
)


@runtime_checkable
class ProtocolManifestFetch(Protocol):
    """Runtime-checkable protocol for manifest fetch backends.

    All manifest fetch backend implementations must implement this protocol.

    Supported backends: http (handler_key: 'http')

    Operation mapping (from node contract io_operations):
        - fetch operation -> fetch()
    """

    @property
    def handler_key(self) -> str:
        """Backend identifier for handler routing (e.g., 'http')."""
        raise NotImplementedError

    async def fetch(
        self, request: ModelManifestFetchRequest
    ) -> ModelManifestFetchResult:
        """Fetch the ONEX runtime manifest.

        Args:
            request: Fetch request with runtime URL and timeout.

        Returns:
            ModelManifestFetchResult with the manifest payload or error details.
            status=SUCCESS if manifest was fetched successfully.
            status=TIMEOUT if the request timed out.
            status=UNAVAILABLE if the runtime is not reachable.
            status=ERROR for any other failure.
        """
        raise NotImplementedError


__all__ = ["ProtocolManifestFetch"]

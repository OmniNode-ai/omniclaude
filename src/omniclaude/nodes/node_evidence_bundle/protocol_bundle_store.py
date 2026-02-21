# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Protocol for evidence bundle storage backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_evidence_bundle.models.model_evidence_bundle import (
    ModelEvidenceBundle,
)


@runtime_checkable
class ProtocolBundleStore(Protocol):
    """Storage backend for evidence bundles.

    Implementations must raise on storage failure — silent loss is forbidden.
    """

    def save(self, bundle: ModelEvidenceBundle) -> None:
        """Persist an evidence bundle.

        Args:
            bundle: The bundle to persist.

        Raises:
            RuntimeError: If the bundle cannot be saved.
        """
        ...

    def get(self, bundle_id: str) -> ModelEvidenceBundle:
        """Retrieve an evidence bundle by ID.

        Args:
            bundle_id: The bundle ID to retrieve.

        Returns:
            The stored evidence bundle.

        Raises:
            KeyError: If no bundle with the given ID exists.
        """
        ...

    def get_by_ticket_id(self, ticket_id: str) -> ModelEvidenceBundle | None:
        """Retrieve an evidence bundle by ticket ID.

        Args:
            ticket_id: The compiled ticket ID.

        Returns:
            The stored evidence bundle, or None if not found.
        """
        ...


__all__ = ["ProtocolBundleStore"]

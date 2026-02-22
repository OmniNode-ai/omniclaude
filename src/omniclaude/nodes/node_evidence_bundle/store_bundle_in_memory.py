# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""In-memory evidence bundle store for testing and local development."""

from __future__ import annotations

import logging

from omniclaude.nodes.node_evidence_bundle.models.model_evidence_bundle import (
    ModelEvidenceBundle,
)

__all__ = ["StoreBundleInMemory"]

logger = logging.getLogger(__name__)


class StoreBundleInMemory:
    """In-memory storage for evidence bundles.

    Not thread-safe; intended for testing and single-threaded local use.
    """

    def __init__(self) -> None:
        self._by_bundle_id: dict[str, ModelEvidenceBundle] = {}
        self._by_ticket_id: dict[str, ModelEvidenceBundle] = {}

    def save(self, bundle: ModelEvidenceBundle) -> None:
        """Persist an evidence bundle in memory.

        Args:
            bundle: The bundle to persist.

        Raises:
            RuntimeError: If a bundle with the same bundle_id already exists.
            RuntimeError: If a bundle for the same ticket_id already exists.
        """
        if bundle.bundle_id in self._by_bundle_id:
            raise RuntimeError(
                f"Evidence bundle {bundle.bundle_id!r} already exists — "
                "bundles are immutable and may not be overwritten."
            )
        if bundle.ticket_id in self._by_ticket_id:
            raise RuntimeError(
                f"An evidence bundle for ticket {bundle.ticket_id!r} already exists — "
                "each ticket produces exactly one bundle."
            )
        self._by_bundle_id[bundle.bundle_id] = bundle
        self._by_ticket_id[bundle.ticket_id] = bundle
        logger.debug(
            "Saved evidence bundle %s for ticket %s", bundle.bundle_id, bundle.ticket_id
        )

    def get(self, bundle_id: str) -> ModelEvidenceBundle:
        """Retrieve an evidence bundle by ID.

        Args:
            bundle_id: The bundle ID to retrieve.

        Returns:
            The stored evidence bundle.

        Raises:
            KeyError: If no bundle with the given ID exists.
        """
        try:
            return self._by_bundle_id[bundle_id]
        except KeyError:
            raise KeyError(f"No evidence bundle found with ID {bundle_id!r}")

    def get_by_ticket_id(self, ticket_id: str) -> ModelEvidenceBundle | None:
        """Retrieve an evidence bundle by ticket ID.

        Args:
            ticket_id: The compiled ticket ID.

        Returns:
            The stored evidence bundle, or None if not found.
        """
        return self._by_ticket_id.get(ticket_id)

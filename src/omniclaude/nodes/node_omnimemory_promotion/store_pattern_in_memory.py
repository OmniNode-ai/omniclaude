# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""In-memory OmniMemory pattern store for testing and local development."""

from __future__ import annotations

import logging

from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)

__all__ = ["StorePatternInMemory"]

logger = logging.getLogger(__name__)


class StorePatternInMemory:
    """In-memory storage for promoted patterns.

    Not thread-safe; intended for testing and single-threaded local use.
    Implements ProtocolPatternStore.
    """

    def __init__(self) -> None:
        self._by_id: dict[str, ModelPromotedPattern] = {}
        self._by_key: dict[str, ModelPromotedPattern] = {}

    def save(self, pattern: ModelPromotedPattern) -> None:
        """Persist a promoted pattern (create or overwrite for version bumps).

        Args:
            pattern: The pattern to persist.
        """
        self._by_id[pattern.pattern_id] = pattern
        self._by_key[pattern.pattern_key] = pattern
        logger.debug(
            "Saved promoted pattern %s (key=%s, version=%d)",
            pattern.pattern_id,
            pattern.pattern_key,
            pattern.version,
        )

    def get_by_key(self, pattern_key: str) -> ModelPromotedPattern | None:
        """Retrieve a promoted pattern by its lookup key.

        Args:
            pattern_key: The normalized pattern key.

        Returns:
            The stored pattern, or None if not found.
        """
        return self._by_key.get(pattern_key)

    def get_by_id(self, pattern_id: str) -> ModelPromotedPattern:
        """Retrieve a promoted pattern by ID.

        Args:
            pattern_id: The pattern ID.

        Returns:
            The stored pattern.

        Raises:
            KeyError: If no pattern with the given ID exists.
        """
        try:
            return self._by_id[pattern_id]
        except KeyError:
            raise KeyError(f"No promoted pattern found with ID {pattern_id!r}")

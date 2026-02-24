# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Protocol for OmniMemory pattern storage (OMN-2353 integration)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from omniclaude.nodes.node_omnimemory_promotion.models.model_promoted_pattern import (
    ModelPromotedPattern,
)


@runtime_checkable
class ProtocolPatternStore(Protocol):
    """OmniMemory storage backend for promoted patterns.

    Concrete implementations integrate with the OMN-2353 OmniMemory
    infrastructure.  The in-memory implementation is used for testing and
    local development.
    """

    def save(self, pattern: ModelPromotedPattern) -> None:
        """Persist a promoted pattern (create or update).

        Args:
            pattern: The pattern to persist.
        """
        ...

    def get_by_key(self, pattern_key: str) -> ModelPromotedPattern | None:
        """Retrieve a promoted pattern by its lookup key.

        Args:
            pattern_key: The normalized pattern key.

        Returns:
            The stored pattern, or None if not found.
        """
        ...

    def get_by_id(self, pattern_id: str) -> ModelPromotedPattern:
        """Retrieve a promoted pattern by its ID.

        Args:
            pattern_id: The pattern ID.

        Returns:
            The stored pattern.

        Raises:
            KeyError: If no pattern with the given ID exists.
        """
        ...


__all__ = ["ProtocolPatternStore"]

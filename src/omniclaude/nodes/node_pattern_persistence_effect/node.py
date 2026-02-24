# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Node Pattern Persistence Effect - 100% contract-driven.

This module provides the NodePatternPersistenceEffect class, a minimal shell
that inherits from NodeEffect. All effect logic is driven by the contract.yaml.

Capability: learned_pattern.storage

The node exposes two operations:
- query_patterns: Query patterns with domain/confidence filtering
- upsert_pattern: Insert or update patterns idempotently

Handler resolution is performed via ServiceRegistry by protocol type
(ProtocolPatternPersistence). The actual storage backend (e.g., PostgreSQL)
implements this protocol.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from omnibase_core.nodes.node_effect import NodeEffect

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer


class NodePatternPersistenceEffect(NodeEffect):
    """Effect node for learned pattern storage.

    Capability: learned_pattern.storage

    All behavior defined in contract.yaml.
    Handler resolved via ServiceRegistry by protocol type.
    """

    def __init__(self, container: ModelONEXContainer) -> None:
        """Initialize the pattern persistence effect node.

        Args:
            container: ONEX container for dependency injection
        """
        super().__init__(container)


__all__ = ["NodePatternPersistenceEffect"]

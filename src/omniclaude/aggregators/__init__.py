# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Session aggregation components for Claude Code hooks.

This package provides the protocol and supporting types for aggregating
Claude Code hook events into session snapshots. The aggregation system
follows event sourcing patterns with idempotency and timeout-based
finalization.

Key Components:
    - ProtocolSessionAggregator: The contract for session aggregation
    - SessionAggregator: In-memory implementation of the protocol
    - EnumSessionStatus: Session lifecycle states
    - ConfigSessionAggregator: Configuration for aggregation behavior
    - TSnapshot_co, TEvent_contra: Variance-annotated type variables for Protocol
    - PromptRecord, ToolRecord, SessionState: Internal state models

Architecture:
    The aggregation system receives hook events from Kafka topics and
    aggregates them into session snapshots. Each session progresses
    through a state machine:

    ```
    ORPHAN -> ACTIVE -> ENDED
                    -> TIMED_OUT
    ```

Related Tickets:
    - OMN-1401: Session storage in OmniMemory
    - OMN-1489: Core models in omnibase_core
    - OMN-1402: Learning compute node

Example:
    >>> from omniclaude.aggregators import (
    ...     SessionAggregator,
    ...     ConfigSessionAggregator,
    ...     EnumSessionStatus,
    ... )
    >>>
    >>> # Create aggregator with default configuration
    >>> config = ConfigSessionAggregator()
    >>> aggregator = SessionAggregator(config)
    >>> print(f"Aggregator: {aggregator.aggregator_id}")

See Also:
    - omniclaude.hooks.schemas: Hook event payload models
    - omniclaude.hooks.topics: Kafka topic definitions
"""

from __future__ import annotations

from omniclaude.aggregators.config import ConfigSessionAggregator
from omniclaude.aggregators.enums import EnumSessionStatus
from omniclaude.aggregators.protocol_session_aggregator import (
    ProtocolSessionAggregator,
    TEvent_contra,
    TSnapshot_co,
)
from omniclaude.aggregators.session_aggregator import (
    PromptRecord,
    PromptSnapshotDict,
    SessionAggregator,
    SessionSnapshotDict,
    SessionState,
    ToolRecord,
    ToolSnapshotDict,
)

__all__ = [
    # Protocol
    "ProtocolSessionAggregator",
    # Implementation
    "SessionAggregator",
    # Type variables (variance-annotated for proper Protocol usage)
    "TSnapshot_co",  # Covariant: used in return types only
    "TEvent_contra",  # Contravariant: used in argument types only
    # Enums
    "EnumSessionStatus",
    # Configuration
    "ConfigSessionAggregator",
    # Internal state models (exposed for testing/extension)
    "PromptRecord",
    "ToolRecord",
    "SessionState",
    # Snapshot TypedDicts (for consumers of get_snapshot)
    "PromptSnapshotDict",
    "SessionSnapshotDict",
    "ToolSnapshotDict",
]

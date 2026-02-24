# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Evidence resolver protocol and null implementation (OMN-2092).

Provides the bridge between promotion gate storage (M3 metrics aggregation)
and the injection pipeline. The sync path is kept testable by defaulting
to NullEvidenceResolver (no file I/O).

Part of OMN-2092: Evidence-Driven Injection Decisions.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EvidenceResolver(Protocol):
    """Protocol for resolving gate results per pattern.

    Implementations provide the bridge between promotion gate storage
    and the injection pipeline. The sync path is kept testable by
    defaulting to NullEvidenceResolver (no file I/O).
    """

    def resolve(self, pattern_id: str) -> str | None:
        """Look up the gate_result for a pattern.

        Returns:
            "pass", "fail", "insufficient_evidence", or None if unknown.
        """
        ...


class NullEvidenceResolver:
    """Always returns None — default, preserves current behavior."""

    def resolve(self, pattern_id: str) -> str | None:
        return None


__all__ = [
    "EvidenceResolver",
    "NullEvidenceResolver",
]

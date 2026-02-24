# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Dict-based evidence resolver for testing (OMN-2092).

In-memory resolver used in unit tests to simulate gate results
without file I/O.

Part of OMN-2092: Evidence-Driven Injection Decisions.
"""

from __future__ import annotations


class DictEvidenceResolver:
    """Test helper — resolves from an in-memory dict."""

    def __init__(self, gates: dict[str, str]) -> None:
        self._gates = gates

    def resolve(self, pattern_id: str) -> str | None:
        return self._gates.get(pattern_id)


__all__ = [
    "DictEvidenceResolver",
]

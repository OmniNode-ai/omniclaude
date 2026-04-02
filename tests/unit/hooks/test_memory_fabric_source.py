# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for MEMORY_FABRIC context source."""

import pytest

from omniclaude.hooks.schemas import ContextSource


@pytest.mark.unit
class TestContextSourceEnum:
    def test_memory_fabric_exists(self) -> None:
        assert hasattr(ContextSource, "MEMORY_FABRIC")
        assert ContextSource.MEMORY_FABRIC == "memory_fabric"

    def test_all_sources_present(self) -> None:
        expected = {
            "database",
            "session_aggregator",
            "rag_query",
            "fallback_static",
            "none",
            "memory_fabric",
        }
        actual = {s.value for s in ContextSource}
        assert expected.issubset(actual)

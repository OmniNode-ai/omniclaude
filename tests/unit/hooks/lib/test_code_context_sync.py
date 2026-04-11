# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for synchronous code context resolver wrapper."""

from __future__ import annotations

import pytest

from omniclaude.hooks.lib.code_context_sync import resolve_code_context_sync


@pytest.mark.unit
class TestCodeContextSync:
    def test_returns_empty_when_query_is_blank(self) -> None:
        assert resolve_code_context_sync("") == ""
        assert resolve_code_context_sync("   ") == ""

    def test_returns_empty_when_embedding_url_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_EMBEDDING_URL", raising=False)
        result = resolve_code_context_sync(
            "NodeCompute base class",
            max_entities=3,
            qdrant_url="http://127.0.0.1:1",
            embedding_url=None,
            timeout_seconds=0.5,
        )
        assert result == ""

    def test_returns_empty_when_qdrant_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_EMBEDDING_URL", "http://127.0.0.1:1")
        result = resolve_code_context_sync(
            query="NodeCompute base class",
            max_entities=5,
            qdrant_url="http://127.0.0.1:1",
            timeout_seconds=0.5,
        )
        assert result == ""

    def test_returns_string_type(self) -> None:
        result = resolve_code_context_sync(
            query="NodeCompute",
            max_entities=3,
            qdrant_url="http://127.0.0.1:1",
            embedding_url="http://127.0.0.1:1",
            timeout_seconds=0.5,
        )
        assert isinstance(result, str)

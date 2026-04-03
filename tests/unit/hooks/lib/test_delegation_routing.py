# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for frontier routing in delegation orchestrator [OMN-7410]."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


class TestFrontierRouting:
    """Verify frontier model routing policy."""

    def test_research_routes_to_frontier_when_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)
        # Also need a local endpoint for fallback in routing table
        monkeypatch.setenv("LLM_CODER_URL", "http://localhost:8000")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _select_handler_endpoint,
        )

        result = _select_handler_endpoint("research")
        assert result is not None
        url, model_name, _prompt, _handler = result
        assert "generativelanguage" in url or "gemini" in model_name.lower()

    def test_research_falls_back_to_local_when_frontier_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DELEGATION_DISABLE_FRONTIER_ROUTING", "true")
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("LLM_CODER_URL", "http://localhost:8000")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _select_handler_endpoint,
        )

        result = _select_handler_endpoint("research")
        assert result is not None
        url, model_name, _prompt, _handler = result
        # Should use local endpoint, not frontier
        assert "generativelanguage" not in url
        assert "gemini" not in model_name.lower()

    def test_document_never_routes_to_frontier(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)
        monkeypatch.setenv("LLM_QWEN_72B_URL", "http://localhost:8001")

        from plugins.onex.hooks.lib.delegation_orchestrator import (
            _select_handler_endpoint,
        )

        result = _select_handler_endpoint("document")
        assert result is not None
        url, model_name, _prompt, _handler = result
        assert "generativelanguage" not in url
        assert "gemini" not in model_name.lower()
        assert "glm" not in model_name.lower()

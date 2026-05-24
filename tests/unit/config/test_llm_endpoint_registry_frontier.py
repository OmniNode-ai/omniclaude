# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for frontier endpoint purposes (GEMINI/GLM/OpenRouter)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _clear_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ambient LLM config so tests do not inherit local overlays."""
    import os

    for key in list(os.environ):
        if key.startswith("LLM_"):
            monkeypatch.delenv(key, raising=False)
    for key in ("GEMINI_API_KEY", "LLM_GLM_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(key, raising=False)


class TestFrontierPurposes:
    """Verify frontier endpoint purposes."""

    def test_frontier_purposes_exist(self) -> None:
        from omniclaude.config.model_local_llm_config import LlmEndpointPurpose

        assert hasattr(LlmEndpointPurpose, "GEMINI")
        assert hasattr(LlmEndpointPurpose, "GLM")
        assert hasattr(LlmEndpointPurpose, "OPENROUTER")
        assert LlmEndpointPurpose.GEMINI == "gemini"
        assert LlmEndpointPurpose.GLM == "glm"
        assert LlmEndpointPurpose.OPENROUTER == "openrouter"

    def test_frontier_endpoints_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("LLM_GEMINI_MODEL_NAME", "configured-gemini")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("LLM_GLM_URL", "https://open.bigmodel.cn/api/paas/v4")
        monkeypatch.setenv("LLM_GLM_MODEL_NAME", "configured-glm")
        monkeypatch.setenv("LLM_GLM_API_KEY", "test-key")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("LLM_OPENROUTER_URL", "https://openrouter.example.com/api")
        monkeypatch.setenv("LLM_OPENROUTER_MODEL_NAME", "configured-openrouter")
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry(_env_file=None)
        gemini = registry.get_endpoint(LlmEndpointPurpose.GEMINI)
        glm = registry.get_endpoint(LlmEndpointPurpose.GLM)
        openrouter = registry.get_endpoint(LlmEndpointPurpose.OPENROUTER)
        assert gemini is not None
        assert glm is not None
        assert openrouter is not None
        assert gemini.max_latency_ms == 15000
        assert glm.max_latency_ms == 15000
        assert openrouter.max_latency_ms == 60000

    def test_frontier_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("DELEGATION_DISABLE_FRONTIER_ROUTING", "true")
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("LLM_GEMINI_MODEL_NAME", "configured-gemini")
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        monkeypatch.setenv("LLM_OPENROUTER_URL", "https://openrouter.example.com/api")
        monkeypatch.setenv("LLM_OPENROUTER_MODEL_NAME", "configured-openrouter")

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry(_env_file=None)
        gemini = registry.get_endpoint(LlmEndpointPurpose.GEMINI)
        openrouter = registry.get_endpoint(LlmEndpointPurpose.OPENROUTER)
        assert gemini is None
        assert openrouter is None

    def test_frontier_not_resolved_when_no_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _clear_llm_env(monkeypatch)
        monkeypatch.delenv("LLM_GEMINI_URL", raising=False)
        monkeypatch.delenv("LLM_GLM_URL", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry(_env_file=None)
        assert registry.get_endpoint(LlmEndpointPurpose.GEMINI) is None
        assert registry.get_endpoint(LlmEndpointPurpose.GLM) is None
        assert registry.get_endpoint(LlmEndpointPurpose.OPENROUTER) is None

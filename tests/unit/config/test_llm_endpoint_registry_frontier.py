# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for frontier endpoint purposes (GEMINI/GLM) [OMN-7410]."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


class TestFrontierPurposes:
    """Verify GEMINI and GLM frontier endpoint purposes."""

    def test_frontier_purposes_exist(self) -> None:
        from omniclaude.config.model_local_llm_config import LlmEndpointPurpose

        assert hasattr(LlmEndpointPurpose, "GEMINI")
        assert hasattr(LlmEndpointPurpose, "GLM")
        assert LlmEndpointPurpose.GEMINI == "gemini"
        assert LlmEndpointPurpose.GLM == "glm"

    def test_frontier_endpoints_resolve(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        monkeypatch.setenv("LLM_GLM_URL", "https://open.bigmodel.cn/api/paas/v4")
        monkeypatch.setenv("LLM_GLM_API_KEY", "test-key")
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry()
        gemini = registry.get_endpoint(LlmEndpointPurpose.GEMINI)
        glm = registry.get_endpoint(LlmEndpointPurpose.GLM)
        assert gemini is not None
        assert glm is not None
        assert gemini.max_latency_ms == 15000
        assert glm.max_latency_ms == 15000

    def test_frontier_disabled_by_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DELEGATION_DISABLE_FRONTIER_ROUTING", "true")
        monkeypatch.setenv(
            "LLM_GEMINI_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry()
        gemini = registry.get_endpoint(LlmEndpointPurpose.GEMINI)
        assert gemini is None

    def test_frontier_not_resolved_when_no_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LLM_GEMINI_URL", raising=False)
        monkeypatch.delenv("LLM_GLM_URL", raising=False)
        monkeypatch.delenv("DELEGATION_DISABLE_FRONTIER_ROUTING", raising=False)

        from omniclaude.config.model_local_llm_config import (
            LlmEndpointPurpose,
            LocalLlmEndpointRegistry,
        )

        registry = LocalLlmEndpointRegistry()
        assert registry.get_endpoint(LlmEndpointPurpose.GEMINI) is None
        assert registry.get_endpoint(LlmEndpointPurpose.GLM) is None

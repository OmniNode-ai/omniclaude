# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for quorum.py — provider migration from Ollama to OPENAI_COMPATIBLE (OMN-4798).

Tests verify:
- OLLAMA is no longer a valid ModelProvider value
- OPENAI_COMPATIBLE is the correct provider for vLLM/local endpoints
- Default endpoint reads from LLM_CODER_URL env var
- Default model uses OPENAI_COMPATIBLE provider
"""

from __future__ import annotations

import pytest

from omniclaude.lib.utils.consensus.quorum import (
    AIQuorum,
    ModelConfig,
    ModelProvider,
    _resolve_llm_coder_url,
)


class TestModelProviderEnum:
    """Test ModelProvider enum after Ollama decommission."""

    @pytest.mark.unit
    def test_openai_compatible_exists(self) -> None:
        """OPENAI_COMPATIBLE is a valid provider."""
        assert ModelProvider.OPENAI_COMPATIBLE.value == "openai_compatible"

    @pytest.mark.unit
    def test_ollama_not_in_enum(self) -> None:
        """OLLAMA is no longer a valid provider (decommissioned OMN-4798)."""
        values = [p.value for p in ModelProvider]
        assert "ollama" not in values, (
            "ModelProvider.OLLAMA found — it was decommissioned in OMN-4798. "
            "Use OPENAI_COMPATIBLE instead."
        )

    @pytest.mark.unit
    def test_gemini_still_exists(self) -> None:
        """GEMINI provider still available."""
        assert ModelProvider.GEMINI.value == "gemini"

    @pytest.mark.unit
    def test_openai_still_exists(self) -> None:
        """OPENAI provider still available."""
        assert ModelProvider.OPENAI.value == "openai"


class TestModelConfigDefaultEndpoint:
    """Test ModelConfig endpoint defaults for OPENAI_COMPATIBLE."""

    @pytest.mark.unit
    def test_openai_compatible_default_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPENAI_COMPATIBLE uses LLM_CODER_URL env var as default endpoint."""
        # GPU server host:port used via env var — not a Kafka address.  # onex-allow-internal-ip
        expected_host = "8000"
        monkeypatch.setenv("LLM_CODER_URL", f"http://gpu-server:{expected_host}")
        config = ModelConfig(
            name="test-model",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        assert config.endpoint == f"http://gpu-server:{expected_host}"

    @pytest.mark.unit
    def test_openai_compatible_raises_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ModelConfig must fail fast when LLM_CODER_URL is not set."""
        monkeypatch.delenv("LLM_CODER_URL", raising=False)
        with pytest.raises(RuntimeError, match="LLM_CODER_URL"):
            ModelConfig(
                name="test-model",
                provider=ModelProvider.OPENAI_COMPATIBLE,
            )


class TestAIQuorumDefaultModels:
    """Test AIQuorum default model list after migration."""

    @pytest.mark.unit
    def test_default_models_use_openai_compatible(self) -> None:
        """No default model uses OLLAMA provider."""
        for model in AIQuorum.DEFAULT_MODELS:
            assert (
                model.provider != ModelProvider("ollama")
                if hasattr(ModelProvider, "OLLAMA")
                else True
            )  # noqa: SIM210

    @pytest.mark.unit
    def test_default_models_have_code_model(self) -> None:
        """At least one default model is an OPENAI_COMPATIBLE code model."""
        code_models = [
            m
            for m in AIQuorum.DEFAULT_MODELS
            if m.provider == ModelProvider.OPENAI_COMPATIBLE
        ]
        assert len(code_models) >= 1, (
            "No OPENAI_COMPATIBLE model in DEFAULT_MODELS. "
            "Expected at least one vLLM/local code model."
        )


class TestResolveLlmCoderUrl:
    """Tests for _resolve_llm_coder_url() fail-fast behavior."""

    @pytest.mark.unit
    def test_requires_llm_coder_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Quorum must not silently fall back to hardcoded IP."""
        monkeypatch.delenv("LLM_CODER_URL", raising=False)
        with pytest.raises(RuntimeError, match="LLM_CODER_URL"):
            _resolve_llm_coder_url()

    @pytest.mark.unit
    def test_returns_url_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns the configured URL."""
        monkeypatch.setenv("LLM_CODER_URL", "http://gpu-server:8000")
        assert _resolve_llm_coder_url() == "http://gpu-server:8000"

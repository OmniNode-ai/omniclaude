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

from omniclaude.lib.utils.consensus.quorum import AIQuorum, ModelConfig, ModelProvider


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
    def test_openai_compatible_hardcoded_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to LLM_CODER_URL default when env var is unset."""
        monkeypatch.delenv("LLM_CODER_URL", raising=False)
        config = ModelConfig(
            name="test-model",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        # Endpoint should be set (not None) — fallback is the GPU server
        assert config.endpoint is not None
        assert "8000" in config.endpoint  # vLLM port

    @pytest.mark.unit
    def test_openai_compatible_no_ollama_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OPENAI_COMPATIBLE endpoint is NOT the old Ollama localhost:11434."""
        monkeypatch.delenv("LLM_CODER_URL", raising=False)
        config = ModelConfig(
            name="test-model",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        assert "localhost:11434" not in (config.endpoint or ""), (
            "Endpoint uses deprecated Ollama URL. Use LLM_CODER_URL instead."
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

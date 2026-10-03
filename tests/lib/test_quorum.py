# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for quorum.py — provider migration from Ollama to OPENAI_COMPATIBLE (OMN-4798).

Tests verify:
- OLLAMA is no longer a valid ModelProvider value
- OPENAI_COMPATIBLE is the correct provider for vLLM/local endpoints
- Default endpoint is resolved from the routing contract's endpoint_url_env (OMN-17103)
- Default model uses OPENAI_COMPATIBLE provider
"""

from __future__ import annotations

import pytest

from omniclaude.lib.utils.consensus.quorum import (
    AIQuorum,
    ModelConfig,
    ModelProvider,
    _resolve_local_backend_base_url,
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
        """OPENAI_COMPATIBLE resolves the contract's endpoint variable (lazy)."""
        # GPU server host:port used via env var — not a Kafka address.  # onex-allow-internal-ip
        monkeypatch.setenv(
            "BIFROST_LOCAL_CODER_ENDPOINT_URL",
            "http://gpu-server:8000/v1/chat/completions",
        )
        config = ModelConfig(
            name="local-coder",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        # Endpoint is resolved lazily via resolve_endpoint(), not at __post_init__
        assert config.endpoint is None
        assert config.resolve_endpoint() == "http://gpu-server:8000"

    @pytest.mark.unit
    def test_openai_compatible_raises_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ModelConfig.resolve_endpoint() must fail fast when the contract variable is unset."""
        monkeypatch.delenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", raising=False)
        config = ModelConfig(
            name="local-coder",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        # Construction succeeds (deferred), but resolve_endpoint() fails
        with pytest.raises(RuntimeError, match="No endpoint URL is configured"):
            config.resolve_endpoint()

    @pytest.mark.unit
    def test_openai_compatible_construction_without_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ModelConfig can be constructed without the endpoint variable (deferred resolution)."""
        monkeypatch.delenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", raising=False)
        # Must not raise at construction time
        config = ModelConfig(
            name="local-coder",
            provider=ModelProvider.OPENAI_COMPATIBLE,
        )
        assert config.endpoint is None


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


class TestResolveLocalBackendBaseUrl:
    """Tests for _resolve_local_backend_base_url() fail-fast behavior."""

    @pytest.mark.unit
    def test_requires_the_contract_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Quorum must not silently fall back to a hardcoded IP."""
        monkeypatch.delenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", raising=False)
        with pytest.raises(RuntimeError, match="No endpoint URL is configured"):
            _resolve_local_backend_base_url("local-coder")

    @pytest.mark.unit
    def test_unknown_backend_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A name the contract does not declare resolves to nothing."""
        monkeypatch.setenv(
            "BIFROST_LOCAL_CODER_ENDPOINT_URL",
            "http://gpu-server:8000/v1/chat/completions",
        )
        with pytest.raises(RuntimeError, match="No endpoint URL is configured"):
            _resolve_local_backend_base_url("test-model")

    @pytest.mark.unit
    def test_non_chat_url_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A URL that is not an OpenAI chat URL yields no derivable base."""
        monkeypatch.setenv("BIFROST_LOCAL_CODER_ENDPOINT_URL", "http://gpu-server:8000")
        with pytest.raises(RuntimeError, match="not an OpenAI chat"):
            _resolve_local_backend_base_url("local-coder")

    @pytest.mark.unit
    def test_returns_base_url_when_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns the contract URL minus the chat path."""
        monkeypatch.setenv(
            "BIFROST_LOCAL_CODER_ENDPOINT_URL",
            "http://gpu-server:8000/v1/chat/completions",
        )
        assert (
            _resolve_local_backend_base_url("local-coder") == "http://gpu-server:8000"
        )

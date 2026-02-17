"""OmniClaude configuration - Pydantic Settings for environment configuration."""

from __future__ import annotations

# Re-export component configs for convenient access
from omniclaude.aggregators.config import ConfigSessionAggregator

from .model_local_llm_config import (
    LlmEndpointConfig,
    LlmEndpointPurpose,
    LocalLlmEndpointRegistry,
)
from .settings import Settings, clear_settings_cache, get_settings, settings

__all__ = [
    # Core settings
    "Settings",
    "clear_settings_cache",
    "get_settings",
    "settings",
    # Component configs
    "ConfigSessionAggregator",
    # LLM endpoint registry
    "LlmEndpointConfig",
    "LlmEndpointPurpose",
    "LocalLlmEndpointRegistry",
]

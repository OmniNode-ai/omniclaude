"""OmniClaude configuration - Pydantic Settings for environment configuration."""

from __future__ import annotations

from .settings import Settings, get_settings, settings

# Re-export component configs for convenient access
from omniclaude.aggregators.config import ConfigSessionAggregator
from omniclaude.consumers.config import ConfigSessionConsumer
from omniclaude.storage.config import ConfigSessionStorage

__all__ = [
    # Core settings
    "Settings",
    "get_settings",
    "settings",
    # Component configs
    "ConfigSessionAggregator",
    "ConfigSessionConsumer",
    "ConfigSessionStorage",
]

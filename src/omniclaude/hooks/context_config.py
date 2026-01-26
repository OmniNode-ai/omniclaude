"""Configuration for context injection in Claude Code hooks.

Provides configurable settings for the context injection system that enriches
sessions with learned patterns and historical context.

Environment variables use the OMNICLAUDE_CONTEXT_ prefix:
    OMNICLAUDE_CONTEXT_ENABLED: Enable/disable context injection (default: true)
    OMNICLAUDE_CONTEXT_MAX_PATTERNS: Maximum patterns to inject (default: 5)
    OMNICLAUDE_CONTEXT_MIN_CONFIDENCE: Minimum confidence threshold (default: 0.7)
    OMNICLAUDE_CONTEXT_TIMEOUT_MS: Timeout for retrieval in milliseconds (default: 2000)
    OMNICLAUDE_CONTEXT_PERSISTENCE_FILE: Path to patterns file (default: .claude/learned_patterns.json)

Example:
    >>> from omniclaude.hooks.context_config import ContextInjectionConfig
    >>>
    >>> # Load from environment
    >>> config = ContextInjectionConfig.from_env()
    >>>
    >>> # Check if enabled
    >>> if config.enabled:
    ...     patterns = retrieve_patterns(config.max_patterns, config.min_confidence)
    ...
    >>> # Direct instantiation with overrides
    >>> config = ContextInjectionConfig(max_patterns=10, min_confidence=0.8)
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ContextInjectionConfig(BaseSettings):
    """Configuration for context injection.

    Controls how learned patterns and historical context are injected into
    Claude Code sessions during the UserPromptSubmit hook.

    Attributes:
        enabled: Enable or disable context injection globally.
        max_patterns: Maximum number of patterns to inject per session.
        min_confidence: Minimum confidence threshold for pattern selection.
        timeout_ms: Timeout for context retrieval operations.
        persistence_file: Path to the learned patterns persistence file.
    """

    model_config = SettingsConfigDict(
        env_prefix="OMNICLAUDE_CONTEXT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    enabled: bool = Field(
        default=True,
        description="Enable or disable context injection",
    )

    max_patterns: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of patterns to inject",
    )

    min_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for patterns",
    )

    timeout_ms: int = Field(
        default=2000,
        ge=500,
        le=10000,
        description="Timeout for context retrieval in milliseconds",
    )

    persistence_file: str = Field(
        default=".claude/learned_patterns.json",
        description="Path to patterns persistence file (relative to project root)",
    )

    @classmethod
    def from_env(cls) -> ContextInjectionConfig:
        """Load configuration from environment variables.

        Creates a ContextInjectionConfig instance by reading environment
        variables with the OMNICLAUDE_CONTEXT_ prefix. Falls back to
        default values when environment variables are not set.

        Returns:
            ContextInjectionConfig instance with values from environment.

        Example:
            >>> import os
            >>> os.environ["OMNICLAUDE_CONTEXT_MAX_PATTERNS"] = "10"
            >>> config = ContextInjectionConfig.from_env()
            >>> config.max_patterns
            10
        """
        return cls()

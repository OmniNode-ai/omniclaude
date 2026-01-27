"""Configuration for context injection in Claude Code hooks.

Provides configurable settings for the context injection system that enriches
sessions with learned patterns and historical context.

Environment variables use the OMNICLAUDE_CONTEXT_ prefix:
    OMNICLAUDE_CONTEXT_ENABLED: Enable/disable context injection (default: true)
    OMNICLAUDE_CONTEXT_MAX_PATTERNS: Maximum patterns to inject (default: 5)
    OMNICLAUDE_CONTEXT_MIN_CONFIDENCE: Minimum confidence threshold (default: 0.7)
    OMNICLAUDE_CONTEXT_TIMEOUT_MS: Timeout for retrieval in milliseconds (default: 2000)

    Database configuration (primary source):
    OMNICLAUDE_CONTEXT_DB_ENABLED: Enable database as pattern source (default: true)
    OMNICLAUDE_CONTEXT_DB_HOST: PostgreSQL host (default: 192.168.86.200)
    OMNICLAUDE_CONTEXT_DB_PORT: PostgreSQL port (default: 5436)
    OMNICLAUDE_CONTEXT_DB_NAME: Database name (default: omninode_bridge)
    OMNICLAUDE_CONTEXT_DB_USER: Database user (default: postgres)
    OMNICLAUDE_CONTEXT_DB_PASSWORD: Database password (required, no default)

    Deprecated file-based configuration:
    OMNICLAUDE_CONTEXT_PERSISTENCE_FILE: Path to patterns file (DEPRECATED)
    OMNICLAUDE_CONTEXT_FILE_FALLBACK_ENABLED: Fall back to file if DB unavailable (default: false)

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
    >>>
    >>> # Get database connection string
    >>> if config.db_enabled:
    ...     dsn = config.get_db_dsn()
"""

from __future__ import annotations

from pydantic import Field, SecretStr
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
        db_enabled: Enable database as pattern source (recommended).
        db_host: PostgreSQL host for pattern storage.
        db_port: PostgreSQL port.
        db_name: Database name.
        db_user: Database user.
        db_password: Database password (SecretStr for security).
        persistence_file: DEPRECATED - Path to the learned patterns persistence file.
        file_fallback_enabled: Fall back to file if database unavailable.
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

    # Database configuration (primary source)
    db_enabled: bool = Field(
        default=True,
        description="Enable database as pattern source (recommended)",
    )

    db_host: str = Field(
        default="192.168.86.200",
        description="PostgreSQL host for pattern storage",
    )

    db_port: int = Field(
        default=5436,
        ge=1,
        le=65535,
        description="PostgreSQL port",
    )

    db_name: str = Field(
        default="omninode_bridge",
        description="Database name",
    )

    db_user: str = Field(
        default="postgres",
        description="Database user",
    )

    db_password: SecretStr = Field(  # secret-ok: pydantic field name, not hardcoded
        default=SecretStr(""),
        description="Database password (from OMNICLAUDE_CONTEXT_DB_PASSWORD)",
    )

    # Deprecated file-based configuration
    persistence_file: str = Field(
        default=".claude/learned_patterns.json",
        description="DEPRECATED: File-based pattern storage. Use database instead.",
        deprecated=True,
    )

    file_fallback_enabled: bool = Field(
        default=False,
        description="Fall back to file if database unavailable",
    )

    def get_db_dsn(self) -> str:
        """Get PostgreSQL connection string.

        Constructs a PostgreSQL DSN (Data Source Name) from the configured
        database credentials. The password is retrieved from the SecretStr.

        Returns:
            PostgreSQL connection string in the format:
            postgresql://user:password@host:port/dbname

        Example:
            >>> config = ContextInjectionConfig(db_password=SecretStr("secret"))
            >>> dsn = config.get_db_dsn()
            >>> dsn.startswith("postgresql://")
            True
        """
        db_pass = self.db_password.get_secret_value()  # secret-ok: runtime env value
        return f"postgresql://{self.db_user}:{db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"

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

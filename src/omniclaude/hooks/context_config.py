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

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from omniclaude.hooks.cohort_assignment import CohortAssignmentConfig
from omniclaude.hooks.injection_limits import InjectionLimitsConfig


class SessionStartInjectionConfig(BaseModel):
    """Configuration for SessionStart pattern injection.

    Controls behavior of pattern injection at session startup,
    including timeout, limits, and footer visibility.

    Environment variables use the OMNICLAUDE_SESSION_INJECTION_ prefix:
        OMNICLAUDE_SESSION_INJECTION_ENABLED: Enable/disable injection (default: true)
        OMNICLAUDE_SESSION_INJECTION_TIMEOUT_MS: Timeout in milliseconds (default: 500)
        OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS: Max patterns to inject (default: 10)
        OMNICLAUDE_SESSION_INJECTION_MAX_CHARS: Max characters in content (default: 8000)
        OMNICLAUDE_SESSION_INJECTION_MIN_CONFIDENCE: Min confidence threshold (default: 0.7)
        OMNICLAUDE_SESSION_INJECTION_INCLUDE_FOOTER: Include injection_id footer (default: false)
        OMNICLAUDE_SESSION_SKIP_IF_INJECTED: Skip UserPromptSubmit if injected (default: true)

    Attributes:
        enabled: Whether SessionStart pattern injection is enabled.
        timeout_ms: Timeout for pattern injection in milliseconds.
        max_patterns: Maximum number of patterns to inject.
        max_chars: Maximum characters in injected content.
        min_confidence: Minimum confidence threshold for pattern inclusion.
        include_footer: Include injection_id footer in additionalContext.
        skip_user_prompt_if_injected: Skip UserPromptSubmit injection if SessionStart already injected.
        marker_file_dir: Directory for session marker files.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = Field(
        default=True,
        description="Whether SessionStart pattern injection is enabled",
    )
    timeout_ms: int = Field(
        default=500,
        ge=100,
        le=5000,
        description="Timeout for pattern injection in milliseconds",
    )
    max_patterns: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of patterns to inject",
    )
    max_chars: int = Field(
        default=8000,
        ge=1000,
        le=32000,
        description="Maximum characters in injected content",
    )
    min_confidence: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for pattern inclusion",
    )
    include_footer: bool = Field(
        default=False,
        description="Include injection_id footer in additionalContext",
    )
    skip_user_prompt_if_injected: bool = Field(
        default=True,
        description="Skip UserPromptSubmit injection if SessionStart already injected",
    )
    marker_file_dir: str = Field(
        default="/tmp",  # noqa: S108
        description="Directory for session marker files",
    )

    @classmethod
    def from_env(cls) -> SessionStartInjectionConfig:
        """Load config with environment variable overrides.

        Creates a SessionStartInjectionConfig instance by reading environment
        variables with the OMNICLAUDE_SESSION_INJECTION_ prefix. Falls back to
        default values when environment variables are not set.

        Returns:
            SessionStartInjectionConfig instance with values from environment.

        Example:
            >>> import os
            >>> os.environ["OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS"] = "15"
            >>> config = SessionStartInjectionConfig.from_env()
            >>> config.max_patterns
            15
        """
        return cls(
            enabled=os.getenv("OMNICLAUDE_SESSION_INJECTION_ENABLED", "true").lower()
            == "true",
            timeout_ms=int(os.getenv("OMNICLAUDE_SESSION_INJECTION_TIMEOUT_MS", "500")),
            max_patterns=int(
                os.getenv("OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS", "10")
            ),
            max_chars=int(os.getenv("OMNICLAUDE_SESSION_INJECTION_MAX_CHARS", "8000")),
            min_confidence=float(
                os.getenv("OMNICLAUDE_SESSION_INJECTION_MIN_CONFIDENCE", "0.7")
            ),
            include_footer=os.getenv(
                "OMNICLAUDE_SESSION_INJECTION_INCLUDE_FOOTER", "false"
            ).lower()
            == "true",
            skip_user_prompt_if_injected=os.getenv(
                "OMNICLAUDE_SESSION_SKIP_IF_INJECTED", "true"
            ).lower()
            == "true",
            marker_file_dir=os.getenv(
                "OMNICLAUDE_SESSION_INJECTION_MARKER_DIR",
                "/tmp",  # noqa: S108
            ),
        )


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

    db_password: SecretStr = Field(
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

    # Injection limits configuration (OMN-1671)
    limits: InjectionLimitsConfig = Field(
        default_factory=InjectionLimitsConfig,
        description="Injection limits to prevent context explosion",
    )

    # Cohort assignment configuration (A/B testing)
    # Uses from_contract to honor contract-first loading with env override.
    # Note: This nested config has its own env prefix (OMNICLAUDE_COHORT_*),
    # NOT OMNICLAUDE_CONTEXT_COHORT_*. The from_contract factory explicitly
    # loads from contract YAML and checks for OMNICLAUDE_COHORT_* env overrides.
    cohort: CohortAssignmentConfig = Field(
        default_factory=CohortAssignmentConfig.from_contract,
        description=(
            "A/B cohort assignment configuration for pattern injection experiments. "
            "Loaded via CohortAssignmentConfig.from_contract() which reads from "
            "contract YAML with optional OMNICLAUDE_COHORT_* env var overrides."
        ),
    )

    # SessionStart pattern injection configuration (OMN-1675)
    # Controls pattern injection at session startup with its own env prefix.
    session_start: SessionStartInjectionConfig = Field(
        default_factory=SessionStartInjectionConfig,
        description=(
            "SessionStart pattern injection configuration. Controls behavior of "
            "pattern injection at session startup including timeout, limits, and "
            "footer visibility. Uses OMNICLAUDE_SESSION_INJECTION_* env vars."
        ),
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
        db_pass = self.db_password.get_secret_value()
        return f"postgresql://{self.db_user}:{db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"

    @classmethod
    def from_env(cls) -> ContextInjectionConfig:
        """Load configuration from environment variables.

        Creates a ContextInjectionConfig instance by reading environment
        variables with the OMNICLAUDE_CONTEXT_ prefix. Falls back to
        default values when environment variables are not set.

        Nested Config Loading:
            The `limits` and `cohort` fields use `default_factory` and have
            their own environment variable handling:

            - `limits`: Uses InjectionLimitsConfig() which reads from
              OMNICLAUDE_INJECTION_LIMITS_* env vars automatically via Pydantic.

            - `cohort`: Uses CohortAssignmentConfig.from_contract() which:
              1. Loads defaults from contract_experiment_cohort.yaml
              2. Checks for OMNICLAUDE_COHORT_* env var overrides
              3. Returns configured instance

            Note: The cohort config uses OMNICLAUDE_COHORT_* prefix (NOT
            OMNICLAUDE_CONTEXT_COHORT_*) for backward compatibility and
            contract-first design.

        Returns:
            ContextInjectionConfig instance with values from environment.

        Example:
            >>> import os
            >>> os.environ["OMNICLAUDE_CONTEXT_MAX_PATTERNS"] = "10"
            >>> config = ContextInjectionConfig.from_env()
            >>> config.max_patterns
            10

            >>> # Cohort config uses its own env prefix
            >>> os.environ["OMNICLAUDE_COHORT_CONTROL_PERCENTAGE"] = "30"
            >>> config = ContextInjectionConfig.from_env()
            >>> config.cohort.control_percentage
            30
        """
        return cls()

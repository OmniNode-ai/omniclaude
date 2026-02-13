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
    OMNICLAUDE_CONTEXT_DB_POOL_MIN_SIZE: Minimum pool connections (default: 1)
    OMNICLAUDE_CONTEXT_DB_POOL_MAX_SIZE: Maximum pool connections (default: 5)

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
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
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
        default="/tmp/omniclaude-sessions",  # noqa: S108  # nosec B108
        description="Directory for session marker files",
    )

    @classmethod
    def from_env(cls) -> SessionStartInjectionConfig:
        """Load config with environment variable overrides.

        Creates a SessionStartInjectionConfig instance by reading environment
        variables with the OMNICLAUDE_SESSION_INJECTION_ prefix. Falls back to
        default values when environment variables are not set or malformed.

        Malformed numeric values (e.g., "abc" for timeout_ms) are logged as
        warnings and fall back to defaults.

        Returns:
            SessionStartInjectionConfig instance with values from environment.

        Example:
            >>> import os
            >>> os.environ["OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS"] = "15"
            >>> config = SessionStartInjectionConfig.from_env()
            >>> config.max_patterns
            15
        """
        import logging

        logger = logging.getLogger(__name__)

        def safe_int(env_var: str, default: int) -> int:
            """Parse int from env var with fallback to default."""
            val = os.getenv(env_var)
            if val is None:
                return default
            try:
                return int(val)
            except ValueError:
                logger.warning(
                    f"Invalid int for {env_var}='{val}', using default {default}"
                )
                return default

        def safe_float(env_var: str, default: float) -> float:
            """Parse float from env var with fallback to default."""
            val = os.getenv(env_var)
            if val is None:
                return default
            try:
                return float(val)
            except ValueError:
                logger.warning(
                    f"Invalid float for {env_var}='{val}', using default {default}"
                )
                return default

        def safe_bool(env_var: str, default: bool) -> bool:
            """Parse bool from env var with fallback to default.

            Accepts case-insensitive: true/false, 1/0, yes/no.
            Logs warning for unexpected values.
            """
            val = os.getenv(env_var)
            if val is None:
                return default
            val_lower = val.lower()
            if val_lower in ("true", "1", "yes"):
                return True
            if val_lower in ("false", "0", "no"):
                return False
            logger.warning(
                f"Invalid bool for {env_var}='{val}', "
                f"expected true/false/1/0/yes/no, using default {default}"
            )
            return default

        try:
            return cls(
                enabled=safe_bool("OMNICLAUDE_SESSION_INJECTION_ENABLED", True),
                timeout_ms=safe_int("OMNICLAUDE_SESSION_INJECTION_TIMEOUT_MS", 500),
                max_patterns=safe_int("OMNICLAUDE_SESSION_INJECTION_MAX_PATTERNS", 10),
                max_chars=safe_int("OMNICLAUDE_SESSION_INJECTION_MAX_CHARS", 8000),
                min_confidence=safe_float(
                    "OMNICLAUDE_SESSION_INJECTION_MIN_CONFIDENCE", 0.7
                ),
                include_footer=safe_bool(
                    "OMNICLAUDE_SESSION_INJECTION_INCLUDE_FOOTER", False
                ),
                skip_user_prompt_if_injected=safe_bool(
                    "OMNICLAUDE_SESSION_SKIP_IF_INJECTED", True
                ),
                marker_file_dir=os.getenv(
                    "OMNICLAUDE_SESSION_INJECTION_MARKER_DIR",
                    "/tmp/omniclaude-sessions",  # noqa: S108  # nosec B108
                ),
            )
        except Exception as e:
            # Catch Pydantic ValidationError or any unexpected errors.
            # Log with context and return default config to ensure method never raises.
            logger.warning(
                f"Failed to create SessionStartInjectionConfig from env: {e}. "
                "Using default configuration."
            )
            return cls()


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
        db_pool_min_size: Minimum database pool connections.
        db_pool_max_size: Maximum database pool connections.
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

    db_pool_min_size: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Minimum database pool connections",
    )

    db_pool_max_size: int = Field(
        default=5,
        ge=1,
        le=100,
        description="Maximum database pool connections",
    )

    # Contract-driven database access (OMN-1779)
    db_contract_path: str = Field(
        default="",
        description=(
            "Path to learned_patterns repository contract YAML. "
            "If empty, uses bundled contract from omniclaude.contracts. "
            "Override via OMNICLAUDE_CONTEXT_DB_CONTRACT_PATH."
        ),
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

    @model_validator(mode="after")
    def validate_pool_sizes(self) -> Self:
        """Ensure pool min_size <= max_size.

        Validates that db_pool_min_size does not exceed db_pool_max_size,
        which would cause runtime errors when creating the connection pool.

        Returns:
            Self: The validated config instance.

        Raises:
            ValueError: If db_pool_min_size > db_pool_max_size.
        """
        if self.db_pool_min_size > self.db_pool_max_size:
            raise ValueError(
                f"db_pool_min_size ({self.db_pool_min_size}) must be <= "
                f"db_pool_max_size ({self.db_pool_max_size})"
            )
        return self

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

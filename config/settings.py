"""
OmniClaude Pydantic Settings Configuration Framework.

This module provides type-safe configuration management using Pydantic Settings.
All configuration is loaded from environment variables with validation and type conversion.

Architecture:
    - Single Settings class organized into logical sections
    - Type hints and validators for all configuration
    - Support for multiple environment files (.env, .env.dev, .env.test, .env.prod)
    - Validation on startup with clear error messages
    - Sensitive values (passwords, API keys) handled securely

Environment File Priority:
    1. .env.{ENVIRONMENT} (e.g., .env.dev, .env.prod)
    2. .env (default/fallback)
    3. System environment variables (highest priority)

Usage:
    from config import settings

    # Access configuration values with type safety
    kafka_servers = settings.kafka_bootstrap_servers
    db_host = settings.postgres_host
    api_key = settings.gemini_api_key

Requirements:
    pip install pydantic pydantic-settings

See Also:
    - .env.example: Template with all configuration variables
    - config/README.md: Detailed usage documentation
    - SECURITY_KEY_ROTATION.md: API key management guide

Implementation:
    Phase 2 - ADR-001 Type-Safe Configuration Framework
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from pydantic import Field, HttpUrl, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


def find_project_root(start_path: Optional[Path] = None) -> Path:
    """
    Find the project root directory by looking for .env or .git.

    This function searches upward from the start path (or current file location)
    to find the project root, identified by the presence of .env or .git.

    Args:
        start_path: Starting directory for search (defaults to this file's directory)

    Returns:
        Path to project root directory

    Raises:
        RuntimeError: If project root cannot be found

    Example:
        >>> root = find_project_root()
        >>> print(root / ".env")
        /path/to/project/.env
    """
    if start_path is None:
        # Start from this file's directory
        start_path = Path(__file__).resolve().parent

    current = start_path
    max_depth = 10  # Prevent infinite loops

    for _ in range(max_depth):
        # Check for project markers
        if (current / ".env").exists() or (current / ".git").exists():
            return current

        # Move up one directory
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    # Fallback: If not found, assume parent of config/ directory is project root
    # This handles the case where .env doesn't exist yet
    return Path(__file__).resolve().parent.parent


def load_env_files(project_root: Path, environment: Optional[str] = None) -> None:
    """
    Load environment files from project root.

    Loads .env and optionally .env.{environment} files using python-dotenv.
    This ensures environment variables are available BEFORE Pydantic Settings
    initialization, making them work from any directory.

    Priority (highest to lowest):
        1. System environment variables (not modified)
        2. .env.{environment} file (loaded last = highest priority)
        3. .env file (loaded first = base configuration)

    Args:
        project_root: Path to project root directory
        environment: Environment name (dev, test, prod, etc.)

    Example:
        >>> load_env_files(Path("/project"), environment="test")
        # Loads /project/.env then /project/.env.test
    """
    # Load base .env file
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)  # Don't override system env vars
        logger.debug(f"Loaded environment from: {env_file}")
    else:
        logger.debug(f"No .env file found at: {env_file}")

    # Load environment-specific file (if specified)
    if environment:
        env_specific = project_root / f".env.{environment}"
        if env_specific.exists():
            load_dotenv(env_specific, override=True)  # Override .env values
            logger.info(f"Loaded environment-specific config: {env_specific}")
        else:
            logger.debug(f"No environment-specific file: {env_specific}")


# =========================================================================
# AUTO-LOAD ENVIRONMENT FILES ON MODULE IMPORT
# =========================================================================
# This ensures .env is loaded BEFORE Settings is instantiated, making it
# work from any directory without manual intervention.

try:
    _project_root = find_project_root()
    _environment = os.getenv("ENVIRONMENT")
    load_env_files(_project_root, _environment)
    logger.debug(f"Auto-loaded .env from project root: {_project_root}")
except Exception as e:
    logger.warning(f"Failed to auto-load .env files: {e}")
    # Continue anyway - Pydantic will use system env vars and defaults


class Settings(BaseSettings):
    """
    Centralized configuration for OmniClaude services.

    All configuration is loaded from environment variables with type validation.
    Organized into logical sections matching .env.example structure.

    Sections:
        1. External Service Discovery (omniarchon services)
        2. Shared Infrastructure (Kafka, PostgreSQL)
        3. AI Provider API Keys
        4. Local Services (Qdrant, Valkey)
        5. Feature Flags & Optimization
        6. Optional Configuration

    Attributes are organized by section with comprehensive documentation.
    """

    # =========================================================================
    # EXTERNAL SERVICE DISCOVERY (from omniarchon)
    # =========================================================================
    # Services provided by omniarchon repository (192.168.86.101)

    archon_intelligence_url: HttpUrl = Field(
        default="http://192.168.86.101:8053",
        description="Archon Intelligence API - Code quality, pattern discovery, RAG queries",
    )

    archon_search_url: HttpUrl = Field(
        default="http://192.168.86.101:8055",
        description="Archon Search API - Vector search, semantic search",
    )

    archon_bridge_url: HttpUrl = Field(
        default="http://192.168.86.101:8054",
        description="Archon Bridge API - Bridge services between systems",
    )

    archon_mcp_url: HttpUrl = Field(
        default="http://192.168.86.101:8051",
        description="Archon MCP Server - Model Context Protocol server",
    )

    intelligence_service_url: Optional[HttpUrl] = Field(
        default=None,
        description="Legacy alias for intelligence service (backward compatibility)",
    )

    main_server_url: HttpUrl = Field(
        default="http://192.168.86.101:8181",
        description="Archon Main Server (if different from intelligence)",
    )

    # ONEX MCP Service Configuration
    onex_mcp_host: str = Field(
        default="192.168.86.101",
        description="ONEX MCP service host (Model Context Protocol)",
    )

    onex_mcp_port: int = Field(
        default=8151,
        ge=1,
        le=65535,
        description="ONEX MCP service port",
    )

    # =========================================================================
    # SHARED INFRASTRUCTURE - KAFKA/REDPANDA (from omninode_bridge)
    # =========================================================================
    # Central message broker for distributed intelligence and observability
    # Running on 192.168.86.200

    kafka_bootstrap_servers: str = Field(
        default="omninode-bridge-redpanda:9092",
        description=(
            "Kafka broker addresses. "
            "Use omninode-bridge-redpanda:9092 for Docker services, "
            "192.168.86.200:29092 for host scripts"
        ),
    )

    kafka_intelligence_bootstrap_servers: Optional[str] = Field(
        default=None,
        description="Legacy alias for Kafka bootstrap servers (backward compatibility)",
    )

    kafka_enable_intelligence: bool = Field(
        default=True, description="Enable event-based intelligence queries"
    )

    kafka_enable_logging: bool = Field(
        default=True, description="Enable Kafka event logging"
    )

    kafka_enable_logging_events: bool = Field(
        default=True, description="Enable logging event publishing to Kafka"
    )

    enable_event_based_discovery: bool = Field(
        default=True, description="Enable event-first pattern discovery"
    )

    enable_filesystem_fallback: bool = Field(
        default=True, description="Fallback to filesystem on event failure"
    )

    prefer_event_patterns: bool = Field(
        default=True, description="Prefer event patterns over built-in patterns"
    )

    kafka_request_timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=60000,
        description="Request timeout in milliseconds (1-60 seconds)",
    )

    kafka_pattern_discovery_timeout_ms: int = Field(
        default=5000,
        ge=1000,
        le=60000,
        description="Pattern discovery timeout in milliseconds (1-60 seconds)",
    )

    kafka_code_analysis_timeout_ms: int = Field(
        default=10000,
        ge=1000,
        le=120000,
        description="Code analysis timeout in milliseconds (1-120 seconds)",
    )

    kafka_doc_topic: str = Field(
        default="documentation-changed",
        description="Documentation change tracking topic",
    )

    kafka_consumer_group_prefix: str = Field(
        default="omniclaude",
        description="Kafka consumer group prefix for this service",
    )

    # Kafka Intelligence Topics
    topic_code_analysis_requested: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-requested.v1",
        description="Topic for code analysis requests",
    )

    topic_code_analysis_completed: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-completed.v1",
        description="Topic for successful analysis responses",
    )

    topic_code_analysis_failed: str = Field(
        default="dev.archon-intelligence.intelligence.code-analysis-failed.v1",
        description="Topic for failed analysis responses",
    )

    # =========================================================================
    # SHARED INFRASTRUCTURE - POSTGRESQL (from omninode_bridge)
    # =========================================================================
    # Shared database for agent tracking, pattern storage, observability
    # Database: omninode_bridge (34+ tables)

    postgres_host: str = Field(
        default="192.168.86.200",
        description="PostgreSQL server host (use omninode-bridge-postgres for Docker)",
    )

    postgres_port: int = Field(
        default=5436,
        ge=1,
        le=65535,
        description="PostgreSQL server port (5432 internal, 5436 external)",
    )

    postgres_database: str = Field(
        default="omninode_bridge", description="PostgreSQL database name"
    )

    postgres_user: str = Field(default="postgres", description="PostgreSQL username")

    postgres_password: str = Field(
        default="", description="PostgreSQL password (REQUIRED - set in .env)"
    )

    # Legacy aliases for backward compatibility
    postgres_db: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_database"
    )

    db_password: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_password"
    )

    omninode_bridge_postgres_password: Optional[str] = Field(
        default=None, description="Legacy alias for postgres_password"
    )

    # PostgreSQL Connection Pool Configuration
    postgres_pool_min_size: int = Field(
        default=2, ge=1, le=100, description="Minimum connection pool size"
    )

    postgres_pool_max_size: int = Field(
        default=10, ge=1, le=100, description="Maximum connection pool size"
    )

    # =========================================================================
    # AI PROVIDER API KEYS
    # =========================================================================
    # Sensitive credentials - never commit to version control

    gemini_api_key: Optional[str] = Field(
        default=None,
        description="Google Gemini API key (get from: https://console.cloud.google.com/apis/credentials)",
    )

    google_api_key: Optional[str] = Field(
        default=None,
        description="Google API Key for Pydantic AI compatibility (usually same as gemini_api_key)",
    )

    zai_api_key: Optional[str] = Field(
        default=None,
        description="Z.ai API key for GLM models (get from: https://z.ai/dashboard)",
    )

    openai_api_key: Optional[str] = Field(
        default=None, description="OpenAI API key (optional)"
    )

    # =========================================================================
    # ALERTING & NOTIFICATIONS
    # =========================================================================
    # Slack webhook for fail-fast error notifications

    slack_webhook_url: Optional[str] = Field(
        default=None,
        description=(
            "Slack webhook URL for error notifications (optional). "
            "Get from: https://api.slack.com/messaging/webhooks. "
            "Notifications are opt-in - only sent if URL is configured."
        ),
    )

    slack_notification_throttle_seconds: int = Field(
        default=300,
        ge=0,
        description=(
            "Throttle window for Slack notifications (seconds). "
            "Max 1 notification per error type per window. "
            "Default: 300 (5 minutes). Set to 0 to disable throttling."
        ),
    )

    # =========================================================================
    # LOCAL SERVICES CONFIGURATION
    # =========================================================================
    # Services running locally on development machine

    # Qdrant Vector Database
    qdrant_host: str = Field(default="localhost", description="Qdrant server host")

    qdrant_port: int = Field(
        default=6333, ge=1, le=65535, description="Qdrant server port"
    )

    qdrant_url: HttpUrl = Field(
        default="http://localhost:6333",
        description="Qdrant full URL (derived from host:port)",
    )

    # Valkey Caching (Redis-compatible)
    enable_intelligence_cache: bool = Field(
        default=True, description="Enable distributed caching for intelligence queries"
    )

    valkey_url: Optional[str] = Field(
        default=None,
        description=(
            "Valkey connection URL (Redis protocol). "
            "Format: redis://:password@host:port/db "
            "Example: redis://:mypassword@archon-valkey:6379/0"
        ),
    )

    # Redis Configuration (for legacy compatibility)
    redis_host: str = Field(
        default="localhost",
        description="Redis server host (legacy compatibility)",
    )

    redis_port: int = Field(
        default=6379,
        ge=1,
        le=65535,
        description="Redis server port (legacy compatibility)",
    )

    # Cache TTLs (seconds)
    cache_ttl_patterns: int = Field(
        default=300,
        ge=0,
        description="Cache TTL for pattern discovery (seconds, 0=no cache)",
    )

    cache_ttl_infrastructure: int = Field(
        default=3600,
        ge=0,
        description="Cache TTL for infrastructure topology (seconds)",
    )

    cache_ttl_schemas: int = Field(
        default=1800, ge=0, description="Cache TTL for database schemas (seconds)"
    )

    # =========================================================================
    # FEATURE FLAGS & OPTIMIZATION
    # =========================================================================

    # Manifest Cache Configuration
    manifest_cache_ttl_seconds: int = Field(
        default=300, ge=0, description="Base cache TTL for manifest injection (seconds)"
    )

    # Pattern Quality Filtering (Phase 2)
    enable_pattern_quality_filter: bool = Field(
        default=False, description="Enable quality filtering for pattern injection"
    )

    min_pattern_quality: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum pattern quality threshold (0.0-1.0). "
            "0.9+=Excellent, 0.7-0.9=Good, 0.5-0.7=Fair, <0.5=Poor (filtered)"
        ),
    )

    # =========================================================================
    # CODE GENERATION & QUALITY GATES
    # =========================================================================

    # Code Generation Control
    codegen_consumer_group: str = Field(
        default="omniclaude-codegen",
        description="Kafka consumer group for code generation service",
    )

    codegen_generate_contracts: bool = Field(
        default=True,
        description="Enable automatic contract generation",
    )

    codegen_generate_models: bool = Field(
        default=True,
        description="Enable automatic model generation",
    )

    codegen_generate_enums: bool = Field(
        default=True,
        description="Enable automatic enum generation",
    )

    codegen_generate_business_logic: bool = Field(
        default=False,
        description="Enable business logic generation (starts with stubs)",
    )

    codegen_generate_tests: bool = Field(
        default=True,
        description="Enable automatic test generation",
    )

    # Mixin Configuration
    codegen_auto_select_mixins: bool = Field(
        default=True,
        description="Automatically select appropriate mixins for generated code",
    )

    codegen_mixin_confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for mixin selection (0.0-1.0)",
    )

    # Core Library Dependencies
    use_core_stable: bool = Field(
        default=True,
        description="Use omnibase_core as dependency (Pydantic 2.x)",
    )

    use_spi_validators: bool = Field(
        default=True,
        description="Use omnibase_spi validators",
    )

    use_archon_events: bool = Field(
        default=False,
        description="Use omniarchon event handlers (when ready)",
    )

    use_bridge_events: bool = Field(
        default=False,
        description="Use omninode_bridge event infrastructure (when ready)",
    )

    # Event-Driven Features
    enable_event_driven_analysis: bool = Field(
        default=False,
        description="Enable event-driven code analysis",
    )

    enable_event_driven_validation: bool = Field(
        default=False,
        description="Enable event-driven validation",
    )

    enable_event_driven_patterns: bool = Field(
        default=False,
        description="Enable event-driven pattern discovery",
    )

    # Quality Thresholds
    quality_threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum quality threshold for code generation (0.0-1.0)",
    )

    onex_compliance_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum ONEX compliance threshold (0.0-1.0)",
    )

    require_human_review: bool = Field(
        default=True,
        description="Require human review for generated code",
    )

    # Intelligence Timeouts
    analysis_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=600,
        description="Code analysis timeout in seconds",
    )

    validation_timeout_seconds: int = Field(
        default=20,
        ge=1,
        le=600,
        description="Validation timeout in seconds",
    )

    # =========================================================================
    # QUALITY ENFORCER CONFIGURATION
    # =========================================================================
    # Phased rollout control for quality enforcement hook

    enable_phase_1_validation: bool = Field(
        default=True,
        description="Enable Phase 1: Fast validation (<100ms)",
    )

    enable_phase_2_rag: bool = Field(
        default=False,
        description="Enable Phase 2: RAG intelligence (<500ms)",
    )

    enable_phase_3_correction: bool = Field(
        default=False,
        description="Enable Phase 3: Correction generation",
    )

    enable_phase_4_ai_quorum: bool = Field(
        default=False,
        description="Enable Phase 4: AI quorum scoring (<1000ms)",
    )

    performance_budget_seconds: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Performance budget for quality enforcement in seconds (0.1-10.0)",
    )

    enforcement_mode: str = Field(
        default="warn",
        description="Enforcement mode: 'warn' (allow with warning), 'block' (prevent write), or 'off' (disabled)",
    )

    @field_validator("enforcement_mode")
    @classmethod
    def validate_enforcement_mode(cls, v: str) -> str:
        """Validate enforcement mode is one of the allowed values."""
        allowed = ["warn", "block", "off"]
        if v.lower() not in allowed:
            raise ValueError(f"Enforcement mode must be one of {allowed}, got '{v}'")
        return v.lower()

    # =========================================================================
    # OPTIONAL CONFIGURATION
    # =========================================================================

    # Development Repository Paths
    omniarchon_path: Optional[str] = Field(
        default=None,
        description="Path to omniarchon repository (auto-resolved if not set)",
    )

    omninode_bridge_path: Optional[str] = Field(
        default=None,
        description="Path to omninode_bridge repository (auto-resolved if not set)",
    )

    # Git Hooks Configuration
    git_hook_validate_docs: bool = Field(
        default=False, description="Enable documentation validation before git push"
    )

    # Agent Router Configuration
    agent_registry_path: str = Field(
        default=None,
        description="Path to agent registry YAML (defaults to ~/.claude/agent-definitions/agent-registry.yaml)",
    )

    agent_definitions_path: str = Field(
        default=None,
        description="Path to agent definitions directory (defaults to ~/.claude/agent-definitions/)",
    )

    # Kafka Consumer Configuration
    kafka_group_id: str = Field(
        default="omniclaude-agent-router-consumer-group",
        description="Kafka consumer group ID for router consumer",
    )

    # Routing Service Configuration
    routing_adapter_port: int = Field(
        default=8055, ge=1, le=65535, description="Routing adapter service HTTP port"
    )

    routing_adapter_host: Optional[str] = Field(
        default=None,
        description=(
            "Routing adapter service bind address. "
            "Defaults to 0.0.0.0 in development (allows external connections), "
            "127.0.0.1 in production (localhost only for security)."
        ),
    )

    health_check_port: int = Field(
        default=8070,
        ge=1,
        le=65535,
        description="Port for health check HTTP endpoint in router consumer",
    )

    # Feature Flags
    use_event_routing: bool = Field(
        default=True,
        description="Enable event-based routing via Kafka (vs HTTP)",
    )

    routing_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="Routing operation timeout (milliseconds)",
    )

    request_timeout_ms: int = Field(
        default=5000,
        ge=100,
        le=60000,
        description="General request timeout (milliseconds)",
    )

    max_batch_size: int = Field(
        default=100, ge=1, le=1000, description="Maximum routing requests per batch"
    )

    cache_ttl_seconds: int = Field(
        default=3600, ge=0, description="General cache TTL (seconds)"
    )

    health_check_interval: int = Field(
        default=30, ge=1, le=3600, description="Health check interval (seconds)"
    )

    # Environment detection
    environment: str = Field(
        default="development",
        description="Runtime environment (development, test, production)",
    )

    debug: bool = Field(
        default=False,
        description="Enable debug logging and verbose output",
    )

    omniclaude_agents_path: Optional[str] = Field(
        default=None,
        description="Path to OmniClaude agents directory (defaults to <project_root>/agents)",
    )

    # =========================================================================
    # VALIDATORS
    # =========================================================================

    @field_validator(
        "postgres_port", "qdrant_port", "routing_adapter_port", "health_check_port"
    )
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        """Validate port is in valid range (1-65535)."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("min_pattern_quality")
    @classmethod
    def validate_quality_threshold(cls, v: float) -> float:
        """Validate pattern quality threshold is between 0.0 and 1.0."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"Pattern quality threshold must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("postgres_pool_min_size", "postgres_pool_max_size")
    @classmethod
    def validate_pool_size(cls, v: int) -> int:
        """Validate connection pool size is reasonable."""
        if v < 1:
            raise ValueError(f"Pool size must be at least 1, got {v}")
        if v > 100:
            logger.warning(
                f"Pool size {v} is very large, consider reducing for resource efficiency"
            )
        return v

    @field_validator(
        "kafka_request_timeout_ms",
        "kafka_pattern_discovery_timeout_ms",
        "routing_timeout_ms",
        "request_timeout_ms",
    )
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        """Validate timeout is reasonable (1-60 seconds)."""
        if not 1000 <= v <= 60000:
            raise ValueError(f"Timeout must be between 1000ms and 60000ms, got {v}")
        return v

    @field_validator("kafka_code_analysis_timeout_ms")
    @classmethod
    def validate_code_analysis_timeout(cls, v: int) -> int:
        """Validate code analysis timeout is reasonable (1-120 seconds)."""
        if not 1000 <= v <= 120000:
            raise ValueError(
                f"Code analysis timeout must be between 1000ms and 120000ms, got {v}"
            )
        return v

    @field_validator("agent_registry_path", mode="before")
    @classmethod
    def resolve_agent_registry_path(cls, v: Optional[str]) -> str:
        """
        Resolve agent registry path with default.

        Priority:
        1. AGENT_REGISTRY_PATH environment variable (explicit override)
        2. REGISTRY_PATH environment variable (Docker compatibility)
        3. Default: ~/.claude/agent-definitions/agent-registry.yaml
        """
        if v:
            return v

        # Check for Docker-compatible REGISTRY_PATH environment variable
        registry_path = os.getenv("REGISTRY_PATH")
        if registry_path:
            return registry_path

        # Fall back to home directory default
        home_dir = Path.home()
        return str(home_dir / ".claude" / "agent-definitions" / "agent-registry.yaml")

    @field_validator("agent_definitions_path", mode="before")
    @classmethod
    def resolve_agent_definitions_path(cls, v: Optional[str]) -> str:
        """Resolve agent definitions directory with default."""
        if v:
            return v
        home_dir = Path.home()
        return str(home_dir / ".claude" / "agent-definitions")

    @field_validator("omniclaude_agents_path", mode="before")
    @classmethod
    def resolve_omniclaude_agents_path(cls, v: Optional[str]) -> str:
        """
        Resolve OmniClaude agents directory with default.

        Priority:
        1. OMNICLAUDE_AGENTS_PATH environment variable (explicit override)
        2. Default: <project_root>/agents/parallel_execution (agent framework location)
        """
        if v:
            return v

        # Get project root (parent of config directory)
        project_root = Path(__file__).resolve().parent.parent
        return str(project_root / "agents" / "parallel_execution")

    @field_validator("routing_adapter_host", mode="before")
    @classmethod
    def validate_routing_adapter_host(cls, v: Any, info: ValidationInfo) -> str:
        """
        Validate and set environment-specific host binding for security.

        Security Rationale:
        -------------------
        - Development: Binds to 0.0.0.0 (all interfaces) to allow connections from
          Docker containers, local network, and external debugging tools.

        - Production/Test: Binds to 127.0.0.1 (localhost only) to prevent external
          access. This is critical for security in production deployments where the
          service should only be accessed through a reverse proxy (nginx, etc).

        Binding to 0.0.0.0 in production exposes the service to the network, which:
        - Increases attack surface
        - Bypasses firewall protection
        - Allows unauthorized access if authentication is weak
        - Violates principle of least privilege

        If external access is needed in production, use a reverse proxy with:
        - TLS/SSL termination
        - Rate limiting
        - Authentication/authorization
        - Request filtering

        Args:
            v: Explicit host value from environment variable or None
            info: Validation context (unused - we read ENVIRONMENT directly)

        Returns:
            Host binding address (0.0.0.0 for dev, 127.0.0.1 for prod)
        """
        # If explicitly set via ROUTING_ADAPTER_HOST environment variable, respect that
        if v is not None:
            return v

        # Read ENVIRONMENT env var directly (case-insensitive due to Settings config)
        # This is more reliable than info.data since environment field is defined later
        import os

        env = os.getenv("ENVIRONMENT", "production").lower()

        if env == "development":
            # Development: Allow external connections for Docker/debugging
            return "0.0.0.0"  # noqa: S104  # Intentional: Development only, secured via Docker network
        else:
            # Production/Test: Localhost only for security
            return "127.0.0.1"

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    def __init__(self, **values):
        """
        Initialize settings with environment variables.

        Environment files (.env and .env.{ENVIRONMENT}) are automatically loaded
        at module import time via load_env_files() function, so they're already
        available as system environment variables.

        Priority (highest to lowest):
        1. System environment variables (highest priority)
        2. .env.{ENVIRONMENT} file (loaded at import time)
        3. .env file (loaded at import time)
        4. Default values in Settings class (lowest priority)

        Note: No need to pass _env_file to super().__init__() because environment
        variables are already loaded into os.environ by load_env_files().

        Example:
            >>> # Environment files already loaded at import time
            >>> from config import settings
            >>> print(settings.postgres_host)  # Uses value from .env
        """
        # Environment files already loaded at module import time
        # Just initialize with system environment variables
        super().__init__(**values)

    # =========================================================================
    # PYDANTIC SETTINGS CONFIGURATION
    # =========================================================================

    model_config = SettingsConfigDict(
        # Environment file configuration (fallback only - files loaded at import time)
        # The load_env_files() function at module import loads .env files into os.environ,
        # so this env_file setting is just a fallback if import-time loading fails.
        env_file=".env",
        env_file_encoding="utf-8",
        # No environment variable prefix
        env_prefix="",
        # Case insensitive environment variable matching
        case_sensitive=False,
        # Ignore extra environment variables not defined in model
        extra="ignore",
        # Allow arbitrary types (for HttpUrl, etc.)
        arbitrary_types_allowed=True,
        # Validate on assignment (catch errors early)
        validate_assignment=True,
        # Use enum values instead of enum instances
        use_enum_values=True,
    )

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    def get_postgres_dsn(self, async_driver: bool = False) -> str:
        """
        Get PostgreSQL connection string (DSN).

        Args:
            async_driver: If True, use asyncpg:// scheme, else postgresql://

        Returns:
            PostgreSQL connection string

        Example:
            >>> settings.get_postgres_dsn()
            'postgresql://postgres:password@192.168.86.200:5436/omninode_bridge'
            >>> settings.get_postgres_dsn(async_driver=True)
            'postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge'
        """
        scheme = "postgresql+asyncpg" if async_driver else "postgresql"
        password = self.get_effective_postgres_password()
        return (
            f"{scheme}://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    def get_effective_postgres_password(self) -> str:
        """
        Get effective PostgreSQL password (handles legacy aliases).

        This method provides backward compatibility with deprecated password
        environment variable aliases while emitting warnings to guide migration.

        Deprecated Aliases (will be removed in v2.0):
            - DB_PASSWORD
            - OMNINODE_BRIDGE_POSTGRES_PASSWORD

        Standard Variable (use this):
            - POSTGRES_PASSWORD

        Returns:
            PostgreSQL password from primary field or legacy aliases

        Raises:
            ValueError: If no password is set

        Warnings:
            Emits deprecation warnings if legacy aliases are used

        Example:
            >>> settings = Settings()
            >>> password = settings.get_effective_postgres_password()
            >>> # Returns value from POSTGRES_PASSWORD (or legacy alias with warning)
        """
        # Check primary password field
        if self.postgres_password:
            return self.postgres_password

        # Check legacy aliases with deprecation warnings
        if self.db_password:
            logger.warning(
                "DEPRECATION WARNING: DB_PASSWORD is deprecated and will be "
                "removed in v2.0. Please migrate to POSTGRES_PASSWORD in your .env file. "
                "See PASSWORD_ALIAS_MIGRATION.md for migration guide."
            )
            return self.db_password

        if self.omninode_bridge_postgres_password:
            logger.warning(
                "DEPRECATION WARNING: OMNINODE_BRIDGE_POSTGRES_PASSWORD is deprecated "
                "and will be removed in v2.0. Please migrate to POSTGRES_PASSWORD in your "
                ".env file. See PASSWORD_ALIAS_MIGRATION.md for migration guide."
            )
            return self.omninode_bridge_postgres_password

        # No password configured
        raise ValueError(
            "PostgreSQL password not configured. " "Set POSTGRES_PASSWORD in .env file"
        )

    def get_effective_kafka_bootstrap_servers(self) -> str:
        """
        Get effective Kafka bootstrap servers (handles legacy aliases).

        Returns:
            Kafka bootstrap servers from primary field or legacy aliases
        """
        return (
            self.kafka_bootstrap_servers
            or self.kafka_intelligence_bootstrap_servers
            or ""
        )

    def validate_required_services(self) -> list[str]:
        """
        Validate that required services are configured.

        Returns:
            List of validation error messages (empty if all valid)

        Example:
            >>> errors = settings.validate_required_services()
            >>> if errors:
            ...     for error in errors:
            ...         print(f"Configuration Error: {error}")
        """
        errors = []

        # Validate PostgreSQL password
        try:
            self.get_effective_postgres_password()
        except ValueError as e:
            errors.append(str(e))

        # Validate Kafka bootstrap servers
        if not self.get_effective_kafka_bootstrap_servers():
            errors.append(
                "Kafka bootstrap servers not configured. "
                "Set KAFKA_BOOTSTRAP_SERVERS in .env file"
            )

        # Validate agent registry exists (if configured)
        if self.agent_registry_path:
            registry_path = Path(self.agent_registry_path)
            if not registry_path.exists():
                errors.append(
                    f"Agent registry not found at: {self.agent_registry_path}. "
                    f"Set AGENT_REGISTRY_PATH environment variable or ensure file exists."
                )

        # Validate agent definitions directory exists (if configured)
        if self.agent_definitions_path:
            definitions_path = Path(self.agent_definitions_path)
            if not definitions_path.is_dir():
                errors.append(
                    f"Agent definitions directory not found at: {self.agent_definitions_path}. "
                    f"Set AGENT_DEFINITIONS_PATH environment variable or ensure directory exists."
                )

        return errors

    def log_configuration(
        self, logger_instance: Optional[logging.Logger] = None
    ) -> None:
        """
        Log configuration with sensitive values sanitized.

        Args:
            logger_instance: Logger to use (defaults to module logger)

        Example:
            >>> settings.log_configuration()
            INFO: Configuration loaded successfully
            INFO:   Environment: development
            INFO:   Kafka: 192.168.86.200:29092
            INFO:   PostgreSQL: 192.168.86.200:5436/omninode_bridge (password: ***)
        """
        log = logger_instance or logger

        log.info("=" * 80)
        log.info("OmniClaude Configuration")
        log.info("=" * 80)

        # External Services
        log.info("\nExternal Services:")
        log.info(f"  Archon Intelligence: {self.archon_intelligence_url}")
        log.info(f"  Archon Search: {self.archon_search_url}")
        log.info(f"  Archon Bridge: {self.archon_bridge_url}")
        log.info(f"  Archon MCP: {self.archon_mcp_url}")

        # Infrastructure
        log.info("\nShared Infrastructure:")
        log.info(f"  Kafka: {self.kafka_bootstrap_servers}")
        log.info(
            f"  PostgreSQL: {self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )
        log.info(f"  PostgreSQL User: {self.postgres_user}")
        log.info(
            f"  PostgreSQL Password: {'***' if self.postgres_password else '(not set)'}"
        )

        # Local Services
        log.info("\nLocal Services:")
        log.info(f"  Qdrant: {self.qdrant_url}")
        log.info(
            f"  Valkey: {self.valkey_url if self.valkey_url else '(not configured)'}"
        )
        log.info(
            f"  Intelligence Cache: {'enabled' if self.enable_intelligence_cache else 'disabled'}"
        )

        # API Keys
        log.info("\nAI Provider API Keys:")
        log.info(f"  Gemini: {'configured' if self.gemini_api_key else 'not set'}")
        log.info(f"  Z.ai: {'configured' if self.zai_api_key else 'not set'}")
        log.info(f"  OpenAI: {'configured' if self.openai_api_key else 'not set'}")

        # Alerting & Notifications
        log.info("\nAlerting & Notifications:")
        log.info(
            f"  Slack Webhook: {'configured' if self.slack_webhook_url else 'not configured'}"
        )
        if self.slack_webhook_url:
            log.info(
                f"  Notification Throttle: {self.slack_notification_throttle_seconds}s"
            )

        # Feature Flags
        log.info("\nFeature Flags:")
        log.info(f"  Event-based Intelligence: {self.kafka_enable_intelligence}")
        log.info(f"  Pattern Quality Filter: {self.enable_pattern_quality_filter}")
        if self.enable_pattern_quality_filter:
            log.info(f"  Min Pattern Quality: {self.min_pattern_quality}")

        # Performance
        log.info("\nPerformance Configuration:")
        log.info(f"  Kafka Timeout: {self.kafka_request_timeout_ms}ms")
        log.info(f"  Routing Timeout: {self.routing_timeout_ms}ms")
        log.info(f"  Manifest Cache TTL: {self.manifest_cache_ttl_seconds}s")
        log.info(f"  Pattern Cache TTL: {self.cache_ttl_patterns}s")

        log.info("=" * 80)

    def to_dict_sanitized(self) -> dict:
        """
        Convert configuration to dictionary with sensitive values sanitized.

        Returns:
            Dictionary with configuration (passwords/keys replaced with ***)

        Example:
            >>> config_dict = settings.to_dict_sanitized()
            >>> print(config_dict['postgres_password'])
            ***
        """
        data = self.model_dump()

        # Sanitize sensitive fields
        sensitive_fields = [
            "postgres_password",
            "db_password",
            "omninode_bridge_postgres_password",
            "gemini_api_key",
            "google_api_key",
            "zai_api_key",
            "openai_api_key",
            "slack_webhook_url",
        ]

        for field in sensitive_fields:
            if data.get(field):
                data[field] = "***"

        # Sanitize Valkey URL (contains password)
        if data.get("valkey_url"):
            data["valkey_url"] = "***"

        return data


# =========================================================================
# SINGLETON INSTANCE
# =========================================================================


def _send_config_error_notification(errors: list[str]) -> None:
    """
    Send Slack notification for configuration errors (non-blocking).

    Separated from get_settings() to avoid coupling and circular dependencies.
    Intelligently uses async notifications when event loop is available,
    falls back to synchronous HTTP when no event loop exists (e.g., module initialization).

    Args:
        errors: List of configuration validation error messages

    Note:
        This function fails silently if notification cannot be sent.
        It's designed to be best-effort and not block application startup.
    """
    try:
        # Import here to avoid circular dependency
        import asyncio

        from agents.lib.slack_notifier import get_slack_notifier

        notifier = get_slack_notifier()
        if not notifier.is_enabled():
            logger.debug("Slack notifications disabled, skipping error notification")
            return

        # Build notification message
        error = ValueError(f"Configuration validation failed: {len(errors)} error(s)")
        context = {
            "service": "config_settings",
            "operation": "configuration_validation",
            "validation_errors": errors,
            "error_count": len(errors),
        }

        # Check if event loop is running - use async if available, sync if not
        try:
            loop = asyncio.get_running_loop()
            # Event loop exists - schedule async notification (non-blocking)
            logger.debug("Event loop detected - scheduling async Slack notification")
            # Use loop.create_task() instead of asyncio.create_task() to avoid
            # implicit loop lookup and potential TOCTOU race condition
            loop.create_task(
                notifier.send_error_notification(error=error, context=context)
            )
        except RuntimeError:
            # No event loop - use synchronous approach (safe for module initialization)
            logger.debug(
                "No event loop detected - using synchronous Slack notification"
            )
            import httpx

            payload = notifier._build_slack_message(error=error, context=context)

            # Send synchronously (no event loop during initialization)
            try:
                response = httpx.post(
                    notifier.webhook_url,
                    json=payload,
                    timeout=10.0,
                )
                if response.status_code == 200:
                    logger.debug(
                        "Configuration validation error notification sent to Slack"
                    )
                else:
                    logger.debug(
                        f"Slack webhook returned non-200 status: {response.status_code}"
                    )
            except httpx.TimeoutException:
                logger.debug("Slack webhook request timed out")
            except Exception as send_error:
                logger.debug(f"Failed to send notification to Slack: {send_error}")

    except Exception as notify_error:
        # Fail silently - notification is best-effort
        logger.debug(f"Could not send config error notification: {notify_error}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get or create singleton settings instance with validation.

    This function implements the singleton pattern to ensure only one
    Settings instance is created and reused throughout the application.
    The @lru_cache decorator provides thread-safe memoization.

    In production environments, configuration validation failures will
    raise ValueError to prevent application startup with invalid config.
    In development/test modes, errors are logged and notifications are sent.

    Pytest Detection:
        Automatically detects pytest collection phase by checking if pytest
        module is imported AND PYTEST_CURRENT_TEST is not set. Validation
        is skipped ONLY during collection to allow test discovery without
        full configuration. Validation runs during actual test execution
        (setup/call/teardown) to catch configuration issues in tests.

    Returns:
        Settings instance

    Raises:
        ValueError: If configuration validation fails in production environment

    Example:
        >>> from config import get_settings
        >>> settings = get_settings()
        >>> print(settings.postgres_host)
        192.168.86.200
    """
    settings = Settings()

    # Check if running in pytest collection phase only
    # During collection, pytest discovers tests without running them, so validation
    # would fail unnecessarily. However, during actual test execution (setup/call/teardown),
    # we WANT validation to catch configuration issues.
    #
    # PYTEST_CURRENT_TEST is set during ALL pytest phases (collection, setup, call, teardown).
    # During collection: "test_file.py::test_name" (no phase suffix)
    # During execution: "test_file.py::test_name (setup|call|teardown)"
    # We detect collection by checking if PYTEST_CURRENT_TEST exists but doesn't contain any phase indicator.
    in_pytest_collection = os.getenv("PYTEST_CURRENT_TEST") is not None and not any(
        phase in os.getenv("PYTEST_CURRENT_TEST", "")
        for phase in ["setup", "call", "teardown"]
    )

    if in_pytest_collection:
        logger.debug(
            "Pytest collection phase detected - skipping validation. "
            "Validation will run during actual test execution (setup/call/teardown)."
        )
        return settings

    # Validate required services on first load
    errors = settings.validate_required_services()
    if errors:
        error_msg = "\n".join(f"  - {error}" for error in errors)
        logger.error(f"Configuration validation failed:\n{error_msg}")

        # CRITICAL: Enforce strict validation in production mode
        # Production deployments MUST have valid configuration
        if settings.environment == "production":
            raise ValueError(
                f"Configuration validation failed in production mode. "
                f"Cannot start service with invalid configuration. "
                f"Errors found:\n{error_msg}"
            )

        # Development/test: send notification (separate concern)
        _send_config_error_notification(errors)

        # Note: In development/test modes, we log but don't raise to allow partial configuration
        # Production mode enforces strict validation (see ValueError raise above)
    else:
        logger.info("Configuration loaded and validated successfully")

    return settings


def reload_settings() -> Settings:
    """
    Force reload of settings from environment.

    Useful for testing or when environment variables change at runtime.
    Clears the lru_cache to force recreation of the Settings instance.

    Returns:
        New Settings instance

    Example:
        >>> import os
        >>> os.environ['POSTGRES_PORT'] = '5432'
        >>> settings = reload_settings()
        >>> print(settings.postgres_port)
        5432
    """
    get_settings.cache_clear()
    return get_settings()

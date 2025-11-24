"""
OmniClaude Configuration Package.

This package provides centralized, type-safe configuration management
using Pydantic Settings.

Core Features:
    - Type-safe configuration with Pydantic validation
    - Environment variable loading with .env file support
    - Multiple environment support (.env.dev, .env.test, .env.prod)
    - Sensitive value sanitization for logging
    - Validation on startup with clear error messages

Usage:
    Basic usage - import the singleton settings instance:

        from config import settings

        # Access configuration with full type safety
        print(settings.postgres_host)  # str
        print(settings.postgres_port)  # int
        print(settings.kafka_enable_intelligence)  # bool

    Get PostgreSQL connection string:

        from config import settings

        # Sync connection
        dsn = settings.get_postgres_dsn()
        # postgresql://postgres:password@192.168.86.200:5436/omninode_bridge

        # Async connection (for asyncpg)
        async_dsn = settings.get_postgres_dsn(async_driver=True)
        # postgresql+asyncpg://postgres:password@192.168.86.200:5436/omninode_bridge

    Validate configuration:

        from config import settings

        errors = settings.validate_required_services()
        if errors:
            for error in errors:
                print(f"Configuration Error: {error}")
            exit(1)

    Log configuration (with sanitization):

        from config import settings
        import logging

        logger = logging.getLogger(__name__)
        settings.log_configuration(logger)

    Reload configuration (useful for testing):

        from config import reload_settings

        # Change environment variable
        import os
        os.environ['POSTGRES_PORT'] = '5432'

        # Force reload
        settings = reload_settings()
        print(settings.postgres_port)  # 5432

Migration from os.getenv():
    Old pattern:
        import os
        kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))

    New pattern:
        from config import settings
        kafka_servers = settings.kafka_bootstrap_servers  # Type-safe, validated
        postgres_port = settings.postgres_port  # Already int, validated

Environment Variables:
    All configuration is loaded from environment variables or .env files.
    See .env.example for complete reference.

    Priority order:
        1. System environment variables (highest priority)
        2. .env.{ENVIRONMENT} file (e.g., .env.dev, .env.prod)
        3. .env file (default/fallback)
        4. Default values in Settings class (lowest priority)

Configuration Sections:
    1. External Service Discovery (archon services on 192.168.86.101)
    2. Shared Infrastructure (Kafka on 192.168.86.200, PostgreSQL)
    3. AI Provider API Keys (Gemini, Z.ai, OpenAI)
    4. Local Services (Qdrant, Valkey)
    5. Feature Flags & Optimization
    6. Optional Configuration (paths, routing, etc.)

See Also:
    - config/README.md: Detailed usage documentation
    - config/settings.py: Settings class implementation
    - .env.example: Configuration template

Implementation:
    Phase 2 - ADR-001 Type-Safe Configuration Framework
"""

from .settings import Settings, get_settings, reload_settings


# Export singleton instance for easy imports
settings = get_settings()

# Public API
__all__ = [
    "Settings",
    "get_settings",
    "reload_settings",
    "settings",
]

# Version information
__version__ = "1.0.0"
__author__ = "OmniClaude Team"
__description__ = "Type-safe configuration management for OmniClaude"

#!/usr/bin/env python3
"""
Configuration Migration Template

Use this template as a reference when migrating files from legacy
configuration patterns (os.getenv, dotenv) to Pydantic Settings.

BEFORE running this template:
1. Determine your file's location (hook, skill, service, agent)
2. Calculate correct path depth to project root
3. Verify all needed variables exist in Settings class
4. Read STANDARDIZATION_GUIDE.md for detailed instructions

AFTER migration:
1. Test import: python3 your_file.py
2. Test functionality with actual workload
3. Remove all commented legacy code
4. Update this file's docstring with migration notes
"""

# =============================================================================
# STEP 1: PATH SETUP (Choose pattern based on file location)
# =============================================================================

# --- OPTION A: Hooks (~/.claude/hooks/*.py) ---
# Use absolute path for hooks (location is fixed)
import sys


sys.path.insert(0, "/Volumes/PRO-G40/Code/omniclaude")

# --- OPTION B: Skills (.claude/skills/<name>/scripts/*.py) ---
# Use relative path (adjust parents[] count based on depth)
# import sys
# from pathlib import Path
# project_root = Path(__file__).resolve().parents[4]  # 4 levels up for skills
# sys.path.insert(0, str(project_root))

# --- OPTION C: Services/Agents (agents/, services/) ---
# No sys.path needed - already in project path
# (Just remove this section entirely)

# =============================================================================
# STEP 2: IMPORT SETTINGS
# =============================================================================

from config import settings


# =============================================================================
# STEP 3: REMOVE LEGACY IMPORTS
# =============================================================================

# ❌ DELETE THESE:
# import os
# from dotenv import load_dotenv
# load_dotenv()

# =============================================================================
# STEP 4: MIGRATE CONFIGURATION ACCESS
# =============================================================================

# --- Database Configuration ---

# ❌ BEFORE:
# db_host = os.getenv("POSTGRES_HOST", "localhost")
# db_port = int(os.getenv("POSTGRES_PORT", "5432"))
# db_user = os.getenv("POSTGRES_USER", "postgres")
# db_password = os.getenv("POSTGRES_PASSWORD")
# db_name = os.getenv("POSTGRES_DATABASE", "mydb")

# ✅ AFTER:
db_host = settings.postgres_host
db_port = settings.postgres_port
db_user = settings.postgres_user
db_password = settings.postgres_password
db_name = settings.postgres_database

# ✅ EVEN BETTER: Use helper method
db_dsn = settings.get_postgres_dsn()  # Sync driver
# db_dsn = settings.get_postgres_dsn(async_driver=True)  # For asyncpg

# --- API Keys ---

# ❌ BEFORE:
# gemini_key = os.getenv("GEMINI_API_KEY")
# if not gemini_key:
#     raise ValueError("GEMINI_API_KEY not set")

# ✅ AFTER:
gemini_key = settings.gemini_api_key
if not gemini_key:
    raise ValueError(
        "GEMINI_API_KEY not configured. " "Set in .env file at project root."
    )

# --- Kafka Configuration ---

# ❌ BEFORE:
# kafka_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
# kafka_timeout = int(os.getenv("KAFKA_REQUEST_TIMEOUT_MS", "5000"))
# enable_intelligence = os.getenv("KAFKA_ENABLE_INTELLIGENCE", "true").lower() == "true"

# ✅ AFTER:
kafka_servers = settings.kafka_bootstrap_servers
kafka_timeout = settings.kafka_request_timeout_ms
enable_intelligence = settings.kafka_enable_intelligence

# ✅ WITH HELPER (handles legacy aliases):
kafka_servers = settings.get_effective_kafka_bootstrap_servers()

# --- Service URLs ---

# ❌ BEFORE:
# intelligence_url = os.getenv(
#     "ARCHON_INTELLIGENCE_URL",
#     "http://192.168.86.101:8053"
# )

# ✅ AFTER:
intelligence_url = settings.archon_intelligence_url

# --- Feature Flags ---

# ❌ BEFORE:
# enable_cache = os.getenv("ENABLE_INTELLIGENCE_CACHE", "true").lower() == "true"
# min_quality = float(os.getenv("MIN_PATTERN_QUALITY", "0.5"))
# enable_filter = os.getenv("ENABLE_PATTERN_QUALITY_FILTER", "false").lower() == "true"

# ✅ AFTER:
enable_cache = settings.enable_intelligence_cache
min_quality = settings.min_pattern_quality
enable_filter = settings.enable_pattern_quality_filter

# --- Cache TTLs ---

# ❌ BEFORE:
# cache_ttl_patterns = int(os.getenv("CACHE_TTL_PATTERNS", "300"))
# cache_ttl_infra = int(os.getenv("CACHE_TTL_INFRASTRUCTURE", "3600"))

# ✅ AFTER:
cache_ttl_patterns = settings.cache_ttl_patterns
cache_ttl_infra = settings.cache_ttl_infrastructure

# =============================================================================
# STEP 5: VALIDATION (Optional but recommended)
# =============================================================================


def validate_configuration():
    """
    Validate configuration on startup.

    This is optional since Settings validates automatically,
    but you can add custom validation logic here.
    """
    errors = settings.validate_required_services()
    if errors:
        print("Configuration errors found:")
        for error in errors:
            print(f"  - {error}")
        raise ValueError("Invalid configuration")

    # Custom validation
    if settings.enable_pattern_quality_filter and settings.min_pattern_quality < 0.5:
        print(
            "Warning: min_pattern_quality is below 0.5, most patterns will be filtered"
        )

    print("✅ Configuration validated successfully")


# =============================================================================
# STEP 6: LOGGING (Optional but recommended for debugging)
# =============================================================================


def log_configuration():
    """Log configuration (with sensitive values sanitized)."""
    import logging

    logger = logging.getLogger(__name__)
    settings.log_configuration(logger)


# =============================================================================
# EXAMPLE: Complete Migration
# =============================================================================


def example_database_connection():
    """Example: Database connection using Pydantic Settings."""
    import psycopg2

    # ✅ Using helper method (recommended)
    conn = psycopg2.connect(settings.get_postgres_dsn())

    # ✅ OR using individual fields
    # conn = psycopg2.connect(
    #     host=settings.postgres_host,
    #     port=settings.postgres_port,
    #     database=settings.postgres_database,
    #     user=settings.postgres_user,
    #     password=settings.postgres_password
    # )

    return conn


async def example_kafka_producer():
    """Example: Kafka producer using Pydantic Settings."""
    from aiokafka import AIOKafkaProducer

    # ✅ Using settings fields
    producer = AIOKafkaProducer(
        bootstrap_servers=settings.get_effective_kafka_bootstrap_servers(),
        request_timeout_ms=settings.kafka_request_timeout_ms,
    )

    await producer.start()
    return producer


def example_api_call():
    """Example: API call with settings."""
    import httpx

    # ✅ Using settings for URL and timeout
    with httpx.Client(timeout=settings.kafka_request_timeout_ms / 1000.0) as client:
        response = client.post(
            f"{settings.archon_intelligence_url}/api/query", json={"prompt": "test"}
        )
        return response.json()


def example_feature_flags():
    """Example: Feature flag usage."""
    patterns = fetch_patterns()

    # ✅ Quality filtering
    if settings.enable_pattern_quality_filter:
        patterns = [p for p in patterns if p.quality >= settings.min_pattern_quality]

    # ✅ Caching
    if settings.enable_intelligence_cache:
        cache_patterns(patterns, ttl=settings.cache_ttl_patterns)

    return patterns


def fetch_patterns():
    """Placeholder for pattern fetching."""
    return []


def cache_patterns(patterns, ttl):
    """Placeholder for pattern caching."""
    pass


# =============================================================================
# TESTING
# =============================================================================

if __name__ == "__main__":
    # Run validation
    validate_configuration()

    # Log configuration (optional)
    # log_configuration()

    # Test configuration access
    print("\nConfiguration Test:")
    print(f"  PostgreSQL: {settings.postgres_host}:{settings.postgres_port}")
    print(f"  Kafka: {settings.kafka_bootstrap_servers}")
    print(f"  Gemini API Key: {'configured' if settings.gemini_api_key else 'not set'}")
    print(
        f"  Intelligence Cache: {'enabled' if settings.enable_intelligence_cache else 'disabled'}"
    )
    print("\n✅ Migration template test passed!")

# =============================================================================
# MIGRATION CHECKLIST
# =============================================================================
"""
Migration Checklist:

Pre-Migration:
[ ] Identified all os.getenv() calls
[ ] Determined file location (hook/skill/service/agent)
[ ] Calculated correct path depth
[ ] Verified all variables exist in Settings class

Migration:
[ ] Added sys.path.insert() (if needed)
[ ] Imported settings from config
[ ] Replaced all os.getenv() with settings.<field>
[ ] Used helper methods where available
[ ] Removed legacy imports (os, dotenv)
[ ] Removed load_dotenv() calls
[ ] Removed manual validation

Post-Migration:
[ ] Tested import: python3 <file>.py
[ ] Tested functionality with actual workload
[ ] Verified .env loading works
[ ] Checked error messages are clear
[ ] Removed commented legacy code

Code Review:
[ ] No os.getenv() remaining
[ ] No dotenv imports remaining
[ ] Correct sys.path for file location
[ ] Helper methods used where available
[ ] Error handling is graceful
"""

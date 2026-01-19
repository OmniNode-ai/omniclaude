#!/usr/bin/env python3
"""
Test to verify .env configuration is loaded correctly for distributed testing.

Migration Status: Migrated to Pydantic Settings (Phase 2)
- Replaced os.getenv() with settings.* pattern (14 calls removed)
- Uses type-safe configuration from config/settings.py
- Maintains backward compatibility for TRACEABILITY_DB_* variables
- All environment variables now accessed via Pydantic Settings framework

Note: These tests require .env with Kafka/Postgres configuration.
Marked as integration tests - skipped in CI.
"""

import pytest

from config import settings


@pytest.mark.integration
def test_env_configuration_loaded():
    """Verify .env configuration is loaded correctly into Pydantic Settings."""
    # Test Kafka configuration
    # Note: Environment may set "omninode-bridge-redpanda:9092" for Docker services
    # or "192.168.86.200:29092" for host scripts. Test for non-empty value.
    assert settings.kafka_bootstrap_servers, "KAFKA_BOOTSTRAP_SERVERS must be set"

    # Test PostgreSQL configuration
    # Note: TRACEABILITY_DB_* env vars map to POSTGRES_* in settings
    # Environment may use "omninode-bridge-postgres" (Docker) or "192.168.86.200" (host)
    assert settings.postgres_host, "POSTGRES_HOST must be set"
    assert (
        settings.postgres_port == 5436 or settings.postgres_port == 5432
    ), f"POSTGRES_PORT should be 5436 (external) or 5432 (internal), got {settings.postgres_port}"

    # Verify password exists (without checking specific value for security)
    password = settings.get_effective_postgres_password()
    assert password is not None, "POSTGRES_PASSWORD must be set"
    assert len(password) > 0, "POSTGRES_PASSWORD cannot be empty"

    # Database name may vary by environment (omninode_bridge for prod, test_db for CI)
    assert settings.postgres_database, "POSTGRES_DATABASE must be set"
    assert (
        settings.postgres_user == "postgres" or settings.postgres_user == "test"
    ), f"POSTGRES_USER should be 'postgres' or 'test', got {settings.postgres_user}"

    # Verify DSN is constructed correctly using helper method
    pg_dsn = settings.get_postgres_dsn()
    assert pg_dsn is not None, "PostgreSQL DSN must be generated"
    assert settings.postgres_database in pg_dsn, "DSN should contain database name"
    # Verify DSN contains a password (without checking specific value)
    assert ":@" not in pg_dsn, "DSN should contain a password (not empty)"


@pytest.mark.integration
def test_postgres_dsn_construction():
    """Verify PostgreSQL DSN is constructed correctly using Pydantic Settings."""
    # Use settings helper method for DSN construction (replaces manual construction)
    dsn = settings.get_postgres_dsn()

    # Verify DSN is well-formed
    assert dsn.startswith("postgresql://"), "DSN should use postgresql:// scheme"
    assert (
        f":{settings.postgres_port}/" in dsn
    ), f"DSN should contain port {settings.postgres_port}"
    assert settings.postgres_database in dsn, "DSN should contain database name"
    assert settings.postgres_user in dsn, "DSN should contain username"

    # Verify DSN contains a password (without checking specific value)
    # DSN format: postgresql://user:password@host:port/database
    # If password is empty, you'd see "user:@host", so ":@" indicates missing password
    assert ":@" not in dsn, "DSN should contain a password (not empty)"
    print(f"\n✅ PostgreSQL DSN constructed: {dsn.split(':')[0]}://[redacted]")


@pytest.mark.integration
def test_kafka_brokers_configuration():
    """Verify Kafka brokers configuration uses Pydantic Settings."""
    # Get Kafka bootstrap servers from settings (with legacy alias support)
    brokers = settings.get_effective_kafka_bootstrap_servers()

    # Verify brokers are configured (value depends on deployment context)
    # Docker services: "omninode-bridge-redpanda:9092"
    # Host scripts: "192.168.86.200:29092"
    assert brokers, "KAFKA_BOOTSTRAP_SERVERS must be configured"
    assert ":" in brokers, "Kafka brokers should include port (format: host:port)"

    # Verify it's one of the expected values
    valid_values = [
        "omninode-bridge-redpanda:9092",  # Docker internal
        "192.168.86.200:29092",  # Host external
        "localhost:29092",  # Local development
        "localhost:9092",  # Local development alternative
    ]
    assert any(
        brokers.startswith(valid.split(":")[0]) for valid in valid_values
    ), f"Kafka brokers should use known host, got: {brokers}"

    print(f"\n✅ Kafka Bootstrap Servers: {brokers}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

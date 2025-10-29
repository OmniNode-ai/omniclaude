#!/usr/bin/env python3
"""
Test to verify .env configuration is loaded correctly for distributed testing.
"""

import os

import pytest


def test_env_configuration_loaded():
    """Verify .env configuration is loaded correctly."""
    # These should be loaded from .env by conftest.py
    assert os.getenv("KAFKA_BOOTSTRAP_SERVERS") == "omninode-bridge-redpanda:9092"
    assert os.getenv("TRACEABILITY_DB_HOST") == "omninode-bridge-postgres"
    assert os.getenv("TRACEABILITY_DB_PORT") == "5436"
    assert os.getenv("TRACEABILITY_DB_PASSWORD") == "***REDACTED***"
    assert os.getenv("TRACEABILITY_DB_NAME") == "omninode_bridge"
    assert os.getenv("TRACEABILITY_DB_USER") == "postgres"

    # Verify PG_DSN is constructed correctly
    pg_dsn = os.getenv("PG_DSN")
    assert pg_dsn is not None
    assert "omninode-bridge-postgres:5436" in pg_dsn
    assert "***REDACTED***" in pg_dsn
    assert "omninode_bridge" in pg_dsn


def test_postgres_dsn_construction():
    """Verify PostgreSQL DSN is constructed correctly from env vars."""
    # Simulate what the fixture does
    dsn = os.getenv("PG_DSN")
    if not dsn:
        host = os.getenv("TRACEABILITY_DB_HOST", "localhost")
        port = os.getenv("TRACEABILITY_DB_PORT", "5436")
        user = os.getenv("TRACEABILITY_DB_USER", "postgres")
        password = os.getenv("TRACEABILITY_DB_PASSWORD", "***REDACTED***")
        database = os.getenv("TRACEABILITY_DB_NAME", "omninode_bridge")
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    assert "omninode-bridge-postgres:5436" in dsn
    assert "***REDACTED***" in dsn
    assert "omninode_bridge" in dsn
    print(f"\n✅ PostgreSQL DSN: {dsn}")


def test_kafka_brokers_configuration():
    """Verify Kafka brokers configuration uses correct address."""
    brokers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    assert brokers == "omninode-bridge-redpanda:9092"
    print(f"\n✅ Kafka Bootstrap Servers: {brokers}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

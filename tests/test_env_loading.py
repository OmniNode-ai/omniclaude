#!/usr/bin/env python3
"""
Test to verify .env configuration is loaded correctly for distributed testing.
"""

import os

import pytest


def test_env_configuration_loaded():
    """Verify .env configuration is loaded correctly."""
    # These should be loaded from .env by conftest.py
    assert os.getenv("KAFKA_BROKERS") == "192.168.86.200:29102"
    assert os.getenv("TRACEABILITY_DB_HOST") == "192.168.86.200"
    assert os.getenv("TRACEABILITY_DB_PORT") == "5436"
    assert os.getenv("TRACEABILITY_DB_PASSWORD") == "omninode_remote_2024_secure"
    assert os.getenv("TRACEABILITY_DB_NAME") == "omninode_bridge"
    assert os.getenv("TRACEABILITY_DB_USER") == "postgres"

    # Verify PG_DSN is constructed correctly
    pg_dsn = os.getenv("PG_DSN")
    assert pg_dsn is not None
    assert "192.168.86.200:5436" in pg_dsn
    assert "omninode_remote_2024_secure" in pg_dsn
    assert "omninode_bridge" in pg_dsn


def test_postgres_dsn_construction():
    """Verify PostgreSQL DSN is constructed correctly from env vars."""
    # Simulate what the fixture does
    dsn = os.getenv("PG_DSN")
    if not dsn:
        host = os.getenv("TRACEABILITY_DB_HOST", "localhost")
        port = os.getenv("TRACEABILITY_DB_PORT", "5436")
        user = os.getenv("TRACEABILITY_DB_USER", "postgres")
        password = os.getenv("TRACEABILITY_DB_PASSWORD", "omninode_remote_2024_secure")
        database = os.getenv("TRACEABILITY_DB_NAME", "omninode_bridge")
        dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    assert "192.168.86.200:5436" in dsn
    assert "omninode_remote_2024_secure" in dsn
    assert "omninode_bridge" in dsn
    print(f"\n✅ PostgreSQL DSN: {dsn}")


def test_kafka_brokers_configuration():
    """Verify Kafka brokers configuration uses remote address."""
    brokers = os.getenv("KAFKA_BROKERS", "localhost:29092")
    assert brokers == "192.168.86.200:29102"
    print(f"\n✅ Kafka Brokers: {brokers}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

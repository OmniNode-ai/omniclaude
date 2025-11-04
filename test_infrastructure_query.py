#!/usr/bin/env python3
"""
Test script for infrastructure query implementation.

Tests the new _query_infrastructure() method to verify it properly
queries and returns connection details for all services.
"""

import asyncio
import json
import sys
from pathlib import Path

# Add agents/lib to path
lib_path = Path(__file__).parent / "agents" / "lib"
sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector  # noqa: E402


async def test_infrastructure_query():
    """Test infrastructure querying."""
    print("=" * 70)
    print("Infrastructure Query Test")
    print("=" * 70)
    print()

    # Load environment variables
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"✓ Loaded environment from {env_file}")
    else:
        print(f"⚠ No .env file found at {env_file}")
    print()

    # Create manifest injector
    async with ManifestInjector() as injector:
        print("Testing infrastructure query methods individually...")
        print()

        # Test PostgreSQL
        print("1. Testing PostgreSQL connection...")
        try:
            pg_info = await injector._query_postgresql()
            print(f"   Status: {pg_info.get('status', 'unknown')}")
            if pg_info.get("status") == "connected":
                print(f"   ✓ Connected to {pg_info['host']}:{pg_info['port']}/{pg_info['database']}")
                print(f"   ✓ Tables: {pg_info.get('tables', 0)}")
            else:
                print(f"   ✗ Error: {pg_info.get('error', 'unknown')}")
            print()
        except Exception as e:
            print(f"   ✗ Exception: {e}")
            print()

        # Test Kafka
        print("2. Testing Kafka connection...")
        try:
            kafka_info = await injector._query_kafka()
            print(f"   Status: {kafka_info.get('status', 'unknown')}")
            if kafka_info.get("status") == "connected":
                print(f"   ✓ Connected to {kafka_info['bootstrap_servers']}")
                print(f"   ✓ Topics: {kafka_info.get('topics', 0)}")
            else:
                print(f"   ✗ Error: {kafka_info.get('error', 'unknown')}")
            print()
        except Exception as e:
            print(f"   ✗ Exception: {e}")
            print()

        # Test Qdrant
        print("3. Testing Qdrant connection...")
        try:
            qdrant_info = await injector._query_qdrant()
            print(f"   Status: {qdrant_info.get('status', 'unknown')}")
            if qdrant_info.get("status") == "available":
                print(f"   ✓ Connected to {qdrant_info['url']}")
                print(f"   ✓ Collections: {qdrant_info.get('collections', 0)}")
                print(f"   ✓ Vectors: {qdrant_info.get('vectors', 0)}")
            else:
                print(f"   ✗ Error: {qdrant_info.get('error', 'unknown')}")
            print()
        except Exception as e:
            print(f"   ✗ Exception: {e}")
            print()

        # Test Docker
        print("4. Testing Docker services query...")
        try:
            docker_services = await injector._query_docker_services()
            if docker_services:
                print(f"   ✓ Found {len(docker_services)} services")
                for service in docker_services[:5]:  # Show first 5
                    print(f"     - {service['name']}: {service['status']}")
                if len(docker_services) > 5:
                    print(f"     ... and {len(docker_services) - 5} more")
            else:
                print("   ⚠ No Docker services found or Docker not available")
            print()
        except Exception as e:
            print(f"   ✗ Exception: {e}")
            print()

        # Test full infrastructure query
        print("5. Testing full infrastructure query (parallel)...")
        try:
            from intelligence_event_client import IntelligenceEventClient

            # Create a mock client (we're not using it for the new implementation)
            client = IntelligenceEventClient()

            result = await injector._query_infrastructure(
                client=client,
                correlation_id="test-infra-query"
            )

            print("   Full infrastructure result:")
            print()
            print(json.dumps(result, indent=2))
            print()

            # Validate structure
            assert "remote_services" in result, "Missing remote_services"
            assert "local_services" in result, "Missing local_services"
            assert "docker_services" in result, "Missing docker_services"

            # Check if services are populated (not empty {})
            pg = result["remote_services"].get("postgresql", {})
            if pg and "status" in pg:
                print(f"   ✓ PostgreSQL populated: {pg['status']}")
            else:
                print("   ✗ PostgreSQL not populated")

            kafka = result["remote_services"].get("kafka", {})
            if kafka and "status" in kafka:
                print(f"   ✓ Kafka populated: {kafka['status']}")
            else:
                print("   ✗ Kafka not populated")

            qdrant = result["local_services"].get("qdrant", {})
            if qdrant and "status" in qdrant:
                print(f"   ✓ Qdrant populated: {qdrant['status']}")
            else:
                print("   ✗ Qdrant not populated")

            print()
            print("=" * 70)
            print("✓ Infrastructure query test completed successfully!")
            print("=" * 70)

        except Exception as e:
            print(f"   ✗ Full query failed: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_infrastructure_query())

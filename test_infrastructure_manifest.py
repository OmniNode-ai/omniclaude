#!/usr/bin/env python3
"""
Test script for infrastructure manifest formatting.

Tests the complete flow from _query_infrastructure() to formatted manifest output.
"""

import asyncio
import sys
from pathlib import Path


# Add agents/lib to path
lib_path = Path(__file__).parent / "agents" / "lib"
sys.path.insert(0, str(lib_path))

from manifest_injector import ManifestInjector  # noqa: E402


async def test_infrastructure_manifest():
    """Test infrastructure manifest generation and formatting."""
    import uuid

    print("=" * 70)
    print("Infrastructure Manifest Test")
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

    # Generate manifest with infrastructure section
    async with ManifestInjector() as injector:
        print("Generating manifest with infrastructure section...")
        print()

        # Generate full manifest with valid UUID
        correlation_id = str(uuid.uuid4())
        manifest = await injector.generate_dynamic_manifest_async(
            correlation_id=correlation_id
        )

        # Format only the infrastructure section
        formatted = injector.format_for_prompt(sections=["infrastructure"])

        print(formatted)
        print()

        # Show statistics
        infra_data = manifest.get("infrastructure", {})
        remote = infra_data.get("remote_services", {})
        local = infra_data.get("local_services", {})
        docker = infra_data.get("docker_services", [])

        print("=" * 70)
        print("Infrastructure Statistics:")
        print("=" * 70)
        print()

        # PostgreSQL
        pg = remote.get("postgresql", {})
        if pg.get("status") == "connected":
            print(f"✓ PostgreSQL: {pg['host']}:{pg['port']}/{pg['database']}")
            print(f"  - Tables: {pg.get('tables', 0)}")
        else:
            print(f"✗ PostgreSQL: {pg.get('status', 'unavailable')}")
        print()

        # Kafka
        kafka = remote.get("kafka", {})
        if kafka.get("status") == "connected":
            print(f"✓ Kafka: {kafka['bootstrap_servers']}")
            print(f"  - Topics: {kafka.get('topics', 0)}")
        else:
            print(f"✗ Kafka: {kafka.get('status', 'unavailable')}")
        print()

        # Qdrant
        qdrant = local.get("qdrant", {})
        if qdrant.get("status") == "available":
            print(f"✓ Qdrant: {qdrant['url']}")
            print(f"  - Collections: {qdrant.get('collections', 0)}")
            print(f"  - Vectors: {qdrant.get('vectors', 0)}")
        else:
            print(f"✗ Qdrant: {qdrant.get('status', 'unavailable')}")
        print()

        # Docker
        if docker:
            print(f"✓ Docker: {len(docker)} services found")
            for service in docker[:5]:
                print(f"  - {service['name']}: {service['status']}")
            if len(docker) > 5:
                print(f"  ... and {len(docker) - 5} more")
        else:
            print("⚠ Docker: No services found or not available")
        print()

        print("=" * 70)
        print("✓ Infrastructure manifest test completed successfully!")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_infrastructure_manifest())

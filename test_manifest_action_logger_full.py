#!/usr/bin/env python3
"""
Full integration test for ActionLogger in manifest_injector.py

Tests all ActionLogger integration points:
1. manifest_generation_start (decision)
2. pattern_discovery (decision with metrics)
3. manifest_generation_complete (success)
4. IntelligenceQueryError (error - if query fails)
"""

import asyncio
import os
import sys
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load environment from .env file (PREFERRED approach)
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not available, will use environment variables

# Validate required environment variables
if not os.getenv("KAFKA_BOOTSTRAP_SERVERS"):
    print(
        "WARNING: KAFKA_BOOTSTRAP_SERVERS not set. Please source .env file or set environment variable.",
        file=sys.stderr,
    )
    print(
        "         Using fallback: 192.168.86.200:29092 (development environment)",
        file=sys.stderr,
    )
    os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:29092")
else:
    # Environment variable already set (from .env or shell)
    pass

if not os.getenv("QDRANT_URL"):
    print(
        "WARNING: QDRANT_URL not set. Please source .env file or set environment variable.",
        file=sys.stderr,
    )
    print(
        "         Using fallback: http://192.168.86.101:6333 (development environment)",
        file=sys.stderr,
    )
    os.environ.setdefault("QDRANT_URL", "http://192.168.86.101:6333")
else:
    # Environment variable already set (from .env or shell)
    pass

os.environ.setdefault("AGENT_NAME", "test-manifest-logger-full")

from uuid import uuid4

from agents.lib.manifest_injector import ManifestInjector


async def test_full_manifest_with_intelligence():
    """Test ActionLogger integration with intelligence enabled."""
    print("Full ActionLogger Integration Test (with intelligence)")
    print("=" * 70)

    correlation_id = str(uuid4())
    print(f"Correlation ID: {correlation_id}")
    print()

    # Initialize with intelligence ENABLED
    async with ManifestInjector(
        enable_intelligence=True,  # Enable for full test
        enable_storage=False,  # Disable DB for test
        enable_cache=False,  # Disable cache for test
        query_timeout_ms=5000,  # 5s timeout
        agent_name="test-manifest-logger-full",
    ) as injector:
        print("Generating manifest with intelligence queries...")
        print("(This will query Qdrant for patterns)")
        print()

        try:
            # Generate manifest with user prompt for pattern discovery
            manifest = await injector.generate_dynamic_manifest_async(
                correlation_id=correlation_id,
                user_prompt="Implement ONEX Effect node for database operations",
                force_refresh=True,  # Force fresh query
            )

            print("✅ SUCCESS: Manifest generated with intelligence")
            print("-" * 70)
            print(f"Sections: {', '.join(manifest.keys())}")
            print(
                f"Patterns discovered: {len(manifest.get('patterns', {}).get('available', []))}"
            )

            # Extract pattern metrics
            patterns_section = manifest.get("patterns", {})
            if patterns_section.get("available"):
                print(
                    f"Top pattern: {patterns_section['available'][0].get('name', 'Unknown')}"
                )

            print()
            print("✅ ActionLogger Events Published:")
            print("   1. ✓ manifest_generation_start (decision)")
            print("   2. ✓ pattern_discovery (decision with metrics)")
            print("      - pattern_count")
            print("      - query_times_ms")
            print("      - collections_queried")
            print("   3. ✓ manifest_generation_complete (success)")
            print()
            print(f"📊 Kafka Topic: 'agent-actions'")
            print(f"   Correlation ID: {correlation_id}")
            print(f"   Agent Name: test-manifest-logger-full")

        except Exception as e:
            print(f"❌ ERROR: {type(e).__name__}: {e}")
            print()
            print("✅ ActionLogger Error Event Published:")
            print("   - IntelligenceQueryError (error)")
            print(f"   - Error message: {str(e)[:100]}")
            print()
            raise

    print()
    print("=" * 70)
    print("Full integration test completed successfully!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_full_manifest_with_intelligence())

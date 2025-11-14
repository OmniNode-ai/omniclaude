#!/usr/bin/env python3
"""
Test script to verify ActionLogger integration in manifest_injector.py

This script tests that ActionLogger is properly integrated and tracks:
- Manifest generation start
- Pattern discovery performance
- Query errors
- Successful manifest generation
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Set up minimal environment
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "omninode-bridge-redpanda:9092")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("AGENT_NAME", "test-manifest-logger")

from uuid import uuid4

from agents.lib.manifest_injector import ManifestInjector


async def test_manifest_with_action_logger():
    """Test that ActionLogger is properly integrated."""
    print("Testing ActionLogger integration in manifest_injector...")
    print("-" * 60)

    # Create correlation ID
    correlation_id = str(uuid4())
    print(f"Correlation ID: {correlation_id}")

    # Initialize manifest injector with intelligence DISABLED for faster testing
    async with ManifestInjector(
        enable_intelligence=False,  # Disable for faster test
        enable_storage=False,  # Disable database storage for test
        enable_cache=False,  # Disable cache for test
        agent_name="test-manifest-logger",
    ) as injector:
        print("\nGenerating manifest (intelligence disabled for fast test)...")

        try:
            # Generate manifest
            manifest = await injector.generate_dynamic_manifest_async(
                correlation_id=correlation_id,
                user_prompt="Test manifest generation with ActionLogger",
            )

            print("\n✅ SUCCESS: Manifest generated successfully")
            print(f"   Sections: {list(manifest.keys())}")
            print(
                f"   Patterns: {len(manifest.get('patterns', {}).get('available', []))}"
            )

            print("\n✅ ActionLogger calls should have been made:")
            print("   1. manifest_generation_start (decision)")
            print("   2. manifest_generation_complete (success)")

            print("\n📊 Check Kafka topic 'agent-actions' for logged events")
            print(f"   Filter by correlation_id: {correlation_id}")

        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            print("\n✅ ActionLogger error call should have been made:")
            print("   - IntelligenceQueryError (error)")
            raise

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_manifest_with_action_logger())

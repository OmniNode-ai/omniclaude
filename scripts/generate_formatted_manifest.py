#!/usr/bin/env python3
"""
Generate the actual formatted manifest that gets injected into agent prompts.
This shows exactly what agents see when manifest intelligence is injected.
"""

import asyncio
import os
import sys
import uuid
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


async def main():
    """Generate and save the formatted manifest."""

    # Verify required environment variables
    if not os.environ.get("POSTGRES_PASSWORD"):
        print("❌ ERROR: POSTGRES_PASSWORD environment variable not set")
        print("   Please run: source .env")
        return 1

    # Set up environment variables (non-sensitive defaults)
    os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "192.168.86.200:9092")
    os.environ.setdefault("POSTGRES_HOST", "192.168.86.200")
    os.environ.setdefault("POSTGRES_PORT", "5436")
    os.environ.setdefault("POSTGRES_DATABASE", "omninode_bridge")
    os.environ.setdefault("POSTGRES_USER", "postgres")
    os.environ.setdefault("AGENT_NAME", "manifest-generator")

    print("🔧 Initializing ManifestInjector...")
    injector = ManifestInjector()

    # Generate a valid UUID for correlation_id
    correlation_id = str(uuid.uuid4())
    print(f"📋 Correlation ID: {correlation_id}")

    print("📡 Generating manifest data via Kafka event bus...")
    manifest_data = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id
    )

    if not manifest_data:
        print("❌ Failed to generate manifest data")
        return 1

    print("✅ Manifest data generated successfully")
    print(f"   - Patterns: {len(manifest_data.get('patterns', []))} found")
    print(
        f"   - Infrastructure: {len(manifest_data.get('infrastructure', {}))} services"
    )
    print(f"   - Models: {len(manifest_data.get('models', {}))} model configurations")
    print(f"   - Schemas: {len(manifest_data.get('database_schemas', {}))} tables")
    print(
        f"   - Debug Intelligence: {manifest_data.get('debug_intelligence', {}).get('total_similar', 0)} similar workflows"
    )

    print("\n📝 Formatting manifest for agent prompt injection...")
    formatted_manifest = injector.format_for_prompt(manifest_data)

    # Save to file
    output_file = project_root / "ACTUAL_MANIFEST_OUTPUT.txt"
    print(f"\n💾 Saving formatted manifest to: {output_file}")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(formatted_manifest)

    # Get file stats
    file_size = output_file.stat().st_size
    line_count = formatted_manifest.count("\n")

    print("\n✅ Success!")
    print(f"   📄 File: {output_file}")
    print(f"   📊 Size: {file_size:,} bytes ({file_size / 1024:.1f} KB)")
    print(f"   📏 Lines: {line_count:,}")

    # Show preview (first 100 lines)
    print("\n📖 Preview (first 100 lines):")
    print("=" * 80)
    lines = formatted_manifest.split("\n")
    for i, line in enumerate(lines[:100], 1):
        print(line)

    if len(lines) > 100:
        print(f"\n... ({len(lines) - 100} more lines)")

    print("=" * 80)

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

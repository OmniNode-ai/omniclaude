#!/usr/bin/env python3
"""
Display a full, formatted manifest with all sections.
"""

import asyncio
import json
import sys
import uuid
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from agents.lib.manifest_injector import ManifestInjector


async def main():
    """Generate and display a full manifest."""
    print("=" * 80)
    print("FULL MANIFEST GENERATION")
    print("=" * 80)
    print()

    # Generate manifest
    injector = ManifestInjector()
    correlation_id = str(uuid.uuid4())
    prompt = "ONEX authentication system"

    print(f"📝 Generating manifest for prompt: '{prompt}'")
    print(f"🔑 Correlation ID: {correlation_id}")
    print()

    manifest = await injector.generate_dynamic_manifest_async(
        correlation_id=correlation_id,
        user_prompt=prompt,
        force_refresh=True,
    )

    print("=" * 80)
    print("MANIFEST STRUCTURE")
    print("=" * 80)
    print()

    # Display metadata
    if "manifest_metadata" in manifest:
        print("📋 MANIFEST METADATA:")
        print("-" * 80)
        metadata = manifest["manifest_metadata"]
        for key, value in metadata.items():
            print(f"  {key}: {value}")
        print()

    # Display patterns section
    if "patterns" in manifest:
        patterns = manifest["patterns"]
        print("🎯 PATTERNS SECTION:")
        print("-" * 80)
        available = patterns.get("available", [])
        print(f"  Total patterns: {len(available)}")
        print()

        if available:
            print("  Sample patterns (first 3):")
            for i, pattern in enumerate(available[:3], 1):
                print(f"\n  Pattern {i}:")
                print(f"    Name: {pattern.get('name', 'N/A')}")
                print(f"    File: {pattern.get('file', 'N/A')[:80]}...")
                print(f"    Confidence: {pattern.get('confidence', 'N/A')}")
                print(f"    Node Types: {pattern.get('node_types', [])}")
                print(f"    Instance Count: {pattern.get('instance_count', 0)}")
                desc = pattern.get("description", "")
                if desc:
                    print(f"    Description: {desc[:200]}...")
        print()

    # Display debug intelligence section
    if "debug_intelligence" in manifest:
        debug = manifest["debug_intelligence"]
        print("🔍 DEBUG INTELLIGENCE:")
        print("-" * 80)
        print(f"  Total similar workflows: {debug.get('total_similar_workflows', 0)}")

        successes = debug.get("successful_approaches", [])
        failures = debug.get("failed_approaches", [])

        print(f"  Successful approaches: {len(successes)}")
        print(f"  Failed approaches: {len(failures)}")
        print()

        if successes:
            print("  ✅ Sample successful approaches (first 3):")
            for i, success in enumerate(successes[:3], 1):
                print(f"\n    {i}. Agent: {success.get('agent_name', 'N/A')}")
                print(f"       Prompt: {success.get('user_prompt', 'N/A')[:60]}...")
                print(f"       Quality: {success.get('quality_score', 'N/A')}")
                print(f"       Execution: {success.get('execution_time_ms', 'N/A')}ms")

        if failures:
            print("\n  ❌ Sample failed approaches (first 3):")
            for i, failure in enumerate(failures[:3], 1):
                print(f"\n    {i}. Agent: {failure.get('agent_name', 'N/A')}")
                print(f"       Prompt: {failure.get('user_prompt', 'N/A')[:60]}...")
                print(f"       Error: {failure.get('error_message', 'N/A')[:60]}...")
        print()

    # Display models section
    if "models" in manifest:
        models = manifest["models"]
        print("🤖 MODELS SECTION:")
        print("-" * 80)

        available_models = models.get("available", [])
        print(f"  Total models: {len(available_models)}")

        if available_models:
            print("\n  Sample models (first 5):")
            for i, model in enumerate(available_models[:5], 1):
                print(f"    {i}. {model.get('name', 'N/A')}")
                print(f"       Provider: {model.get('provider', 'N/A')}")
                print(f"       Context: {model.get('context_window', 'N/A')} tokens")
                print(f"       Cost: ${model.get('cost_per_1k_tokens', 'N/A')}/1k")
        print()

    # Display archon_search section
    if "archon_search" in manifest:
        search = manifest["archon_search"]
        print("🔎 ARCHON SEARCH:")
        print("-" * 80)
        print(f"  Status: {search.get('status', 'N/A')}")
        print(f"  Endpoint: {search.get('endpoint', 'N/A')}")

        capabilities = search.get("capabilities", [])
        if capabilities:
            print(f"  Capabilities: {', '.join(capabilities)}")
        print()

    # Display infrastructure section
    if "infrastructure" in manifest:
        infra = manifest["infrastructure"]
        print("🏗️ INFRASTRUCTURE:")
        print("-" * 80)

        for service_name, service_info in infra.items():
            if isinstance(service_info, dict):
                print(f"  {service_name}:")
                print(f"    Status: {service_info.get('status', 'N/A')}")
                print(f"    Endpoint: {service_info.get('endpoint', 'N/A')}")
                if "collections" in service_info:
                    print(f"    Collections: {service_info['collections']}")
        print()

    # Display database_schemas section
    if "database_schemas" in manifest:
        schemas = manifest["database_schemas"]
        print("🗄️ DATABASE SCHEMAS:")
        print("-" * 80)

        tables = schemas.get("tables", [])
        print(f"  Total tables: {len(tables)}")

        if tables:
            print("\n  Sample tables (first 5):")
            for i, table in enumerate(tables[:5], 1):
                print(f"    {i}. {table.get('name', 'N/A')}")
                print(f"       Purpose: {table.get('purpose', 'N/A')[:60]}...")
                columns = table.get("columns", [])
                print(f"       Columns: {len(columns)}")
        print()

    # Summary statistics
    print("=" * 80)
    print("MANIFEST SUMMARY")
    print("=" * 80)
    print(f"  Total sections: {len(manifest)}")
    print(f"  Top-level keys: {', '.join(manifest.keys())}")

    # Approximate size
    manifest_str = json.dumps(manifest, default=str)
    print(f"  Approximate size: {len(manifest_str):,} characters")
    print()

    print("✅ Manifest generation complete!")
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
